import os
from pathlib import Path

# TODO: learn more about ChatClient vs ChatCompletionClient
from agent_framework.openai import OpenAIChatCompletionClient
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

client = OpenAIChatCompletionClient(
    model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    # TODO: is there also a param called azure_endpoint?
    base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
)
