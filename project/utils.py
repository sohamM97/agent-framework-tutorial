import asyncio
import random
import sys

from agent_framework import Agent, AgentResponse, AgentSession, Message
from models import UserPrompt
from pydantic import BaseModel


class RandomException(Exception):
    pass


# TODO: Claude Review: this injection sabotages dev-ui runs. It's called at the top of
# stream_soham (so it fires on the opening greeting) and in ask_agent_to_review, ~1/3
# of the time. Under `uv run` that's fine — main()'s driver loop catches RandomException
# and resumes from the last checkpoint. But dev-ui runs the module-level `workflow`
# directly and NEVER enters main(), so there's no catch/resume: ~1 in 3 dev-ui sessions
# just crash (often at the very first turn). Now that dev-ui is a real entry point,
# consider gating this behind an env var / flag that only the CLI driver sets, so
# checkpoint testing stays on for `uv run` but dev-ui sessions don't randomly explode.
def throw_random_exception():
    # SOHAM: throw an exception 1/3rd of the time, to test checkpointing
    rand_int = random.choice([1, 2, 3])
    if rand_int == 3:
        raise RandomException


async def stream_soham(
    agent: Agent, message: str | Message, session: AgentSession, ctx
) -> None:
    """Run Soham with streaming and surface each chunk as workflow output.

    Claude: yielding the updates (instead of running non-streamed and yielding one
    final string) is what makes his words type out live via stream_segment, under
    his "Soham" label. Iterating the stream to the end also finalizes the run and
    writes it into the shared session — ResponseStream calls get_final_response()
    on exhaustion (_types.py:3117-3120) — so his conversation memory stays intact.

    Claude: contrast with the earlier NON-streaming version — there Soham's text
    rode inside the UserPrompt and reached the driver as part of the request_info
    event (the driver printed `prompt.text` before reading input); it was never a
    yield_output. Streaming flips that: the text goes out via yield_output here, and
    request_info now carries only the routing `kind`.
    """
    # Initially, I had kept this in main. However, there the exception was technically
    # being thrown OUTSIDE the workflow run. Checkpointing is best tested when an
    # exception occurs INSIDE the workflow run (this function is one of the functions
    # which runs inside the workflow).
    throw_random_exception()
    async for update in agent.run(message, session=session, stream=True):
        # SOHAM: ctx.yield_output yields the outputs of the workflow which the user
        # sees. If agents/agentexecutors are present in the workflow, all of their
        # outputs are yielded by default, unless output_from is set.
        await ctx.yield_output(update)


# Claude: map executor ids -> the agent persona behind them, so outputs are
# attributed correctly. Two things this buys us: it collapses the two Soham-backed
# executors (gather_requirements + present_proposal) under the single name "Soham",
# and it prettifies xl/amma into XL/Amma. Without this map the driver falls back to
# the raw executor id (see stream_segment's .get(id, id)), so you'd see
# "[AGENT amma]" / "[AGENT gather_requirements]" instead of the persona names.
# (An even earlier, pre-streaming driver hardcoded "Soham" and so mislabeled Amma —
# the bug this map first fixed; today's fallback is the raw id, not "Soham".)
EXECUTOR_LABELS = {
    "gather_requirements": "Soham",
    "present_proposal": "Soham",
    "xl": "XL",
    "amma": "Amma",
}

# Claude: ANSI escape codes — special character sequences the terminal reads as
# "switch style" instead of printing. \033[2m turns on dim (a fainter shade of the
# normal text color), \033[0m switches back to normal. Codes stack with semicolons,
# so \033[2;36m is dim + cyan. Both diagnostic styles stay dim so the agent
# conversation dominates at full brightness; only the hue tells them apart. If your
# terminal doesn't render dim, gray ("\033[90m") is a good substitute.
# Claude: only colorize when stdout is a real terminal — piping the run to a file
# (e.g. `> run.log`) would otherwise litter it with escape codes.
_IS_TTY = sys.stdout.isatty()
EVENT_STYLE = "\033[2m" if _IS_TTY else ""  # dim, no hue
CHECKPOINT_STYLE = "\033[2;36m" if _IS_TTY else ""  # dim cyan
RESET = "\033[0m" if _IS_TTY else ""


