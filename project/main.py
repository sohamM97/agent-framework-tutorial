import asyncio
import os
from pathlib import Path
from typing import Annotated, Optional

from agent_framework import Agent, AgentResponse, AgentSession, Message, tool

# TODO: learn more about ChatClient vs ChatCompletionClient
from agent_framework.openai import OpenAIChatCompletionClient
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

# TODO: something with context provider


class UserSatisfaction(BaseModel):
    # TODO: Claude Review: consider adding a `reasoning: str` field before
    # `satisfied` to give the model room to think — usually improves accuracy.
    satisfied: bool


# Unused for now. Was using it when I had asked the agent to output just the
# text and filename, and was writing to file myself.
class ProposalFileDetails(BaseModel):
    filename: str
    proposal: str


# TODO: facing some issue in always_require. Have to look into that.
@tool(approval_mode="never_require")
def write_to_file(
    # TODO: is annotation required for the LLM? Or just for us?
    filename: Annotated[str, Field(description="The name of the file to create")],
    contents: Annotated[str, Field(description="The contents to write in the file")],
    filepath: Annotated[
        str, Field(description="The path at which to write the file")
    ] = "outputs",
):
    file_loc = Path(filepath) / filename
    with open(file_loc, "w") as f:
        f.write(contents)


async def run_agent(
    agent: Agent,
    message: str | Message | list[Message] = "",
    session: Optional[AgentSession] = None,
    options: Optional[dict] = None,
    # TODO: when options are given, the message is the final json
    # Is there any way to show a proper msg as well as a json?
    # If not, we can get rid of this extra flag.
    show_message: bool = True,
) -> AgentResponse:
    response = await agent.run(
        message, session=session, stream=show_message, options=options
    )

    if show_message:
        print("\n[AGENT]: ...")
        async for chunk in response:
            if chunk.text:
                print(chunk.text, end="", flush=True)
        print()

    final_response = await response.get_final_response() if show_message else response
    return final_response


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
    # summarize) is driven per-run below, which is an intentional design
    # choice.
    # TODO: does this lead to infinite questions till i explictly ask to stop?
    # Yes kinda does. need cap on no. of messages as a safeguard. also clearer
    # system prompts so that the agent does not just keep blabbering on.
    # Shouldn't just depend on user's satisfaction, as user is never gonna be
    # satisfied while agent keeps on asking. Maybe it should be based on the
    # agent's satisfaction.
    sm_agent = Agent(
        client=client,
        name="AgentSoham",
        instructions="You are Soham, the lead developer of AIStudio Team. Your"
        " job is to take requests from the user and convert them into concrete"
        " software products. The requests can be features, bugfixes, "
        "deployments, implementations or anything technical, really."
        "Encourage the user to be as detailed as possible while asking for "
        "requirements. Always adopt a friendly tone with the user. Keep asking"
        " the user follow-up questions and clarifications till he is satisfied"
        " with the proposal. Keep your statements concise - within a 100 words"
        ", unless absolutely necessary. Do NOT suggest him to input images"
        " or screenshots since you don't have that capability right now."
        " DO NOT generate any code samples, that is not your job.",
        # TODO: maybe to prevent it from arbitrarily writing code, the earlier
        # approach where WE output the file, is a better approach. The agent
        # responsible for writing code can use it as a tool.
        tools=[write_to_file],
    )

    session = sm_agent.create_session()

    # TODO: multi-intent agent like stop, exit etc.
    sf_agent = Agent(
        client=client,
        name="SatisfactionAgent",
        instructions="You are an agent who is tasked with going thru the "
        "conversation and figuring out whether Agent Soham has all the "
        "requirements necessary for the final solution. Output true if the "
        "agent doesn't need to ask the user any more questions to draft the "
        "final proposal. Output false if you feel the agent needs more inputs "
        "from the user before drafting the final project plan.",
    )

    bot_message = await run_agent(
        agent=sm_agent,
        message=Message(
            role="system", contents=["Greet the user, and ask him his requirements."]
        ),
        session=session,
    )
    bot_message = bot_message.text

    while True:
        user_response = await take_input_from_user()

        bot_message = await run_agent(
            agent=sm_agent, message=user_response, session=session
        )
        bot_message = bot_message.text

        # TODO: Claude Review: (#2 session pollution) sf_agent runs on the
        # shared session, so its empty-input + {satisfied} verdict gets written
        # back into sm_agent's history (InMemoryHistoryProvider stores messages
        # in session state — _sessions.py:838/854). Fix: read the transcript
        # via `session.state.get("messages", [])` and pass it as the judge's
        # `message` WITHOUT a session=, so the judge stays stateless and writes
        # nothing back. (Optionally append a trailing user Message telling it to
        # output its verdict now.)
        user_satisfaction_info = await run_agent(
            agent=sf_agent,
            session=session,
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

    # once user is satisfied

    await run_agent(
        agent=sm_agent,
        message=Message(
            role="system",
            contents=[
                "Generate a proposal file name relevant to the discussion and "
                "write the proposal to the file using the write_to_file tool. "
                "Once that is done, summarize the discussion, tell the user "
                "that the proposal file is present, give him the path, and "
                "tell him he will have a finished product shortly. DO NOT ask "
                "any questions at this stage, as this is supposed to be the "
                "final approach."
            ],
        ),
        session=session,
    )

    # TODO: maybe a summary of the transcript too. With confirmation from user.


if __name__ == "__main__":
    asyncio.run(main())
