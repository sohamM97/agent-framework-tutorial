import os
from pathlib import Path

# TODO: learn more about ChatClient vs ChatCompletionClient
from agent_framework.openai import OpenAIChatCompletionClient
from dotenv import load_dotenv
from openai import AsyncAzureOpenAI, Timeout

load_dotenv(Path(__file__).parent / ".env")

# Claude: we build the Azure client ourselves so we can control the connect timeout
# and retry count. OpenAIChatCompletionClient does not expose those, but it accepts a
# pre-built async_client (agent_framework_openai/_chat_completion_client.py:288). The
# openai SDK default is only a 5-second connect timeout with 2 retries
# (openai/_constants.py:9), which is what let one brief network stall abort a whole
# workflow run. We widen the connect window and add a few retries so short-lived
# network blips recover on their own (the SDK retries connect/timeout errors with
# backoff). Note: retries can't help if the endpoint is genuinely unreachable.
async_client = AsyncAzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    # Claude: no AZURE_OPENAI_API_VERSION in .env, so fall back to the same default
    # the framework uses (agent_framework_openai/_chat_completion_client.py:88).
    api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
    # Claude: Timeout(total, connect=...) — total response budget stays 600s, but the
    # connect budget goes 5s -> 15s. openai.Timeout is just httpx.Timeout re-exported.
    timeout=Timeout(600.0, connect=15.0),
    max_retries=5,
)

# Claude: passing async_client keeps us on Azure and skips the client's own env
# lookup; we still pass model (the deployment name), which is sent as the deployment
# on each request. base_url is no longer needed here — the async_client owns the URL.
client = OpenAIChatCompletionClient(
    model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    async_client=async_client,
)
