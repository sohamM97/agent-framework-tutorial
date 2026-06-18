import asyncio
from typing import Optional

from agent_framework import Agent, AgentResponse, AgentSession, Message
from agents import sf_agent, sm_agent, xl_agent
from pydantic import BaseModel
from tools import write_to_file

# TODO: something with context provider


class UserSatisfaction(BaseModel):
    # TODO: Claude Review: consider adding a `reasoning: str` field before
    # `satisfied` to give the model room to think — usually improves accuracy.
    # TODO: Claude Review: naming — the judge now decides whether the agent has
    # ENOUGH REQUIREMENTS, not whether the user is satisfied. `UserSatisfaction`
    # / `satisfied` is a misnomer; `RequirementsReady` / `ready` would match the
    # actual semantics (and reduce the model's confusion about what it judges).
    satisfied: bool


class ProposalFileDetails(BaseModel):
    filename: str
    proposal: str


# TODO: Claude Review: cognitive complexity is high (SonarQube: 22 > 15
# allowed) from the nested while/for/for/if. Extract the inner
# `for request in chunk.user_input_requests` body into an async helper
# `_collect_approvals(chunk) -> list` called per-chunk inside the stream loop
# (text printing stays inline). It returns that chunk's approval responses;
# the caller extends `pending` and flips the flag. Drops one nesting level.
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

    while has_user_input_requests:
        has_user_input_requests = False
        response = await agent.run(
            pending, session=session, stream=show_message, options=options
        )
        pending = []

        if show_message:
            print("\n[AGENT]: ...")
            async for chunk in response:
                if chunk.text:
                    print(chunk.text, end="", flush=True)

                if chunk.user_input_requests:
                    has_user_input_requests = True

                    for request in chunk.user_input_requests:
                        print("\nApproval needed:")
                        print(f" Function: {request.function_call.name}")
                        print(f" Arguments: {request.function_call.arguments}")
                        print("Enter 'y' or 'n'.")

                        approval_flag = await take_input_from_user()
                        approval_flag = approval_flag.lower() == "y"
                        pending.append(
                            request.to_function_approval_response(
                                approved=approval_flag
                            )
                        )
            print()

    final_response = (
        await response.get_final_response() if show_message and response else response
    )
    return final_response


async def take_input_from_user() -> str:
    return await asyncio.to_thread(input, "\n[USER]: ")


async def main():

    sm_session = sm_agent.create_session()

    await run_agent(
        agent=sm_agent,
        messages=Message(
            role="system", contents=["Greet the user, and ask him his requirements."]
        ),
        session=sm_session,
    )

    while True:
        user_response = await take_input_from_user()

        # Claude NOTE: sf_agent (the judge) shares sm_agent's session, so its input +
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
        user_satisfaction_info = await run_agent(
            agent=sf_agent,
            session=sm_session,
            messages=user_response,
            options={"response_format": UserSatisfaction},
            show_message=False,
        )

        satisfied = (
            user_satisfaction_info.value and user_satisfaction_info.value.satisfied
        )

        if satisfied:
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

    # once user is satisfied

    # TODO: need proper directory structure
    bot_response = await run_agent(
        agent=sm_agent,
        messages=Message(
            role="system",
            contents=[
                "Generate a proposal file name (just the name, not a full "
                "path) relevant to the discussion and the proposal itself. "
                "The file should be a markdown file."
            ],
        ),
        session=sm_session,
        options={"response_format": ProposalFileDetails},
        show_message=False,
    )
    proposal_details = bot_response.value

    # We write the proposal file ourselves to keep it deterministic. Else,
    # Agent Soham tended to write python scripts in spite of being instructed
    # against that in the system prompt.
    proposal_file_path = write_to_file(
        filename=proposal_details.filename, contents=proposal_details.proposal
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

    xl_session = xl_agent.create_session()

    await run_agent(
        agent=xl_agent,
        messages=Message(
            role="system",
            contents=[
                f"Read the contents of this proposal: {proposal_file_path} and"
                " code a working solution."
            ],
        ),
        session=xl_session,
    )

    # # Claude: debug view only — peek at the raw in-memory history. The default
    # # InMemoryHistoryProvider namespaces its state under source_id "in_memory"
    # # (_agents.py:475 → state.setdefault(provider.source_id, {})), so messages
    # # live at state["in_memory"]["messages"], not state["messages"]. Reaching
    # # in like this is NOT supported (MS docs: treat AgentSession as opaque) —
    # # fine for eyeballing, including the sf_agent session pollution.
    # print("******* FINAL TRANSCRIPT **************")
    # for message in session.state.get("in_memory", {}).get("messages", []):
    #     # Claude: author_name is the agent that produced it (AgentSoham /
    #     # SatisfactionAgent); falls back to the bare role (user/system/tool).
    #     who = message.author_name or message.role
    #     print(f"[{who}]: {message.text}")
    # print("***************************************")

    # TODO: maybe a summary of the transcript too. With confirmation from user.


if __name__ == "__main__":
    asyncio.run(main())
