import asyncio
import os
from typing import Optional

from agent_framework import Agent, AgentSession, Message

# TODO: learn more about ChatClient vs ChatCompletionClient
from agent_framework.openai import OpenAIChatCompletionClient
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class UserSatisfaction(BaseModel):
    # TODO: Claude Review: consider adding a `reasoning: str` field before
    # `satisfied` to give the model room to think — usually improves accuracy.
    satisfied: bool


async def run_agent(
    agent: Agent,
    prompt: str | Message | list[Message],
    session: AgentSession,
    options: Optional[dict] = None,
) -> Optional[BaseModel]:
    # TODO: Claude Review: don't stream decision/structured calls — when options
    # is set we never iterate chunks, so stream=True just adds overhead. Stream
    # only user-facing turns; use stream=False for the structured branch.
    response = await agent.run(prompt, session=session, stream=True, options=options)

    if options:
        # https://learn.microsoft.com/en-us/agent-framework/agents/structured-outputs?pivots=programming-language-python
        final_response = await response.get_final_response()
        return final_response.value

    else:
        print("\n[AGENT]: ...")
        async for chunk in response:
            if chunk.text:
                print(chunk.text, end="", flush=True)
        print()


async def take_input_from_user() -> str:
    return await asyncio.to_thread(input, "\n[USER]: ")


async def main():

    client = OpenAIChatCompletionClient(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        # TODO: is there also a param called azure_endpoint?
        base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
    )

    # Standing persona/behavior (role, friendly tone, conciseness) lives in
    # instructions — it's true every turn. Per-turn control (greet/propose/
    # summarize) is driven per-run below, which is an intentional design choice.
    sm_agent = Agent(
        client=client,
        name="AgentSoham",
        instructions="You are Soham, the lead developer of AIStudio Team. Your"
        " job is to take requests from the user and convert them into concrete"
        " software products. The requests can be features, bugfixes, "
        "deployments, implementations or anything technical, really."
        "Always adopt a friendly tone with the user. "
        "Keep your statements concise - within a 100 words,"
        "unless absolutely necessary.",
    )

    # TODO: can we achieve the entire thing in a single loop?

    session = sm_agent.create_session()

    await run_agent(
        agent=sm_agent,
        prompt=Message(
            role="system", contents=["Greet the user, and ask him his requirements."]
        ),
        session=session,
    )

    req = await take_input_from_user()

    await run_agent(
        agent=sm_agent,
        prompt=[
            Message(
                role="system",
                contents=[
                    "The following is the user's requirement. "
                    "Propose him a solution."
                    "If needed, ask him follow up questions. If you're not "
                    "asking follow-ups, Ask the user if he is satisfied with "
                    "this proposal, or whether he wants to discuss it further."
                ],
            ),
            Message(role="user", contents=[req]),
        ],
        session=session,
    )

    # TODO: Claude Review: run the satisfaction classifier on a SEPARATE session
    # (or a small dedicated agent), not `session`. Right now each structured call
    # appends its "figure out if satisfied" prompt + JSON answer into the shared
    # history, polluting the user-facing thread and wasting tokens. Keep the
    # decision out-of-band (lightweight LLM-as-judge pattern).
    # TODO: Claude Review: loop-and-a-half — this take-input + classify block is
    # duplicated inside the loop. Collapse to a single `while True:` with a
    # `break`, and factor the classifier prompt into one helper.
    user_response = await take_input_from_user()

    user_satisfaction_info = await run_agent(
        agent=sm_agent,
        prompt=[
            Message(
                role="system",
                contents=[
                    "The following is the user's response to your "
                    "solution. Figure out if the user is satisfied it. In case"
                    " he wants to discuss this further, assume he isn't "
                    "satisfied just yet."
                ],
            ),
            Message(role="user", contents=[user_response]),
        ],
        session=session,
        options={"response_format": UserSatisfaction},
    )

    satisfied = user_satisfaction_info and user_satisfaction_info.satisfied

    while not satisfied:
        await run_agent(
            agent=sm_agent,
            prompt="The user is not entirely satisfied with your solution. "
            "He needs to discuss some more points before giving a go ahead."
            "Clarify whatever he needs and then ask him again whether we're "
            "good to go.",
            session=session,
        )

        user_response = await take_input_from_user()

        user_satisfaction_info = await run_agent(
            agent=sm_agent,
            prompt="The following is the user's response to your solution: "
            f"`{user_response}`. Figure out if the user is satisfied. In "
            "case he wants to discuss this further, assume he isn't satisfied "
            "just yet.",
            session=session,
            options={"response_format": UserSatisfaction},
        )

        satisfied = user_satisfaction_info and user_satisfaction_info.satisfied

    # once user is satisfied

    await run_agent(
        agent=sm_agent,
        prompt="Summarize the discussion you had with the user, the "
        "deliverables, and tell the user you will return with the finished "
        "product shortly.",
        session=session,
    )


if __name__ == "__main__":
    asyncio.run(main())