def _format_checkpoint(checkpoint) -> str:
    """One-line-ish summary of a WorkflowCheckpoint for live inspection.

    Claude: the full checkpoint holds the whole conversation (checkpoint.messages) and
    all committed shared state (checkpoint.state) — too big to dump every step. We show
    the identity/chain fields plus which executors have in-flight messages and which
    state keys are set. Swap in `checkpoint.to_dict()` if you want to see everything.
    """
    executors_with_msgs = list(checkpoint.messages.keys())
    state_keys = list(checkpoint.state.keys())
    return (
        f"  checkpoint_id : {checkpoint.checkpoint_id}\n"
        f"  previous      : {checkpoint.previous_checkpoint_id}\n"
        f"  iteration     : {checkpoint.iteration_count}\n"
        f"  msgs pending  : {executors_with_msgs}\n"
        f"  state keys    : {state_keys}\n"
        f"  pending reqs  : {list(checkpoint.pending_request_info_events.keys())}"
    )


def _format_event(event) -> str:
    """Compact one-liner describing a workflow event, for learning/inspection.

    Claude: WorkflowEvent packs every possible field onto one class (_events.py:194)
    and only sets the ones that apply to this event's type. So we pull each field and
    include it only when present — that's how one formatter covers all the event kinds
    (started, status, superstep_started/completed, executor_invoked/completed,
    request_info, warning/error). The data payload is kept to a short preview because
    executor_completed carries the executor's sent messages + outputs
    (_executor.py:288-292), which can be large.
    """
    parts = [f"type={event.type}"]
    if event.executor_id is not None:
        parts.append(f"executor={event.executor_id}")
    if event.iteration is not None:
        parts.append(f"superstep={event.iteration}")
    if event.state is not None:
        # Claude: .state is a WorkflowRunState enum (STARTED, IN_PROGRESS, IDLE,
        # IDLE_WITH_PENDING_REQUESTS, ...); .value is its readable string.
        parts.append(f"state={event.state.value}")
    if event.type == "request_info":
        # These are properties that raise off a non-request_info event, so read them
        # only here (guarded by type). They tell us who is waiting on the human.
        parts.append(f"request_id={event.request_id} from={event.source_executor_id}")
    if event.data is not None:
        preview = str(event.data).replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:80] + "…"
        parts.append(f"data={preview}")
    return "[EVENT] " + "  ".join(parts)


async def stream_segment(stream, workflow_name: str, checkpoint_storage=None):
    """Render one streaming run's output live, then return its WorkflowRunResult.

    Claude: with stream=True, each AgentExecutor (XL, Amma) — and Soham too, whose
    turns we stream via stream_soham — sends its reply as a run of 'output' events
    whose data is an AgentResponseUpdate, one small text chunk per event. So we
    print a labeled header the first time a source speaks, then print its chunks
    inline as they arrive (this is the live typing effect).

    Two things to know:
    - A plain-string yield (the fixed y/n confirm prompt) arrives as a SINGLE output
      event rather than a run of chunks, so it prints in one go. We handle both by
      reading .text when present and falling back to str(event.data).
    - We must keep an empty chunk empty (a chunk's .text is "" on some updates).
      Using `chunk or str(...)` would wrongly dump the raw update object for those,
      so we check `is None` instead.
    """
    last_source = None
    async for event in stream:
        # TODO: what is a superstep? is it similar to a "turn"?
        # Claude: log every event except the per-token output/intermediate stream
        # (rendered as live text below; a line per token would shred the typing).
        # Close any half-printed live line first so the diagnostic starts clean.
        if event.type not in ("output", "intermediate"):
            if last_source is not None:
                print()
                last_source = None
            print()
            print(f"{EVENT_STYLE}{_format_event(event)}{RESET}")

        # Claude: a checkpoint is saved just before each superstep_completed event
        # (_runner.py:143-146). The id isn't on the event, so we read the newest one
        # back out of storage here.
        if event.type == "superstep_completed" and checkpoint_storage is not None:
            latest = await checkpoint_storage.get_latest(workflow_name=workflow_name)
            print()
            # Claude: the style stays on across newlines, so one wrap covers the
            # whole multi-line checkpoint block.
            print(f"{CHECKPOINT_STYLE}[CHECKPOINT @ superstep {event.iteration}]")
            print((_format_checkpoint(latest) if latest else "  (none)") + RESET)
            continue
        if event.type != "output":
            continue
        # Claude: a sub-workflow (mini_workflow) runs BATCH inside WorkflowExecutor, so
        # its outputs arrive as whole AgentResponse objects (not streamed chunks), all
        # tagged with the executor id "mini_workflow". Print each as its own labeled
        # block keyed by its author (messages[0].author_name), so Summarizer and
        # Marketing show separately instead of glued together under one header.
        # Claude NOTE: this BATCH behavior isn't configurable. WorkflowExecutor always
        # runs its sub-workflow non-streaming — self.workflow.run(...) with NO
        # stream=True (_workflow_executor.py:408), then collects finished outputs via
        # get_outputs() (:555). No flag streams a sub-workflow's tokens; verified
        # identical across agent-framework 1.9/1.10/1.11 and main, and NOT documented
        # anywhere (source is the only evidence). The one streaming path is
        # workflow.as_agent(), but it forwards only the FINAL agent's reply
        # (_agent.py:417-464).
        if isinstance(event.data, AgentResponse):
            msgs = event.data.messages
            author = msgs[0].author_name if msgs else event.executor_id
            print(f"\n[AGENT {author}]: {event.data.text}")
            last_source = None  # make the next streamed event reprint its header
            continue
        # AgentResponseUpdate has .text (the chunk); a plain-string yield does not.
        chunk = getattr(event.data, "text", None)
        if chunk is None:
            chunk = str(event.data)
        if event.executor_id != last_source:
            label = EXECUTOR_LABELS.get(event.executor_id, event.executor_id)
            print(f"\n[AGENT {label}]: ", end="", flush=True)
            last_source = event.executor_id
        print(chunk, end="", flush=True)
    if last_source is not None:
        print()  # close off the last streamed line
    # The run is finished (idle or paused for input); hand back the full result so
    # the caller can read any pending request_info events.
    return await stream.get_final_response()


