# agents-framework-tutorial

### References:

- https://github.com/microsoft/agent-framework
- https://learn.microsoft.com/en-us/agent-framework/get-started/your-first-agent?pivots=programming-language-python
- https://www.youtube.com/watch?v=EAeUiipzCTE
- https://www.udemy.com/course/microsoft-agent-framework-fundamentals (same as the youtube course)

# Concepts

## Memory

Two types:
- Session level memory: memory in a certain **thread** or **session**
    - Earlier, they were called "threads" in code; now they are called "sessions".
- Long term memory i.e. **context**: memory across sessions or threads
    - In MAF, they are managed using context providers

Context providers have two sections:
- Before invocation: Inject context derived from persistent memory (e.g. - user's preferred language: Spanish)
- After invocation: Inspect the user messages + agent responses and update your memory (e.g. - the user just told you a new preference)

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
