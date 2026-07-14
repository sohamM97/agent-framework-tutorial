import asyncio
from typing import cast

from agent_framework import (
    Agent,
    AgentExecutorRequest,
    AgentExecutorResponse,
    AgentResponse,
    Message,
    WorkflowBuilder,
    WorkflowContext,
    executor,
)
from client import client
from tools import get_files_under_dir, read_from_file

summarizer_agent = Agent(
    client=client,
    name="Summarizer",
    instructions="You are an agent who can take a look at the codebase, and describe "
    "what it does, its features etc.",
    tools=[get_files_under_dir, read_from_file],
)


marketing_agent = Agent(
    client=client,
    name="Marketing",
    instructions="You are an agent who can take information about any product, its "
    "features etc. and generate a catchy marketing slogan.",
)


@executor(id="forward_summary")
# TODO: why is summary an AgentExecutorResponse? Why not, say, AgentResponse or
# even a string? The AgentResponse import was copied from code samples, while
# AgentExecutorResponse was something claude suggested. Understand both.
async def forward_summary(
    summary: AgentExecutorResponse, ctx: WorkflowContext[AgentExecutorRequest]
):
    text = summary.agent_response.text
    # TODO: when I tried sending only text, got some warning. find out the deal
    # with this. The warning was:
    # AgentExecutor 'Marketing': from_str handler invoked with an empty cache.
    # If you are chaining from an AgentExecutor, the upstream custom executor may be
    # emitting a plain str instead of using AgentExecutorResponse.with_text(...), which
    # causes the full conversation context to be lost.
    await ctx.send_message(
        AgentExecutorRequest(messages=[Message(role="user", contents=[text])])
    )


# TODO: The following is fixed now, but need to understand better:
# Claude Review: this 400s when run, but ONLY because Summarizer's tools need
# approval. (WorkflowBuilder wraps each bare Agent in an AgentExecutor node —
# _workflow_builder.py:189-221 — and that wrapper owns the two message lists below.)
# Each AgentExecutor holds TWO lists of messages: (a) the agent's own session (its
# running chat history), and (b) a "cache" it forwards to the next node. On an approval
# resume MAF OVERWRITES the cache with just the approval answer (_agent_executor.py:315
# — a plain `=`), so the assistant `tool_calls` message survives only in the session
# (a), not in the forwarded cache (b). Summarizer's own run is fine; but Marketing
# replays that forwarded cache
# (context_mode "full", :225) and OpenAI rejects a `tool` message with no preceding
# `tool_calls`.
# FIX: don't chain the raw transcript into Marketing — put a tiny executor between them
# that forwards only `summary.agent_response.text` as a fresh user message.
# SAMPLES CONFIRM: agents_with_approval_requests.py never chains an approval-agent into
# another agent; it ends with an executor that forwards `.agent_response.text`, not the
# full conversation. That's the pattern to copy.
def build_mini_workflow():
    return (
        WorkflowBuilder(start_executor=summarizer_agent, output_from="all")
        .add_edge(summarizer_agent, forward_summary)
        .add_edge(forward_summary, marketing_agent)
        .build()
    )


# Claude: every tool here is approval_mode="always_require", so when Summarizer tries
# to call read_from_file / get_files_under_dir the run PAUSES and hands back a pending
# request instead of running the tool. Each pending request is a tool-approval ask: we
# show the function + its arguments, read a y/n, and turn the answer into the response
# object MAF wants (data.to_function_approval_response). The dict we return is keyed by
# request_id so MAF can match each answer back to the request that raised it.
async def answer_approvals(requests) -> dict:
    responses = {}
    for event in requests:
        data = event.data
        print(f"\n{event.source_executor_id} wants to call a tool:")
        print(f"  Function : {data.function_call.name}")
        print(f"  Arguments: {data.function_call.arguments}")
        # Claude: input() blocks, so run it off the event loop with to_thread — the same
        # trick workflow_graph.py's take_input_from_user uses.
        answer = await asyncio.to_thread(input, "Approve? (y/n): ")
        approved = answer.strip().lower() == "y"
        responses[event.request_id] = data.to_function_approval_response(
            approved=approved
        )
    return responses


async def main():
    workflow = build_mini_workflow()

    # Claude: run once, then keep resuming until nothing is waiting on us. run() returns
    # when the workflow either finishes (goes idle) OR pauses for approval;
    # get_request_info_events() tells the two apart. We answer any pending approvals and
    # feed them back via responses= to continue the SAME run from where it paused.
    result = await workflow.run("Files are present at outputs/sample")
    while True:
        requests = result.get_request_info_events()
        if not requests:
            break
        responses = await answer_approvals(requests)
        result = await workflow.run(responses=responses)

    outputs = cast(list[AgentResponse], result.get_outputs())
    for output in outputs:
        print(f"{output.messages[0].author_name}: {output.text}\n")

    # This is just to print the final state, ideally "WorkflowRunState.IDLE"
    # Copied from samples
    print("Final state:", result.get_final_state())


if __name__ == "__main__":
    asyncio.run(main())
