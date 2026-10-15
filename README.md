# agents-framework-tutorial

### References:

- https://github.com/microsoft/agent-framework
- https://learn.microsoft.com/en-us/agent-framework/get-started/your-first-agent?pivots=programming-language-python
- https://www.youtube.com/watch?v=EAeUiipzCTE
- https://www.udemy.com/course/microsoft-agent-framework-fundamentals (same as the youtube course)

# Concepts

## Memory

> Checked against the `agent-framework` 1.11.0 source. This section used to say that
> memory "across sessions" is what context providers give you. That is not true, and it is
> an easy thing to believe — see below.

The thing to get straight first: **a session does not hold the conversation.**
`AgentSession` is described in the source as a "lightweight state container". All it has is
`session_id`, `service_session_id`, and a `state` dict.

So where do the messages live? **The chat history is itself a context provider.**
`InMemoryHistoryProvider` is "the default provider auto-added by the agent for local
sessions when no providers are configured", and it keeps the messages in
`session.state["messages"]`.

That gives the real picture:

- A **session** is one ongoing conversation, identified by `session_id`. Create it with
  `agent.create_session()` and pass it as `session=` on each run.
    - These used to be called **threads**. `get_new_thread()` became `create_session()`,
      and `run(..., thread=)` became `run(..., session=)`.
- A **context provider** is a pair of hooks around each run:
    - `before_run`: add to what the model sees this turn (instructions, messages, tools).
    - `after_run`: look at the messages and the response, and record what is worth keeping.
- The `state` dict a provider is handed is **provider-scoped storage that lives inside
  `session.state`** — the docstring says "Full cross-provider state remains available at
  `session.state`".

**So a context provider's memory is session-scoped, exactly like the chat history.** Both
sit in the same dict, and both disappear when the session does. A provider is the *place*
where long-term memory becomes possible; it is not the storage that makes it happen.
Writing a fact into `state` just puts it back in the session.

To make something outlive a session, one of these has to happen:

- **Persist the session yourself** — `session.to_dict()` / `AgentSession.from_dict()` into
  a database, cache, or file.
- **Subclass `HistoryProvider`** and implement `get_messages` / `save_messages` against
  your own storage. `FileHistoryProvider` (one JSON Lines file per session) is the shipped
  example.
- **Read and write your own store inside `before_run` / `after_run`.** This is the one for
  durable facts like a name or a preferred language: load it in `before_run` and inject it
  with `context.extend_instructions(...)`, then save any new fact in `after_run`. The store
  has to be something outside the session — a database, or the host application's own
  per-user state.

`tutorials/agents/04_memory.py` shows the hook shape, but note it reads its result back out
of `session.state` — so what it actually demonstrates is per-session memory, not memory
that survives into a new session.

## Context Window Management/Truncation

All models have a maximum context window. As conversations grow:
- We may hit token limits and get errors
- API costs increase
- Response times slow down
- The model may lose focus on recent messages

Truncation strategies:

1. **Sliding window** - Keep only the last N messages, discarding older ones
    - Pros: simpler to implement, predictable behaviour
    - Cons: loses older context, doesn't account for message length
    - Used more for prototypes/demos

2. **Token-based truncation** - Remove old messages until total tokens are under a budget
    - Pros: More precise, respects actual token limits
    - Cons: Requires token counting, slightly more complex
    - Used more for production systems

Both of the above lose information, so a smarter approach is:

3. **Summarization**
    - Log conversation exchanges - track user and assistant messages
    - Summarize old exchanges - using a dedicated summarizer agent
    - Inject summary **as a message** - send it as the first message to the new thread
    - This is also a multi-agent pattern

## Workflows

Sources:
- https://learn.microsoft.com/en-us/agent-framework/workflows
- https://github.com/microsoft/agent-framework/tree/main/python/samples/03-workflows

Some of the advantages of using workflows are mentioned in: https://learn.microsoft.com/en-us/agent-framework/workflows/#key-features

# KodeKloud lab adjustments

> **Scope — proxy is lab-only.** Everything in this section is specific to the KodeKloud tutorial labs, which run against a **proxy gateway** (`OPENAI_API_BASE`). My own `project/` does **not** use that proxy — it runs against a **real Azure OpenAI resource** (`OpenAIChatCompletionClient` with `azure_endpoint` + the `AZURE_OPENAI_*` vars). So the proxy-only quirks below (e.g. the `/responses` → `404` issue) don't apply to `project/`.

For the youtube/udemy tutorial KodeKloud labs:

## Setup (applies to the entire lab):

**Note: this was needed for section 1 but not for 2.** Also, the given URL doesn't seem to exist anymore. Maybe something changed in the lab - need to try section 1 again to verify.

- Go to https://kodekloud.com/ai-playgrounds/kodekey, launch now, copy base url and api key
- Export `OPENAI_API_KEY` and `OPENAI_API_BASE` in the terminal

## Section 1

### Code changes (apply to the entire lab):

- Use `model="gpt-5.5"` (instead of `model_id="openai/gpt-4.1-mini"`)
- Use `agent = client.as_agent(...)` instead of `agent = client.create_agent(...)`

### Task 2 specific:

- Replace `stream = agent.run_stream(query)` with `stream = agent.run(query, stream=True)`

## Section 2

### Code changes (apply to the entire lab):

- Use `model="openai/gpt-4.1-mini"` (instead of `model_id="openai/gpt-4.1-mini"`)
- Use `agent.create_session()` instead of `agent.get_new_thread()`
- Use `await agent.run(..., session=...)` instead of `await agent.run(..., thread=...)`
- Use `OpenAIChatCompletionClient` instead of `OpenAIChatClient`.
    - `OpenAIChatClient` calls the OpenAI **Responses API** (`/v1/responses`), while `OpenAIChatCompletionClient` calls the classic **Chat Completions API** (`/v1/chat/completions`).
    - The KodeKloud lab gateway (a proxy `OPENAI_API_BASE`) only implements `/chat/completions`, so `OpenAIChatClient` fails with `404 - {'detail': 'Not Found'}` (the `detail` body is a giveaway that it's a proxy, not real OpenAI).
    - Everything downstream (`client.as_agent(...)`, `create_session()`, `agent.run(...)`) is identical between the two clients — only the endpoint differs.

## Section 3 and 4

### Code changes (apply to the entire lab):

- Use `model="openai/gpt-4.1-mini"` (instead of `model_id="openai/gpt-4.1-mini"`)
- Import `Agent` instead of `ChatAgent` (renamed in `python-1.3.0`)
- Use `Agent(client=...)` instead of `Agent(chat_client=...)` (the constructor's first parameter was renamed from `chat_client` to `client`)
