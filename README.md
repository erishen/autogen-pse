# autogen-pse

A **Planner-Specialist-Evaluator three-role agent framework** built on Microsoft AutoGen. Three agents collaborate — each with clear responsibilities and independent verification — forming a closed-loop delivery pipeline.

## Quick Start

```bash
cp .env.example .env          # Configure API key and external paths
uv sync                        # Install dependencies
make demo                      # Run the quicksort demo
```

## Project Structure

```
autogen-pse/
├── src/autogen_pse/           # Core engine
│   ├── orchestrator.py        # Cycle control, step_buffer, trace recording
│   ├── agents.py              # Planner / Specialist / Evaluator factories
│   ├── prompts.py             # Prompt loader (supports task-specific prompts)
│   └── tools.py               # Token tracking & reporting
├── tasks/                     # Task registry
│   ├── _registry.json         # All registered tasks
│   ├── demo/                  # Code delivery demo
│   │   ├── meta.json / run.py / prompts/
│   │   └── output/            # Generated files (gitignored)
│   └── portfolio-review/      # Investment weekly review
│       ├── meta.json / run.py / prompts/
│       ├── prepare.py          # Data prep (zero LLM cost)
│       ├── prepare_market.py   # Market index extraction
│       └── output/             # Generated files (gitignored)
├── web/                       # Vite + React frontend
│   ├── src/App.jsx / App.css
│   ├── src/TrendChart.jsx     # Asset trend chart (Chart.js)
│   └── src/api.js             # API client
├── web_server.py              # FastAPI backend
├── cli.py                     # CLI: pse list / run / trace
├── tests/                     # 31 unit tests
├── Makefile
├── .env.example               # Configuration template
└── .gitignore
```

## Three Entry Points

### CLI — Task Platform

```bash
python cli.py list              # List all tasks
python cli.py run <task>        # Run a task (prepare → PSE)
python cli.py trace -n 5        # View last 5 execution traces
```

### Makefile — Shortcuts

```bash
make demo        # Code delivery demo
make summarize   # Generate investment summary (zero LLM cost)
make review      # Weekly review with PSE analysis
make market      # Latest market indices
make serve       # Start web dashboard (http://localhost:8080)
make test        # 31 unit tests
make lint        # Code checks
```

**`make summarize`** is the daily tool: reads asset-lens JSON output, generates a structured summary, and uses a rule engine to auto-detect 4 categories of portfolio issues (long-term losses, low capital efficiency, high volatility, structural problems). Zero LLM cost.

**`make review`** is deep analysis: the PSE trio writes an investment report based on the summary, with independent data verification. Run only when you need a second opinion.

**`make serve`** launches the Web Dashboard at `http://localhost:8080` — asset trend charts, one-click task execution, execution history.

## PSE Three-Role Division

| Role | Responsibility | Constraint |
|------|------|------|
| **Planner** | Analyze requirements, decompose tasks, delegate execution, make delivery decisions | No code, no calculations |
| **Specialist** | Execute specific tasks, write deliverables to disk | Only what's assigned, report on completion |
| **Evaluator** | Independently verify deliverables, output verdict | Don't trust Planner, no suggestions, only PASS/PARTIAL/FAIL |

## Cycle Control & step_buffer

Each task consists of multiple plan→execute→evaluate cycles:

```
Planner → Specialist → Evaluator
           ↑    PARTIAL     │
           └── fix & retry ─┘  (max 3 times)
           ↑    FAIL         │
           └── fresh plan ──┘  (max 2 times, auto BLOCKED)

PASS → delivered
```

**step_buffer**: on PARTIAL, only the verdict summary is passed to keep focus; on FAIL, the context is cleared and planning restarts — preventing token explosion.

Detailed traces per cycle (verdict, per-agent token usage, duration) are written to `outputs/traces/trace_*.json`.

## Environment Variables

All configuration is centralized in `.env`:

| Variable | Description |
|------|------|
| `OPENAI_API_KEY` | LLM API key |
| `OPENAI_BASE_URL` | API base URL |
| `ASSET_LENS_DIR` | Path to asset-lens project |
| `MONEY_CSV_DIR` | Path to market CSV data directory |
| `PSE_*` series | Issue detection thresholds (10 required) |
| `MARKET_INDICES` | Market index names (comma-separated, required) |

See `.env.example` for detailed comments.

## Tech Stack

- **AutoGen** (RoundRobinGroupChat) — Agent orchestration
- **DeepSeek** / OpenAI-compatible — Model backend
- **FastAPI** — Web API with SSE streaming
- **Vite + React** — Dashboard with Chart.js
- **uv** — Python project management

## Adding a New Task

Three steps:

```bash
# 1. Create task directory
mkdir -p tasks/new-task/prompts

# 2. Write three role prompts
#    tasks/new-task/prompts/planner.md
#    tasks/new-task/prompts/specialist.md
#    tasks/new-task/prompts/evaluator.md

# 3. Write entry scripts (optional prepare.py)
#    tasks/new-task/run.py        # Read data → create_pse_team(task="new-task") → run_task()
#    tasks/new-task/meta.json     # Name and description
```

Then register in `tasks/_registry.json` — `pse list` will pick it up.
