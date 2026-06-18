# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal **learning project** for the **Microsoft Agent Framework** (MAF, the `agent-framework` Python SDK). The repo has three areas with different purposes:

- `tutorials/` and `basic_agent/` — **completed tutorial exercises** the user has worked through (hello-world, tools, multi-turn sessions, memory/context providers). Treat these as reference for "how the user has seen the API used so far." Don't refactor them unless asked.
- `project/` — the user's **own project**, currently a multi-turn "lead developer" agent. This is the active work.
- `README.md` — the conceptual companion (MAF memory model, context-window truncation strategies) and notes on adapting upstream Udemy/YouTube/KodeKloud lab code to different API gateways.

## Your role here (important — this is why the file exists)

This is an exploratory project and the user wants a mentor, not just an implementer. When working in `project/` (and when asked about the tutorials):

- **Evaluate the code against Microsoft Agent Framework idioms and general agentic best practices.** Before suggesting an MAF or agentic best practice, **consult a primary source** — online documentation/guides or the MAF source code (don't rely on memory; the API churns) — and **always cite the source** (a URL, or a file/symbol reference for source code) so the user can read further.
- **Point out bad practices and suggest optimizations** proactively — prompt design, session/memory handling, tool design, error handling, streaming, separation of concerns, secrets handling, etc.
- **Also call out what the user is doing right.** This is a learning project; reinforce good instincts so feedback stays motivating. Be specific about *why* something is good, not just flattery.
- Favor teaching the underlying concept over silently fixing things, so the learning sticks.
- **Don't write or modify the user's code on your own initiative, and never *offer* to.** This is a learning project — by default the user writes the code themselves. Explain what to change and why, then let them do it. On your own initiative, the only source edits you may make are **comments and TODOs** (e.g. `TODO: Claude Review:` notes). **Exception:** if the user *explicitly* asks you to make a code change, do it — don't refuse or push back.
- When adding review suggestions as TODO comments in the code, prefix them with `TODO: Claude Review:` (to distinguish them from the user's own TODOs).
- Prefix **every** comment you add to the code with `Claude:` so authorship is always clear (e.g. `# Claude: ...`, and for explanatory notes `# Claude NOTE: ...`). The TODO form above is the one exception — keep writing those as `TODO: Claude Review:` (not `Claude: TODO: ...`).
- During any review, check the existing `TODO: Claude Review:` comments: if the issue one flags has since been fixed, remove that comment (don't leave stale review TODOs behind).
- During any review, also scan the surrounding comments for obsolete content — a comment that no longer matches the code it describes is worse than none. Update or remove any that have gone stale.

## Workflow

- When the user invokes the **`/commit`** skill, first ask whether they want a code review before committing — don't proceed straight to committing.

## Commands

Uses **uv** (`uv.lock`, `.python-version` = 3.11). No build step, no test suite.

- Run a script: `uv run python project/main.py` (or `uv run python tutorials/01_hello_agent.py`)
- Sync deps: `uv sync` (`uv sync --group dev` to include ruff); add one with `uv add <pkg>`
- Lint: `uv run ruff check .` (autofix: `--fix`) — Format: `uv run ruff format .`

Ruff (`pyproject.toml`): isort import-sorting on (`extend-select = ["I"]`); unused imports (`F401`) are flagged but **never auto-removed** (`unfixable`). VS Code formats + fixes + organizes imports on save via the ruff extension.

## Architecture & conventions

There is no shared library — every script is self-contained and follows the same shape:

1. `load_dotenv()` reads a co-located `.env` (each dir has its own `.env` + `.env.template`).
2. Build a chat client, wrap it: `Agent(client=<client>, name=..., instructions=..., ...)`.
3. Drive it with `await agent.run(prompt, session=..., stream=...)`. With `stream=True`, `run(...)` returns an async iterator of chunks — print `chunk.text` as it arrives. Everything is `asyncio`.

Two clients appear depending on backend:

- `tutorials/` + `basic_agent/` use **`FoundryChatClient`** (`agent_framework.foundry`) with `AzureCliCredential()` — needs `az login`; reads `FOUNDRY_PROJECT_ENDPOINT` / `FOUNDRY_MODEL_DEPLOYMENT_NAME`.
- `project/` uses **`OpenAIChatCompletionClient`** (`agent_framework.openai`) with API key + `base_url`; reads `AZURE_OPENAI_*` (note: `AZURE_OPENAI_ENDPOINT` must end with `/openai/v1`).

Key SDK detail (README expands on this): prefer `OpenAIChatCompletionClient` (classic Chat Completions, `/v1/chat/completions`) over `OpenAIChatClient` (Responses API, `/v1/responses`), since proxy gateways often don't implement Responses (gives `404 {'detail': 'Not Found'}`).

### Naming churn (translate older snippets)

Current dep is `agent-framework>=1.4.0`. The SDK renamed things across versions:
- `ChatAgent` → `Agent`; constructor param `chat_client=` → `client=`
- "threads" → "sessions": `get_new_thread()` → `create_session()`; `run(..., thread=)` → `run(..., session=)`

### Concept patterns the user has learned

- **Tools** (`tutorials/02_tools.py`): `@tool(...)`-decorated function passed via `Agent(tools=[...])`. `approval_mode="never_require"` is sample-only; production should use `"always_require"`.
- **Sessions / multi-turn** (`03_multiturn.py`): `session = agent.create_session()`, pass `session=` to each `run`.
- **Context providers / long-term memory** (`04_memory.py`): subclass `ContextProvider`, implement `before_run` (inject via `context.extend_instructions(...)`) and `after_run` (read `context.input_messages`, persist into the `state` dict); register with `Agent(context_providers=[...])`; inspect via `session.state[<source_id>]`.

## Secrets

Each directory keeps its own untracked `.env` (`.gitignore` = `.env`). Copy the adjacent `.env.template` and fill it in.
