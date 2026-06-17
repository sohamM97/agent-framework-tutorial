import asyncio
import os
from typing import Optional

from agent_framework import Agent, AgentSession, Message

# TODO: learn more about ChatClient vs ChatCompletionClient
from agent_framework.openai import OpenAIChatCompletionClient
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

# TODO: something with context provider


class UserSatisfaction(BaseModel):
    # TODO: Claude Review: consider adding a `reasoning: str` field before
    # `satisfied` to give the model room to think — usually improves accuracy.
    satisfied: bool


async def run_agent(
    agent: Agent,
    message: str | Message | list[Message],
    session: Optional[AgentSession] = None,
    options: Optional[dict] = None,
) -> Optional[BaseModel]:
    # TODO: Claude Review: don't stream decision/structured calls — when options
    # is set we never iterate chunks, so stream=True just adds overhead. Stream
    # only user-facing turns; use stream=False for the structured branch.
    response = await agent.run(message, session=session, stream=True, options=options)

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
        final_response = await response.get_final_response()
        return final_response.text


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
    # TODO: does this lead to infinite questions till i explictly ask to stop?
    # Yes kinda does. need cap on no. of messages as a safeguard. also clearer
    # system prompts so that the agent does not just keep blabbering on.
    # Shouldn't just depend on user's satisfaction, as user is never gonna be
    # satisfied while agent keeps on asking.
    sm_agent = Agent(
        client=client,
        name="AgentSoham",
        instructions="You are Soham, the lead developer of AIStudio Team. Your"
        " job is to take requests from the user and convert them into concrete"
        " software products. The requests can be features, bugfixes, "
        "deployments, implementations or anything technical, really."
        "Always adopt a friendly tone with the user. Keep asking the user "
        "follow-up questions and clarifications till he is satisfied with the "
        "proposal. Keep your statements concise - within a 100 words,"
        "unless absolutely necessary. Do NOT suggest him to input images"
        "or screenshots since you don't have that capability right now.",
    )

    # TODO: multi-intent agent like stop, exit etc.
    sf_agent = Agent(
        client=client,
        name="SatisfactionAgent",
        instructions="You are an agent who is tasked with analysing the user's"
        " response, and figuring out whether the user is satisfied with the "
        "proposed solution. In case he is stating his requirements, wants to "
        "discuss further, and so on, assume he isn't satisfied just yet.",
    )

    session = sm_agent.create_session()

    bot_message = await run_agent(
        agent=sm_agent,
        message=Message(
            role="system", contents=["Greet the user, and ask him his requirements."]
        ),
        session=session,
    )

    while True:
        user_response = await take_input_from_user()
        user_satisfaction_info = await run_agent(
            agent=sf_agent,
            message=[
                Message(
                    role="user",
                    contents=[
                        f"Assistant's proposal:"
                        f"\n{bot_message}"
                        "\n\nUser's reply:"
                        f"\n{user_response}"
                    ],
                )
            ],
            options={"response_format": UserSatisfaction},
        )

        satisfied = user_satisfaction_info and user_satisfaction_info.satisfied

        if satisfied:
            break

        bot_message = await run_agent(
            agent=sm_agent, message=user_response, session=session
        )

    # once user is satisfied

    await run_agent(
        agent=sm_agent,
        message=Message(
            role="system",
            contents=[
                "Summarize the discussion you had with the user, the "
                "deliverables, and tell the user you will return with the "
                "finished product shortly."
            ],
        ),
        session=session,
    )
    # TODO: a tool to output the plan in a text file. maybe a summary of the transcript too.
    # With confirmation from user.


if __name__ == "__main__":
    asyncio.run(main())
