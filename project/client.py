import os
from pathlib import Path

# TODO: learn more about ChatClient vs ChatCompletionClient
from agent_framework.openai import OpenAIChatCompletionClient
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

client = OpenAIChatCompletionClient(
    model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    # There is also another parameter called base_url. If we use that,
    # the endpoint we provide needs to end with /openai/v1. For example:
    # https://<your azure openai resource>.openai.azure.com/openai/v1
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
)
