# autogen-pse

A **task-agnostic Planner–Specialist–Evaluator (PSE) agent framework** built on Microsoft AutoGen. Three agents with clear, separated responsibilities and an independent verification gate form a closed-loop delivery pipeline. You bring the task; the engine stays the same.

> **This is one of three PSE frameworks in this workspace family — same philosophy, different orchestration backend:**
> - **autogen-pse** (this repo) — PSE on AutoGen `RoundRobinGroupChat`, with optional RAG and a web dashboard.
> - **crewai-pse** — PSE on CrewAI `Sequential` (used for project-code → blog publishing to erishen.cn).
> - **langgraph-pse** — PSE on a LangGraph state machine (used for CRM data-quality QA).

## Quick Start

```bash
cp .env.example .env          # configure API key + any task-specific paths
uv sync                        # install dependencies
make demo                      # run the minimal quicksort task (verifies the pipeline)
```

## Tasks are pluggable

The engine knows nothing about investments, code, or CRM — it only runs the PSE loop for whatever task you register. Two tasks ship today:

| Task | Role | What it does |
|------|------|--------------|
| `demo` | Minimal example | Planner → Specialist writes quicksort code → Evaluator runs pytest + ruff. Proves the pipeline end-to-end. |
| `portfolio-review` | **Reference task** | The author's primary use case: reads `asset-lens` JSON/CSV, a rule-engine `prepare.py` builds a structured summary (zero LLM cost), then the PSE trio writes a weekly investment review with independent data verification. |

Add your own under `tasks/<your-task>/` (see *Adding a New Task*). Once registered in `tasks/_registry.json`, `python cli.py list` discovers it automatically.

## Project Structure

```
autogen-pse/
├── src/autogen_pse/           # Framework engine (unchanged across tasks)
│   ├── orchestrator.py        # PSE loop: cycle control, step_buffer, trace + token stats
│   ├── agents.py              # Planner / Specialist / Evaluator factories (task-aware)
│   ├── prompts.py             # Prompt loader — task-specific prompts, falls back to demo
│   ├── tools.py               # Tool sandbox (read_file/bash/pytest/ruff) + token tracking
│   └── config.py              # pydantic-settings .env loader
├── tasks/                     # ← Plug your tasks in here
│   ├── _registry.json         # Task catalog (name → label / description / env_required)
│   ├── demo/                  # Minimal example task
│   │   ├── meta.json / run.py / prompts/
│   │   └── output/            # Generated files (gitignored)
│   └── portfolio-review/      # Reference task (investment weekly review)
│       ├── meta.json / run.py / prepare.py / prepare_market.py / prompts/
│       ├── sanitize_rules.toml # post-hoc guardrails for the report
│       └── output/            # Generated files + archive/ (gitignored)
├── web/                       # Vite + React dashboard (Chart.js)
├── web_server.py              # FastAPI backend (SSE streaming)
├── cli.py                     # pse list / run / prepare / trace
├── tests/                     # unit tests
├── Makefile
├── .env.example
└── .gitignore
```

## Three Entry Points

### CLI — the task platform

```bash
python cli.py list              # list all registered tasks
python cli.py run <task>        # run a task (prepare → PSE)
python cli.py prepare <task>    # run only data prep (if the task has prepare.py)
python cli.py trace -n 5        # show the last 5 execution traces
```

### Makefile — shortcuts

```bash
make demo            # run the demo task
make summarize       # portfolio-review: build the structured summary (zero LLM cost)
make review          # portfolio-review: full PSE weekly review (DeepSeek)
make review-agnes    # portfolio-review: full PSE weekly review (Agnes 2.0 Flash)
make market          # portfolio-review: latest market indices
make serve           # start the web dashboard (http://localhost:8080)
make test            # run unit tests
make lint            # ruff check + format
```

> The `summarize` / `review` / `market` targets are thin wrappers around the `portfolio-review` task. For any new task you add, use `python cli.py run <your-task>` (or add your own Makefile target).

**`make summarize`** is the daily tool: it reads `asset-lens` JSON output, builds a structured summary, and a rule engine auto-detects 4 classes of portfolio issues (long-term loss, low capital efficiency, high volatility, structural problems). Zero LLM cost.

**`make review`** is the deep pass: the PSE trio writes the investment report on top of the summary with independent data verification. Run it when you want a second opinion.

**`make serve`** launches the web dashboard at `http://localhost:8080` — asset trend charts, one-click task execution, execution history.

