import asyncio
import os
from random import randint
from typing import Annotated

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential
from dotenv import load_dotenv
from pydantic import Field

load_dotenv()


# NOTE: approval_mode="never_require" is for sample brevity.
# Use "always_require" in production for user confirmation before tool execution.
@tool(approval_mode="never_require")
def get_weather(
    location: Annotated[str, Field(description="The location to get the weather for.")],
) -> str:
    """Get the weather for a given location."""
    conditions = ["sunny", "cloudy", "rainy", "stormy"]
    return f"The weather in {location} is {conditions[randint(0, 3)]} with a high of {randint(10, 30)}°C."


async def agent(location: str):
    client = FoundryChatClient(
        project_endpoint=os.environ.get("FOUNDRY_PROJECT_ENDPOINT"),
        model=os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME"),
        credential=AzureCliCredential(),
    )

    agent = Agent(
        client=client,
        name="WeatherAgent",
        instructions="You are a helpful weather agent. Use the get_weather tool to answer questions.",
        tools=[get_weather],
    )

    user_query = f"Tell me about the weather in {location}"

    print(f"User: {user_query}")

    print("Agent (streaming): ", end="", flush=True)
    async for chunk in agent.run(user_query, stream=True):
        if chunk.text:
            print(chunk.text, end="", flush=True)
    print()


if __name__ == "__main__":
    location = input("Which location's weather do you want? ")
    asyncio.run(agent(location))
