<div align="right">
  <a href="README.md">🌐 English</a>
</div>

# autogen-pse

基于 Microsoft AutoGen 的 **task-agnostic（任务无关）Planner–Specialist–Evaluator（PSE）三角色 Agent 框架**。三个角色各司其职、独立验证，形成闭环交付流水线。框架只负责跑 PSE 循环，任务由你注册进来。

> **这是本工作区 PSE 框架家族四个成员之一 —— 同一套理念，不同的编排后端：**
> - **autogen-pse**（本仓库）—— 基于 AutoGen `RoundRobinGroupChat` 的 PSE，带可选 RAG 与 Web Dashboard。
> - **crewai-pse** —— 基于 CrewAI `Sequential` 的 PSE（用于项目代码 → 中英文章 → 发布 erishen.cn）。
> - **langgraph-pse** —— 基于 LangGraph 状态机的 PSE（用于 CRM 数据质量 QA + 每周关系复盘）。
> - **llamaindex-pse** —— 基于 LlamaIndex Workflow、内置 RAG 的 PSE（用于简历定制）。

## 快速开始

```bash
cp .env.example .env          # 配置 API Key 及任务相关路径
uv sync                        # 安装依赖
make demo                      # 运行最小快排任务（验证流水线）
```

## 任务是可插拔的

引擎本身不关心投资、代码还是 CRM —— 它只对你注册的任务跑 PSE 循环。当前内置两个任务：

| 任务 | 定位 | 用途 |
|------|------|------|
| `demo` | 最小示例 | Planner → Specialist 写快排代码 → Evaluator 跑 pytest + ruff，端到端验证流水线。 |
| `portfolio-review` | **参考任务** | 作者主力场景：读 `asset-lens` 的 JSON/CSV，由规则引擎 `prepare.py` 产出结构化摘要（零 LLM 成本），再由 PSE 三角色撰写**下周投资建议**（原称「投资周报」）并联立核验数据。 |

更多任务放到 `tasks/<your-task>/` 即可（见「扩展新任务」）。在 `tasks/_registry.json` 注册后，`python cli.py list` 会自动发现。

## 项目结构

```
autogen-pse/
├── src/autogen_pse/           # 框架引擎（跨任务不变）
│   ├── orchestrator.py        # PSE 循环：循环控制、step_buffer、trace 与 token 统计
│   ├── agents.py              # Planner / Specialist / Evaluator 工厂（task 感知）
│   ├── prompts.py             # 提示词加载器 —— 任务专属优先，回退到 demo
│   ├── tools.py               # 工具沙箱（read_file/bash/pytest/ruff）+ token 统计
│   └── config.py              # pydantic-settings 的 .env 加载器
├── tasks/                     # ← 任务插拔目录
│   ├── _registry.json         # 任务清单（name → label / description / env_required）
│   ├── demo/                  # 最小示例任务
│   │   ├── meta.json / run.py / prompts/
│   │   └── output/            # 生成产物（gitignored）
│   └── portfolio-review/      # 参考任务（投资周报）
│       ├── meta.json / run.py / prepare.py / prepare_market.py / prompts/
│       ├── sanitize_rules.toml # 报告后处理护栏
│       └── output/            # 生成产物 + archive/（gitignored）
├── web/                       # Vite + React 前端（Chart.js）
├── web_server.py              # FastAPI 后端（SSE 流式）
├── cli.py                     # pse list / run / prepare / trace
├── tests/                     # 单元测试
├── Makefile
├── .env.example
└── .gitignore
```

## 三个入口

### CLI — 任务平台

```bash
python cli.py list              # 列出所有已注册任务
python cli.py run <task>        # 运行任务（prepare → PSE）
python cli.py prepare <task>    # 仅跑数据准备（若任务含 prepare.py）
python cli.py trace -n 5        # 查看最近 5 次执行 trace
```

### Makefile — 快捷命令

```bash
make demo            # 运行 demo 任务
make summarize       # portfolio-review：生成结构化摘要（零 LLM 成本）
make review          # portfolio-review：完整 PSE 下周投资建议（DeepSeek）
make review-agnes    # portfolio-review：完整 PSE 下周投资建议（Agnes 2.0 Flash）
make market          # portfolio-review：最新市场指数
make serve           # 启动 Web Dashboard（http://localhost:8080）
make test            # 运行单元测试
make lint            # ruff 检查 + 格式化
```

> `summarize` / `review` / `market` 是 `portfolio-review` 任务的薄封装。新增任务请用 `python cli.py run <your-task>`（或自行加 Makefile 目标）。

**`make summarize`** 是日常工具：读 `asset-lens` 的 JSON 输出，生成结构化摘要，并用规则引擎自动检测 4 类持仓问题（长期亏损、资金效率低、高波动、结构问题）。零 LLM 成本。

**`make review`** 是深度分析：PSE 三角色在摘要基础上撰写**下周投资建议**、独立验证数据准确性。只在想听第二种意见时跑。

**`make serve`** 启动 Web Dashboard：`http://localhost:8080` — 资产趋势图、一键触发任务、执行历史。

## PSE 三角色分工

| 角色 | 职责 | 约束 |
|------|------|------|
| **Planner** | 分析需求、分解任务、委托执行、交付决策 | 不写代码，不做计算 |
| **Specialist** | 执行具体任务，产物写磁盘 | 只做分配的事，完成后汇报 |
| **Evaluator** | 独立验证产物，输出判决 | 不信任 Planner，不给建议，只判 PASS / PARTIAL / FAIL |