async def take_input_from_user(response_type: type = str) -> str | BaseModel:
    """Read the user's answer, shaped to the expected `response_type`.

    Claude: a plain-str request (confirm y/n, XL's approvals) stays one input() line.
    For a Pydantic model (ProjectRequirements) we ask one line per field and build it,
    so it's generic -- add/rename a field and the prompts follow. is_required() is True
    only when a field has no default, so an optional field left blank uses its default.
    """
    if isinstance(response_type, type) and issubclass(response_type, BaseModel):
        values = {}
        for field_name, field in response_type.model_fields.items():
            required = field.is_required()
            suffix = ": " if required else " (optional, Enter to skip): "
            answer = await asyncio.to_thread(input, f"\n[USER] {field_name}{suffix}")
            # Claude: a required field can't be left blank -- keep asking until the
            # user types something. strip() so spaces alone don't count as filled.
            while required and not answer.strip():
                answer = await asyncio.to_thread(
                    input, f"[USER] {field_name} is required{suffix}"
                )
            if answer or required:
                values[field_name] = answer
        return response_type(**values)
    return await asyncio.to_thread(input, "\n[USER]: ")


async def answer_pending_requests(requests) -> dict:
    """Turn the workflow's pending request_info events into a responses dict.

    NOTE — two kinds of request flow through here:
      1. UserPrompt  — our own conversational asks from GatherRequirements.
      2. function-approval requests — auto-surfaced by AgentExecutor when XL calls
         write_to_file (approval_mode="always_require"). The AgentExecutor turns the
         agent's user_input_requests into workflow request_info events, then resumes
         the agent once we answer.
         Claude NOTE — because we now run with stream=True, this conversion happens
         in the STREAMING branch: the approval prompt only shows up AFTER XL's tokens
         finish streaming, not mid-stream (_agent_executor.py:529-543; the
         non-streaming version that did the same is :447-449).
         Either way the `always_require` approval survives the port for free — we
         reuse the same `to_function_approval_response` call main.py used.
    """
    responses = {}
    for event in requests:
        data = event.data
        if isinstance(data, UserPrompt):
            # Claude: nothing to print here anymore — Soham's question already
            # streamed out as workflow output. We just collect the user's answer.
            # Claude: event.response_type is the type passed to ctx.request_info
            # (ProjectRequirements for a requirements turn, str for a confirm) — it
            # rides on the request-info event, so we read it straight off `event`.
            responses[event.request_id] = await take_input_from_user(
                event.response_type
            )
        elif hasattr(data, "to_function_approval_response"):
            print(f"\n{event.source_executor_id} needs approval:")
            print(f" Function: {data.function_call.name}")
            print(f" Arguments: {data.function_call.arguments}")
            print("Enter 'y' or 'n'.")
            approved = (await take_input_from_user()).strip().lower() == "y"
            responses[event.request_id] = data.to_function_approval_response(
                approved=approved
            )
        else:
            raise RuntimeError(f"Unexpected request payload: {type(data)!r}")
    return responses
