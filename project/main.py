import asyncio
from typing import Optional

from agent_framework import Agent, AgentResponse, AgentSession, Message
from agents import amma_agent, judge_agent, sm_agent, xl_agent
from constants import OUTPUTS_DIR
from models import ProjectDetails
from tools import write_to_file

# TODO: something with context provider
# TODO: how to incorporate workflows into all this.
# TODO: difference between session and context?

# TODO: overall flow:
# 1. Loop of Soham agent asking asking reqs till satisfied (done)
# 2. Loop of XL coding and Amma reviewing till Amma satisfied (done)
# 3. Loop of Vivek reviewing, XL coding, amma reviewing till vivek satisfied

# TODO: how can workflows simplify the above flow?
# maybe handoff can switch seamlessly between the agents without the defined
# flow. good for cases like "i have so and so source code already, review it"
# which will trigger amma agent directly instead of going thru the whole flow.


async def _collect_approvals(chunk, agent_name: str) -> list:
    approvals = []

    for request in chunk.user_input_requests:
        print(f"\n{agent_name} needs approval:")
        print(f" Function: {request.function_call.name}")
        print(f" Arguments: {request.function_call.arguments}")
        print("Enter 'y' or 'n'.")

        approval_flag = await take_input_from_user()
        approval_flag = approval_flag.lower() == "y"
        approvals.append(request.to_function_approval_response(approved=approval_flag))

    return approvals


async def run_agent(
    agent: Agent,
    messages: str | Message | list[Message] = "",
    session: Optional[AgentSession] = None,
    options: Optional[dict] = None,
    # TODO: when options are given, the message is the final json
    # Is there any way to show a proper msg as well as a json?
    # If not, we can get rid of this extra flag.
    # TODO: Claude Review: naming — `show_message` undersells what it controls
    # (streaming + console printing + the whole approval loop + the return
    # path). Something like `interactive` or `stream` names the real axis.
    show_message: bool = True,
) -> Optional[AgentResponse]:

    has_user_input_requests = True
    response = None

    # Claude: working list of messages to send on the next agent.run. Accept a
    # single str/Message or a ready-made list of Messages without nesting the
    # latter.
    pending: list = list(messages) if isinstance(messages, list) else [messages]

    if not show_message:
        return await agent.run(pending, session=session, options=options)

    while has_user_input_requests:
        has_user_input_requests = False
        response = await agent.run(
            pending, session=session, stream=True, options=options
        )
        pending = []

        print(f"\n[AGENT {agent.name}]: ...")
        async for chunk in response:
            if chunk.text:
                print(chunk.text, end="", flush=True)

            if chunk.user_input_requests:
                has_user_input_requests = True
                approvals = await _collect_approvals(chunk, agent.name)
                pending.extend(approvals)

        print()

    final_response = await response.get_final_response() if response else response
    return final_response


async def take_input_from_user() -> str:
    return await asyncio.to_thread(input, "\n[USER]: ")