工具按最小权限挂载到各 Agent：Planner 有 `read_file` + `bash`；Specialist 有 `read_file`；Evaluator 有 `read_file` + `bash` + `pytest` + `ruff`。

## 循环控制与 step_buffer

每次任务由若干次 plan→execute→evaluate 循环组成：

```
Planner → Specialist → Evaluator
           ↑    PARTIAL     │
           └── 修复后重试 ──┘  （最多 MAX_PARTIAL_RETRIES = 3）
           ↑    FAIL         │
           └── 重新 plan ───┘  （最多 MAX_FAIL_RETRIES = 2，超限 BLOCKED）

PASS → "交付完成"  ·  BLOCKED → 停止
```

**step_buffer**：PARTIAL 只传判决摘要保持焦点；FAIL 清空上下文重新 plan，避免 token 失控。每轮循环的详细 Trace（判决、各 Agent Token 消耗、耗时、完整对话）写入 `outputs/traces/trace_*.json`。

可通过环境变量调节：`PSE_MAX_PARTIAL_RETRIES`、`PSE_MAX_FAIL_RETRIES`、`PSE_TURNS_PER_CYCLE`、`PSE_TIMEOUT`、`PSE_MODEL_STREAM`。

## 环境变量

框架级配置（所有任务都需要）：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | LLM API Key |
| `OPENAI_BASE_URL` | API 地址（默认 DeepSeek） |
| `OPENAI_MODEL` | 模型名 |

每个任务可额外声明自己的变量，写在 `meta.json` 的 `env_required` 中。例如 `portfolio-review` 需要 `ASSET_LENS_DIR`、`MONEY_CSV_DIR`、`MARKET_INDICES` 以及 `PSE_*` 检测阈值（共 10 项）。完整注释见 `.env.example`。

## 技术栈

- **AutoGen** (`RoundRobinGroupChat`) — Agent 编排
- **DeepSeek** / OpenAI 兼容 — 模型后端（也支持 Agnes）
- **FastAPI** — Web API（SSE 流式）
- **Vite + React** — Dashboard（Chart.js）
- **uv** — Python 项目管理

## 成本

计费随模型后端而定。DeepSeek Chat（约 ¥2 / 1M 输入 token、¥8 / 1M 输出 token）下一次典型 `portfolio-review` 分析约 ¥0.08–¥0.65；`demo` 任务相近。`make summarize` 零 LLM token（纯规则引擎）。

## 扩展新任务

任务就是 `tasks/` 下的一个目录，四件套即可：

```
tasks/my-task/
├── meta.json              # { name, label, description, env_required: [...] }
├── run.py                 # 入口：读数据 → create_pse_team(task="my-task") → run_task(team, TASK_TEXT, verbose=...)
├── prepare.py             # （可选）零 LLM 数据准备；通过 `cli.py prepare` 运行
└── prompts/
    ├── planner.md         # Planner 系统提示词
    ├── specialist.md      # Specialist 系统提示词
    └── evaluator.md       # Evaluator 系统提示词
```

步骤：

1. **建目录** —— `mkdir -p tasks/my-task/prompts`。
2. **写三个角色提示词。** 只覆盖想和 `demo` 不同的角色即可；`load_prompt(name, task)` 会回退到 `demo` 的提示词补全你省略的文件。*(可选：加 `<role>_rules.md` 注入私有规则 —— 其内容会替换提示词中的 `{INVESTMENT_RULES}` / `{STOP_LOSS_RULES}` 占位符。)*
3. **写 `run.py`** —— 组装任务文本（例如读准备好的数据），调用 `create_pse_team(task="my-task")`，再 `await run_task(team, task_text, verbose=True)`。Evaluator 判 PASS 即结束循环；之后可从 trace 提取并落盘产物（参照 `portfolio-review/run.py`）。
4. **在 `tasks/_registry.json` 注册** —— 加入 `"my-task": { "label": "...", "description": "...", "env_required": [...] }`。`python cli.py list` 立即可见。

无需改动引擎。

## 与兄弟框架的关系

四者共享 **PSE 角色模型**与**验证→修正循环**，区别在编排：

| | `autogen-pse` | `crewai-pse` | `langgraph-pse` | `llamaindex-pse` |
|---|---|---|---|---|
| 编排 | **AutoGen `RoundRobinGroupChat`** | CrewAI `Sequential` | LangGraph `StateGraph` + 条件边 | LlamaIndex `Workflow` + `@step` + Event |
| 核查步骤 | 独立 Evaluator（PASS/PARTIAL/FAIL）+ grep/pytest/ruff | `run.py` 里正则/grep | 图中注入 `verify_fn` | 工作流中注入 `verify_fn` |
| RAG | 可选 | — | — | **内置**（`retriever`，源头接地） |
| 额外能力 | **Web Dashboard（FastAPI + React）+ CLI 任务平台** | 写/发/归档三步 | 内置两个 CRM 任务 | RAG 索引缓存 |
| 实际用途 | **asset-lens → 下周投资建议** | 项目代码 → 中英文章 → WordPress | CRM 数据质量 QA + 每周关系复盘 | 简历定制（RAG） |
| 最适合 | 便宜、高频草稿 | 更丰富的多 Agent 发布 | 需要显式状态控制的工作流 | RAG 接地生成 |

## 许可证

MIT

---

## 相关文章
- [基于 AutoGen 构建 PSE 三角色闭环：一个可重试、可追溯的 Agent 协作框架](https://erishen.cn/autogen-pse-triangle-agent-framework/)
