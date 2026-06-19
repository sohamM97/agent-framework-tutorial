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
- **During any code review, look beyond correctness for refactoring and clarity wins too:** duplicated logic worth extracting, functions doing too much / high cyclomatic complexity, dead or unreachable code, and especially **unclear or misleading variable and function names** — suggest a better name and say *why* it reads more clearly. As always, propose the change and let the user apply it (comments/TODOs are the only edits you make unprompted).
- **Also flag underused library idioms** — places where an imported library's own API would do the job more cleanly than hand-rolled code (e.g. `pathlib`'s `Path.read_text()` / `write_text()` instead of `open()` + `with`, a stdlib/3rd-party helper instead of a manual loop). The user is here to learn the libraries well, so name the idiomatic call and what it replaces.
- **Also call out what the user is doing right.** This is a learning project; reinforce good instincts so feedback stays motivating. Be specific about *why* something is good, not just flattery.
- Favor teaching the underlying concept over silently fixing things, so the learning sticks.
- **Don't write or modify the user's code on your own initiative, and never *offer* to.** This is a learning project — by default the user writes the code themselves. Explain what to change and why, then let them do it. On your own initiative, the only source edits you may make are **comments and TODOs** (e.g. `TODO: Claude Review:` notes). **Exception:** if the user *explicitly* asks you to make a code change, do it — don't refuse or push back.
- When adding review suggestions as TODO comments in the code, prefix them with `TODO: Claude Review:` (to distinguish them from the user's own TODOs).
- Prefix **every** comment you add to the code with `Claude:` so authorship is always clear (e.g. `# Claude: ...`, and for explanatory notes `# Claude NOTE: ...`). The TODO form above is the one exception — keep writing those as `TODO: Claude Review:` (not `Claude: TODO: ...`).
- During any review, check the existing `TODO: Claude Review:` comments: if the issue one flags has since been fixed, remove that comment (don't leave stale review TODOs behind).
- During any review, also scan the surrounding comments for obsolete content — a comment that no longer matches the code it describes is worse than none. Update or remove any that have gone stale.

## Workflow

- **Whenever the user asks you to commit — via the `/commit` skill *or* any plain-language request like "commit this" / "commit and push" — first ask whether they want a code review before committing.** Don't proceed straight to committing. This applies to every commit request, not just the skill invocation.

## Commands

Uses **uv** (`uv.lock`, `.python-version` = 3.14). No build step, no test suite.

- Run the project: from inside `project/`, `uv run main.py` (it's a package of modules — `main`, `agents`, `client`, `tools` — wired with absolute imports, so it must be run from that directory).
- Run a tutorial: from the repo root, `uv run python tutorials/01_hello_agent.py` (these are still standalone single-file scripts).
- Sync deps: `uv sync` (`uv sync --group dev` to include ruff); add one with `uv add <pkg>`
- Lint: `uv run ruff check .` (autofix: `--fix`) — Format: `uv run ruff format .`

Ruff (`pyproject.toml`): isort import-sorting on (`extend-select = ["I"]`); unused imports (`F401`) are flagged but **never auto-removed** (`unfixable`). VS Code formats + fixes + organizes imports on save via the ruff extension.

## Architecture & conventions

`tutorials/` and `basic_agent/` are **self-contained single-file scripts**. `project/` has outgrown that — it's now a small **multi-module package** run from inside its own directory (so `import agents` etc. resolve as top-level modules; relative imports were dropped for this reason):

- `client.py` — builds the one shared `OpenAIChatCompletionClient` from `AZURE_OPENAI_*`.
- `tools.py` — the `write_to_file` tool (`approval_mode="always_require"`).
- `agents.py` — the two agents: `sm_agent` ("AgentSoham", the lead-developer persona) and `sf_agent` ("SatisfactionAgent", an LLM-as-judge).
- `main.py` — the orchestration loop plus `run_agent()`, a helper that wraps `agent.run`, streams output, and drives the **human-in-the-loop approval cycle** (on a `user_input_request` it prompts y/n, then re-runs with *only* the approval responses — never re-sending the original message, or the tool-call would dangle in the session and 400 on replay).

The conversation flow in `main()`: greet → each turn ask `sf_agent` (structured `response_format=UserSatisfaction`) whether enough requirements are gathered; if not, `sm_agent` replies; once satisfied + user confirms, a final run writes the proposal via the tool. **Both agents currently share one session** — convenient but it pollutes `sm_agent`'s history with the judge's verdicts (documented inline as a `Claude NOTE:`); the decoupling fix is to run the judge stateless with its own transcript.

Whatever the file, each agent run follows the same shape:

1. `load_dotenv()` reads a co-located `.env` (each dir has its own `.env` + `.env.template`). Bare `load_dotenv()` resolves relative to the *running script's* directory and **breaks under the VS Code debugger** (it then searches the CWD) — anchor it with `load_dotenv(Path(__file__).parent / ".env")` if that bites.
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
