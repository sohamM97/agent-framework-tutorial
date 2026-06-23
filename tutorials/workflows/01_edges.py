# Source: https://learn.microsoft.com/en-us/agent-framework/workflows/edges?pivots=programming-language-python

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from agent_framework import (
    AgentExecutor,
    AgentExecutorRequest,
    AgentExecutorResponse,
    Case,
    Default,
    Message,
    WorkflowBuilder,
    WorkflowContext,
    executor,
)
from agent_framework.openai import OpenAIChatCompletionClient, OpenAIChatOptions
from azure.identity import AzureCliCredential
from dotenv import load_dotenv
from pydantic import BaseModel
from typing_extensions import Never

load_dotenv()


class DetectionResult(BaseModel):
    """Represents the result of spam detection."""

    # is_spam drives the routing decision taken by edge conditions
    is_spam: bool
    # Human readable rationale from the detector
    reason: str
    # The agent must include the original email so downstream agents can operate without reloading content
    email_content: str


class EmailResponse(BaseModel):
    """Represents the response from the email assistant."""

    # The drafted reply that a user could copy or send
    response: str


def get_condition(expected_result: bool):
    """Create a condition callable that routes based on DetectionResult.is_spam."""

    # The returned function will be used as an edge predicate.
    # It receives whatever the upstream executor produced.
    def condition(message: Any) -> bool:
        # Defensive guard. If a non AgentExecutorResponse appears, let the edge pass to avoid dead ends.
        if not isinstance(message, AgentExecutorResponse):
            return True

        try:
            # Prefer parsing a structured DetectionResult from the agent JSON text.
            # Using model_validate_json ensures type safety and raises if the shape is wrong.
            # Soham: In the original example, it was "message.agent_run_response.text", which is wrong
            detection = DetectionResult.model_validate_json(message.agent_response.text)
            # Route only when the spam flag matches the expected path.
            return detection.is_spam == expected_result
        except Exception:
            # Fail closed on parse errors so we do not accidentally route to the wrong path.
            # Returning False prevents this edge from activating.
            return False

    return condition


@executor(id="send_email")
async def handle_email_response(
    response: AgentExecutorResponse, ctx: WorkflowContext[Never, str]
) -> None:
    """Handle legitimate emails by drafting a professional response."""
    # Downstream of the email assistant. Parse a validated EmailResponse and yield the workflow output.
    email_response = EmailResponse.model_validate_json(response.agent_response.text)
    await ctx.yield_output(f"Email sent:\n{email_response.response}")


@executor(id="handle_spam")
async def handle_spam_classifier_response(
    response: AgentExecutorResponse, ctx: WorkflowContext[Never, str]
) -> None:
    """Handle spam emails by marking them appropriately."""
    # Spam path. Confirm the DetectionResult and yield the workflow output. Guard against accidental non spam input.
    detection = DetectionResult.model_validate_json(response.agent_response.text)
    if detection.is_spam:
        await ctx.yield_output(f"Email marked as spam: {detection.reason}")
    else:
        # This indicates the routing predicate and executor contract are out of sync.
        raise RuntimeError("This executor should only handle spam messages.")


@executor(id="to_email_assistant_request")
async def to_email_assistant_request(
    response: AgentExecutorResponse, ctx: WorkflowContext[AgentExecutorRequest]
) -> None:
    """Transform spam detection response into a request for the email assistant."""
    # Parse the detection result and extract the email content for the assistant
    detection = DetectionResult.model_validate_json(response.agent_response.text)

    # Create a new request for the email assistant with the original email content
    request = AgentExecutorRequest(
        messages=[Message(role="user", contents=[detection.email_content])],
        should_respond=True,
    )
    await ctx.send_message(request)


async def main() -> None:
    # Create agents
    # AzureCliCredential uses your current az login. This avoids embedding secrets in code.
    chat_client = OpenAIChatCompletionClient(
        model=os.environ["AZURE_OPENAI_CHAT_COMPLETION_MODEL"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        # api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        credential=AzureCliCredential(),
    )

    # Agent 1. Classifies spam and returns a DetectionResult object.
    # response_format enforces that the LLM returns parsable JSON for the Pydantic model.
    spam_detection_agent = AgentExecutor(
        chat_client.as_agent(
            instructions=(
                "You are a spam detection assistant that identifies spam emails. "
                "Always return JSON with fields is_spam (bool), reason (string), and email_content (string). "
                "Include the original email content in email_content."
            ),
            default_options=OpenAIChatOptions[Any](response_format=DetectionResult),
        ),
        id="spam_detection_agent",
    )

    # Agent 2. Drafts a professional reply. Also uses structured JSON output for reliability.
    email_assistant_agent = AgentExecutor(
        chat_client.as_agent(
            instructions=(
                "You are an email assistant that helps users draft professional responses to emails. "
                "Your input might be a JSON object that includes 'email_content'; base your reply on that content. "
                "Return JSON with a single field 'response' containing the drafted reply."
            ),
            default_options={"response_format": EmailResponse},
        ),
        id="email_assistant_agent",
    )

    # Build the workflow graph.
    # Start at the spam detector.
    # If not spam, hop to a transformer that creates a new AgentExecutorRequest,
    # then call the email assistant, then finalize.
    # If spam, go directly to the spam handler and finalize.
    workflow = (
        WorkflowBuilder(start_executor=spam_detection_agent)
        # Not spam path: transform response -> request for assistant -> assistant -> send email
        .add_edge(
            spam_detection_agent,
            to_email_assistant_request,
            condition=get_condition(False),
        )
        .add_edge(to_email_assistant_request, email_assistant_agent)
        .add_edge(email_assistant_agent, handle_email_response)
        # Spam path: send to spam handler
        .add_edge(
            spam_detection_agent,
            handle_spam_classifier_response,
            condition=get_condition(True),
        )
        .build()
    )

    # Read Email content from the sample resource file.
    # This keeps the sample deterministic since the model sees the same email every run.
    email_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
        "resources",
        "email.txt",
    )

    # Email file source:
    # https://github.com/microsoft/agent-framework/blob/main/python/samples/03-workflows/resources/email.txt
    with open(email_path) as email_file:  # noqa: ASYNC230
        email = email_file.read()

    # Execute the workflow. Since the start is an AgentExecutor, pass an AgentExecutorRequest.
    # The workflow completes when it becomes idle (no more work to do).
    request = AgentExecutorRequest(
        messages=[Message(role="user", contents=[email])], should_respond=True
    )
    events = await workflow.run(request)
    outputs = events.get_outputs()
    if outputs:
        for idx, output in enumerate(outputs):
            print(f"Workflow output [step {idx}]: {output}")


if __name__ == "__main__":
    asyncio.run(main())
