# autogen-pse

基于 Microsoft AutoGen 的 **Planner-Specialist-Evaluator 三角色 Agent 框架**。三个角色各司其职、独立验证，形成闭环交付流水线。

## 快速开始

```bash
cp .env.example .env          # 配置 API Key 和外部路径
uv sync                        # 安装依赖
make demo                      # 运行快速排序 Demo
```

## 项目结构

```
autogen-pse/
├── src/autogen_pse/           # 框架核心（引擎不变）
├── tasks/                     # 任务注册中心
│   ├── _registry.json         # 所有任务的元信息
│   ├── demo/                  # 代码交付 Demo
│   │   ├── meta.json / run.py / prompts/
│   │   └── output/            # 生成产物（gitignored）
│   └── portfolio-review/      # 投资周报分析
│       ├── meta.json / run.py / prompts/
│       ├── prepare.py          # 数据准备（零 LLM 成本）
│       ├── prepare_market.py   # 市场指数提取
│       └── output/             # 生成产物（gitignored）
├── web/                       # Vite + React 前端
│   ├── src/App.jsx / App.css
│   ├── src/TrendChart.jsx     # 资产趋势图（Chart.js）
│   └── src/api.js             # API 客户端
├── web_server.py              # FastAPI 后端
├── cli.py                     # pse list / pse run <task> / pse trace ✅ 新增
├── tests/                     # 31 条测试用例
├── Makefile
├── .env.example               # 配置模板
└── .gitignore
```

## 三个入口

### CLI — 任务平台

```bash
python cli.py list              # 列出所有任务
python cli.py run <task>        # 运行任务（prepare → PSE）
python cli.py trace -n 5        # 查看最近 5 次执行 trace
```

### Makefile — 快捷命令

```bash
make demo        # 代码交付 Demo
make summarize   # 生成投资摘要（零成本）
make review      # 投资周报 PSE 分析
make market      # 最新指数行情
make serve      # 启动 Web Dashboard（http://localhost:8080）
make test        # 31 条测试
make lint        # 代码检查
```

**`make summarize`** 是日常工具：读 asset-lens 的 JSON 输出，生成结构化摘要，并用规则引擎自动检测 4 类持仓问题（长期亏损、资金效率低、高波动、结构问题）。零 LLM 成本。

**`make review`** 是深度分析：PSE 三角色基于摘要编写投资报告、独立验证数据准确性。只在拿不准时跑。

**`make serve`** 启动 Web Dashboard：`http://localhost:8080` — 资产趋势图、一键触发任务、执行历史。

## PSE 三角色分工

| 角色 | 职责 | 约束 |
|------|------|------|
| **Planner** | 分析需求、分解任务、委托执行、交付决策 | 不写代码，不做计算 |
| **Specialist** | 执行具体任务，产物写磁盘 | 只做分配的事，完成后汇报 |
| **Evaluator** | 独立验证产物，输出判决 | 不信任 Planner，不给建议，只判 PASS/PARTIAL/FAIL |

## 循环控制和 step_buffer

每次任务由若干次 plan→execute→evaluate 循环组成：

```
Planner → Specialist → Evaluator
           ↑    PARTIAL     │
           └── 修复后重试 ──┘  （最多 3 次）
           ↑    FAIL         │
           └── 重新 plan ───┘  （最多 2 次，超限自动 BLOCKED）

PASS → 交付完成
```

**step_buffer**: PARTIAL 只传判决摘要保持焦点；FAIL 清空上下文重新 plan，避免 token 失控。

每轮循环的详细 Trace（判决结果、各 Agent Token 消耗、耗时）写入 `outputs/traces/trace_*.json`。

## 环境变量

所有配置集中在 `.env`，包括：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | LLM API Key |
| `OPENAI_BASE_URL` | API 地址 |
| `ASSET_LENS_DIR` | asset-lens 项目路径 |
| `MONEY_CSV_DIR` | 资产汇总 CSV 数据路径 |
| `PSE_*` 系列 | 问题检测阈值（10 项，全部必填） |
| `MARKET_INDICES` | 市场指数名（逗号分隔，必填） |

详见 `.env.example` 中的逐项注释。

## 技术栈

- **AutoGen** (RoundRobinGroupChat) — Agent 编排
- **DeepSeek** / OpenAI 兼容 — 模型后端
- **uv** — Python 项目管理

## 扩展新任务

三步加一个新场景：

```bash
# 1. 创建任务目录
mkdir -p tasks/new-task/prompts

# 2. 写三个角色提示词
#    tasks/new-task/prompts/planner.md
#    tasks/new-task/prompts/specialist.md
#    tasks/new-task/prompts/evaluator.md

# 3. 写入口脚本（可选 prepare.py）
#    tasks/new-task/run.py        # 读数据 → create_pse_team(task="new-task") → run_task()
#    tasks/new-task/meta.json     # 名称和描述
```

然后在 `tasks/_registry.json` 注册，`pse list` 就能看到了。