async def main():

    sm_session = sm_agent.create_session()

    await run_agent(
        agent=sm_agent,
        # System messages must be developer-controlled. Never inject user input
        # into system messages.
        # Source: https://learn.microsoft.com/en-us/agent-framework/agents/safety#keep-system-messages-developer-controlled
        messages=Message(
            role="system", contents=["Greet the user, and ask him his requirements."]
        ),
        session=sm_session,
    )

    while True:
        user_response = await take_input_from_user()

        # Claude NOTE: judge_agent (the judge) shares sm_agent's session, so its input +
        # {satisfied} verdict get written into the history that BOTH agents
        # replay each turn ("session pollution"). Consequences, accepted for
        # now since conversations are short:
        #   1. The judge re-reads its own past verdicts and can anchor on them
        #      — a likely cause of the occasional wrong "True".
        #   2. sm_agent sees the JSON verdicts as its own assistant turns (the
        #      wire format keys off role, not author_name), so it can drift
        #      off-persona as they accumulate.
        #   3. Token bloat: every verdict is replayed on all later runs, growing
        #      with the conversation.
        # Decoupling fix if this ever bites: hand the judge its own transcript
        # and run it WITHOUT session= so it stays stateless and writes nothing
        # back. Don't scrape session.state to build that transcript — MS docs
        # say treat AgentSession as opaque:
        # https://learn.microsoft.com/en-us/agent-framework/agents/conversations/storage
        req_ready_info = await run_agent(
            agent=judge_agent,
            session=sm_session,
            messages=user_response,
            show_message=False,
        )

        ready = req_ready_info.value and req_ready_info.value.ready

        if ready:
            print(
                "\n[AGENT]: Looks like we have everything we need. Should we "
                "proceed with the final proposal? (y/n)"
            )
            final = await take_input_from_user()
            if final.lower() == "y":
                break
            # TODO: Claude Review: (#3) on a non-"y" answer, `final` is
            # discarded and the loop just re-prompts — the user's redirection
            # is lost. Feed `final` into sm_agent so they can course-correct.

        await run_agent(agent=sm_agent, messages=user_response, session=sm_session)

    # once all requirements are ready

    bot_response = await run_agent(
        agent=sm_agent,
        messages=Message(
            role="system",
            contents=[
                "Generate a project name and a proposal based on your "
                "discussion. The project name should be in snake_case. "
                "The proposal contents should be in markdown format."
            ],
        ),
        session=sm_session,
        options={"response_format": ProjectDetails},
        show_message=False,
    )
    proposal_details = bot_response.value

    # Create a project directory that will consist of the proposal and the
    # project source code
    # TODO: Claude Review: path-kind discrepancy — `project_path` is RELATIVE
    # (Path("outputs")/...), but `proposal_file_path` returned below is ABSOLUTE
    # (BASE_DIR-rooted by write_to_file). The xl_agent prompt interpolates both,
    # so the agent sees one absolute and one relative path. It works only because
    # write_to_file re-roots every filepath under BASE_DIR — a latent footgun if
    # that ever changes. Make them consistent: either root project_path at
    # BASE_DIR too, or have write_to_file return a path relative to BASE_DIR.
    project_path = OUTPUTS_DIR / proposal_details.project_name

    # We write the proposal file ourselves to keep it deterministic. Else,
    # Agent Soham tended to write python scripts in spite of being instructed
    # against that in the system prompt.
    proposal_file_path = write_to_file(
        filename="proposal.md",
        contents=proposal_details.proposal,
        filepath=project_path,
    )

    await run_agent(
        agent=sm_agent,
        messages=Message(
            role="system",
            contents=[
                "Summarize the discussion, tell the user "
                f"that the proposal file is present at {proposal_file_path}, "
                "give him the name, and tell him he will have a finished "
                "product shortly. DO NOT ask any questions at this stage, as "
                "this is supposed to be the "
                "final approach."
            ],
        ),
        session=sm_session,
    )

    # Note: Agents with tools always need sessions.
    # TODO: investigate why
    # TODO: what about sharing sessions like sm_agent and judge_agent?
    xl_session = xl_agent.create_session()

    await run_agent(
        agent=xl_agent,
        messages=Message(
            role="system",
            contents=[
                f"Read the contents of this proposal: {proposal_file_path} and"
                f" code a working solution at {project_path / 'out'} "
                "directory. IMPORTANT: All project related files (source code,"
                " readme etc.) should be mandatorily inside the 'out' "
                "directory. Once you are done coding, inform the user and give"
                " him the path where your code is."
            ],
        ),
        session=xl_session,
    )

    # TODO: error handling - if code is not generated because of any error,
    # goes in infinite loop. Add a flag for review success or failure
    # TODO: Claude Review: unbounded `while True` — if Amma never returns
    # lgtm=True, XL and Amma ping-pong forever, each round costing model calls
    # (Amma runs at reasoning_effort="high"). Add a max_rounds cap, same
    # safeguard the Soham loop's TODO calls for in agents.py.
    # Claude NOTE: a workflow gives this cap for free — WorkflowBuilder takes a
    # max_iterations arg (default 100) that limits how many rounds the engine
    # runs, so an Amma<->XL review loop built as a workflow can't run forever.
    # See agent_framework/_workflows/_workflow_builder.py:80 (and _runner.py).

    while True:
        amma_session = amma_agent.create_session()
        # TODO: agent hallucinates file names which are not present at the out
        # directory. give it a list files tool.
        code_review = await run_agent(
            agent=amma_agent,
            messages=Message(
                role="system",
                contents=[f"Review the code under directory: {project_path / 'out'}"],
            ),
            session=amma_session,
        )
        if not code_review.value:
            raise ValueError("LLM failed to return value")

        if code_review.value.lgtm or not code_review.value.success:
            break

        # TODO: make sure agent reads existing files using read tool also to
        # verify review points. Till now was only using write tools.
        await run_agent(
            agent=xl_agent,
            messages=Message(
                role="system",
                contents=[
                    "Code review has flagged the following issues: "
                    + code_review.value.comments
                    + " Fix them. If needed, make sure you read existing code "
                    + "to verify correctness before writing your fixes."
                ],
            ),
            session=xl_session,
        )

    # # Claude: debug view only — peek at the raw in-memory history. The default
    # # InMemoryHistoryProvider namespaces its state under source_id "in_memory"
    # # (_agents.py:475 → state.setdefault(provider.source_id, {})), so messages
    # # live at state["in_memory"]["messages"], not state["messages"]. Reaching
    # # in like this is NOT supported (MS docs: treat AgentSession as opaque) —
    # # fine for eyeballing, including the judge_agent session pollution.
    # print("******* FINAL TRANSCRIPT **************")
    # for message in session.state.get("in_memory", {}).get("messages", []):
    #     # Claude: author_name is the agent that produced it (SohamAgent /
    #     # JudgeAgent); falls back to the bare role (user/system/tool).
    #     who = message.author_name or message.role
    #     print(f"[{who}]: {message.text}")
    # print("***************************************")

    # TODO: maybe a summary of the transcript too. With confirmation from user.


if __name__ == "__main__":
    asyncio.run(main())
