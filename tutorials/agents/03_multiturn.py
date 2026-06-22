import asyncio
import os

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential
from dotenv import load_dotenv

load_dotenv()


async def agent():
    client = FoundryChatClient(
        project_endpoint=os.environ.get("FOUNDRY_PROJECT_ENDPOINT"),
        model=os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME"),
        credential=AzureCliCredential(),
    )

    agent = Agent(
        client=client,
        name="ConversationAgent",
        instructions="You are a friendly assistant. Keep your answers brief.",
    )

    # Create a session to maintain conversation history
    session = agent.create_session()

    # First turn
    result = await agent.run("My name is Alice and I love hiking.", session=session)
    print(f"Agent: {result}\n")

    # Second turn — the agent should remember the user's name and hobby
    result = await agent.run("What do you remember about me?", session=session)
    print(f"Agent: {result}")


if __name__ == "__main__":
    asyncio.run(agent())