## The PSE Three Roles

| Role | Responsibility | Constraint |
|------|------|------|
| **Planner** | Analyze the request, decompose the task, delegate execution, make the delivery decision | No code, no calculations |
| **Specialist** | Execute the assigned task; write deliverables to disk | Only what's assigned; report on completion |
| **Evaluator** | Independently verify the deliverable; emit a verdict | Doesn't trust the Planner; no suggestions — only PASS / PARTIAL / FAIL |

Tools are attached per agent (minimum-privilege): Planner gets `read_file` + `bash`; Specialist gets `read_file`; Evaluator gets `read_file` + `bash` + `pytest` + `ruff`.

## Cycle Control & step_buffer

Each task runs as a series of plan → execute → evaluate cycles:

```
Planner → Specialist → Evaluator
           ↑    PARTIAL     │
           └── fix & retry ─┘  (max MAX_PARTIAL_RETRIES = 3)
           ↑    FAIL         │
           └── fresh plan ──┘  (max MAX_FAIL_RETRIES = 2, then BLOCKED)

PASS → "交付完成" (delivered) · BLOCKED → stop
```

**step_buffer**: on PARTIAL only the verdict summary is passed forward to keep focus; on FAIL the context is cleared and planning restarts — preventing token blow-up. Every cycle's trace (verdict, per-agent token usage, duration, full transcript) is written to `outputs/traces/trace_*.json`.

Tunable via env vars: `PSE_MAX_PARTIAL_RETRIES`, `PSE_MAX_FAIL_RETRIES`, `PSE_TURNS_PER_CYCLE`, `PSE_TIMEOUT`, `PSE_MODEL_STREAM`.

## Environment Variables

Framework-level config (every task needs these):

| Variable | Description |
|------|------|
| `OPENAI_API_KEY` | LLM API key |
| `OPENAI_BASE_URL` | API base URL (defaults to DeepSeek) |
| `OPENAI_MODEL` | Model name |

Each task may additionally require its own variables, declared in its `meta.json` → `env_required`. For example, `portfolio-review` requires `ASSET_LENS_DIR`, `MONEY_CSV_DIR`, `MARKET_INDICES` and the `PSE_*` detection thresholds (10 items). See `.env.example` for the fully annotated list.

## Tech Stack

- **AutoGen** (`RoundRobinGroupChat`) — agent orchestration
- **DeepSeek** / OpenAI-compatible — model backend (Agnes also supported)
- **FastAPI** — web API with SSE streaming
- **Vite + React** — dashboard with Chart.js
- **uv** — Python project management

## Cost

Pricing follows the model backend. On DeepSeek Chat (~¥2 / 1M input tokens, ¥8 / 1M output tokens), a typical `portfolio-review` analysis runs about ¥0.08–¥0.65; the `demo` task is similar. `make summarize` uses zero LLM tokens (rule engine only).

## Adding a New Task

A task is just a directory under `tasks/`. Four pieces:

```
tasks/my-task/
├── meta.json              # { name, label, description, env_required: [...] }
├── run.py                 # entry: read data → create_pse_team(task="my-task") → run_task(team, TASK_TEXT, verbose=...)
├── prepare.py             # (optional) zero-LLM data prep; run via `cli.py prepare`
└── prompts/
    ├── planner.md         # Planner system prompt
    ├── specialist.md      # Specialist system prompt
    └── evaluator.md       # Evaluator system prompt
```

Steps:

1. **Create the directory** — `mkdir -p tasks/my-task/prompts`.
2. **Write the three role prompts.** Only override the roles you want to differ from `demo`; `load_prompt(name, task)` falls back to the `demo` prompts for any file you omit. *(Optional: add `<role>_rules.md` to inject private rules into that role's prompt — its content replaces the `{INVESTMENT_RULES}` / `{STOP_LOSS_RULES}` placeholders when present.)*
3. **Write `run.py`** — build the per-task prompt text (e.g. read prepared data), call `create_pse_team(task="my-task")` then `await run_task(team, task_text, verbose=True)`. The Evaluator's PASS verdict ends the loop; you can extract and persist the artifact from the trace afterwards (see `portfolio-review/run.py`).
4. **Register in `tasks/_registry.json`** — add `"my-task": { "label": "...", "description": "...", "env_required": [...] }`. `python cli.py list` will pick it up immediately.

No engine changes required.
