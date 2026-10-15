import asyncio

from agent_framework import (
    Agent,
    # AgentExecutorRequest,
    AgentExecutorResponse,
    # Message,
    Workflow,
    WorkflowBuilder,
    WorkflowContext,
    executor,
)
from agent_framework.orchestrations import SequentialBuilder
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
# Note: data type of summary needs to be AgentExecutorResponse, NOT AgentResponse or str
# Else, TypeCompatibilityError is thrown.
async def forward_summary(
    summary: AgentExecutorResponse,
    ctx: WorkflowContext[str],  # WorkflowContext[AgentExecutorRequest],
):
    text = summary.agent_response.text
    # TODO: when I tried sending only text, got some warning. find out the deal
    # with this. The warning here was:
    # AgentExecutor 'Marketing': from_str handler invoked with an empty cache.
    # If you are chaining from an AgentExecutor, the upstream custom executor may be
    # emitting a plain str instead of using AgentExecutorResponse.with_text(...), which
    # causes the full conversation context to be lost.
    # However, when passing on info to a workflow executor (instead of an agent),
    # passing on a string is expected and in fact, that is what works in case the
    # workflow executor wraps a SequentialBuilder (AgentExecutorRequest does not).
    await ctx.send_message(
        text
        # Note: One interesting behaviour. In the simple Sequential case, we were
        # sending AgentExecutorRequest from send_message, which was working (str also
        # works). But in case of fan-in, AgentExecutorRequest throws this error:
        # -----------------------------------------------------------------------------
        # agent_framework._workflows._validation.TypeCompatibilityError:
        # [TYPE_COMPATIBILITY] Type incompatibility between executors
        # 'forward_summary' -> 'Marketing'. Source executor outputs types
        # ["<class 'agent_framework._workflows._agent_executor.AgentExecutorRequest'>"]
        # but target executor can only handle types
        # ["<class 'agent_framework._types.Message'>",
        # 'list[str | agent_framework._types.Message]',
        # "<class 'agent_framework._workflows._agent_executor.AgentExecutorResponse'>",
        # "<class 'str'>",
        # "<class 'agent_framework._workflows._agent_executor.AgentExecutorRequest'>"].
        # -----------------------------------------------------------------------------
        # AgentExecutorRequest(messages=[Message(role="user", contents=[text])])
    )


@executor(id="reverse_summary_and_forward")
async def reverse_summary_and_forward(
    summary: AgentExecutorResponse,
    ctx: WorkflowContext[str],  # WorkflowContext[AgentExecutorRequest],
):
    text = summary.agent_response.text
    await ctx.send_message(
        text
        # AgentExecutorRequest(messages=[Message(role="user", contents=[text])])
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
        #### Sequential #############
        # .add_edge(summarizer_agent, forward_summary)
        # .add_edge(forward_summary, marketing_agent)
        #### Fan-in - simple ########
        # .add_edge(summarizer_agent, forward_summary)
        # .add_edge(summarizer_agent, reverse_summary_and_forward)
        # .add_fan_in_edges(
        #     [forward_summary, reverse_summary_and_forward], marketing_agent
        # )
        #### Fan-out and fan-in #####
        .add_fan_out_edges(
            summarizer_agent, [forward_summary, reverse_summary_and_forward]
        )
        # Claude NOTE: fan-in [b, c] -> d, b sends str, c sends int: d gets ONE list,
        # so d's input type must be list[str | int]. Two catches:
        # - Order follows the add_fan_in_edges list, not who finished first.
        # - The list is flat: if b does ctx.send_message twice, d gets ["b1", "b2", 42].
        # Source: FanInEdgeRunner.send_message in _workflows/_edge_runner.py
        .add_fan_in_edges(
            [forward_summary, reverse_summary_and_forward], marketing_agent
        )
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


# Note: Earlier, this was in main(). It was moved out just because devui needs workflows
# to be at the module level to be able to detect them.
mini_workflow = build_mini_workflow()

mini_workflow_seq = SequentialBuilder(
    participants=[summarizer_agent, forward_summary, marketing_agent],
    intermediate_output_from=[summarizer_agent],
).build()


async def run_workflow(workflow: Workflow):
    start_message = "Files are present at outputs/sample"
    print(f"Sending the following message to workflow agents: {start_message}")

    result = await workflow.run(start_message)
    while True:
        requests = result.get_request_info_events()
        if not requests:
            break
        responses = await answer_approvals(requests)
        result = await workflow.run(responses=responses)

    # This was copied from the samples but anyway, the data type of outputs is
    # list[AgentResponse]
    # outputs = cast(list[AgentResponse], result.get_outputs())
    outputs = result.get_outputs()
    for output in outputs:
        print()
        print(f"##### {output.messages[0].author_name.upper()} ######")
        print(output.text)

    # This is just to print the final state, ideally "WorkflowRunState.IDLE"
    # Copied from samples
    print("Final state:", result.get_final_state())


async def main():
    # Claude: run once, then keep resuming until nothing is waiting on us. run() returns
    # when the workflow either finishes (goes idle) OR pauses for approval;
    # get_request_info_events() tells the two apart. We answer any pending approvals and
    # feed them back via responses= to continue the SAME run from where it paused.

    print("---------------- DEMONSTRATING SIMPLE WORKFLOW ------------------------")

    await run_workflow(workflow=mini_workflow)

    # print("---------------- DEMONSTRATING SEQUENTIAL WORKFLOW --------------------")

    # await run_workflow(workflow=mini_workflow_seq)


if __name__ == "__main__":
    asyncio.run(main())
