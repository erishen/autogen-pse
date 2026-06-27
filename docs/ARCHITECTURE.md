# autogen-pse 架构文档

> Planner-Specialist-Evaluator 三角色 Agent 框架
> 基于 Microsoft AutoGen (RoundRobinGroupChat)

---

## 架构总览

```
CLI (cli.py)
  │
  ├─ make summarize → prepare.py       ← 数据准备层（零 LLM 成本）
  │                     │
  │                     └─ asset-lens JSON/CSV → 结构化摘要 + 规则引擎检测
  │
  └─ make review    → run.py           ← PSE 分析层（LLM 驱动）
                        │
                        └─ create_pse_team() → orchestrator.py
                             │
                             ├─ Planner      ← 分析需求、分解任务、交付决策
                             ├─ Specialist   ← 生成分析报告
                             ├─ Evaluator    ← 独立验证数据准确性
                             └─ ToolAgent    ← 执行工具调用、保存产物
                                  │
                                  └─ tools.py → RAG 知识库检索 (.env 可选)
```

---

## 核心组件

### 1. 任务注册系统

`tasks/` 目录下每个子目录即一个独立任务，通过以下文件定义：

```
tasks/<task-name>/
├── meta.json         # 名称和描述（供 `pse list` 展示）
├── run.py            # 入口脚本：读取数据 → 创建 PSE 团队 → 执行分析
├── prepare.py        # （可选）数据准备脚本，零 LLM 成本
├── prepare_market.py # （可选）实时行情数据提取
├── prompts/
│   ├── planner.md    # Planner 角色提示词
│   ├── specialist.md # Specialist 角色提示词
│   └── evaluator.md  # Evaluator 角色提示词
└── output/           # 生成产物（gitignored）
    └── archive/      # 按日期归档
```

任务在 `tasks/_registry.json` 中注册，供 CLI 发现。

内置任务：
- **demo** — 快速排序代码交付演示，验证 PSE 流程可用性
- **portfolio-review** — 投资周报分析（当前主力任务）

### 2. PSE 三角色设计

灵感源自 [agentic-souls](https://github.com/erishen/agentic-souls) 的文档驱动开发模式，将软件开发中的"计划→执行→验证"循环映射到投资分析场景。

#### Planner（规划者）

| 属性 | 值 |
|------|-----|
| 角色 | 首席投资顾问 / 交付负责人 |
| 注册工具 | `read_file`, `bash` |
| 职责 | 获取实时行情、分解分析任务、委托 Specialist 执行、调用 Evaluator 验证、PASS/FAIL 判决 |
| 循环行为 | PASS → 宣布交付完成；PARTIAL → 指出修复项；FAIL → 重新 plan |

#### Specialist（执行者）

| 属性 | 值 |
|------|-----|
| 角色 | 投资研报撰写人 |
| 注册工具 | `read_file`（仅读取权限） |
| 职责 | 执行 Planner 分配的任务，输出完整 markdown 分析报告 |
| 输出规范 | 所有数字可追溯原始数据，调仓建议包含产品/金额/方向/理由/优先级 |
| 报告结构 | 包含数据诊断、风险警示、调仓建议、验收清单 |
| 最终结论 | 报告末尾 `## 🎯 最终结论` 章节独立提取为周报文件 |

#### Evaluator（评审者）

| 属性 | 值 |
|------|-----|
| 角色 | 独立投资评审官 |
| 注册工具 | `read_file`, `run_pytest`, `run_ruff` |
| 职责 | 独立验证 Specialist 报告，读取原始数据核验数字 |
| 判决 | PASS / PARTIAL / FAIL（不给修复建议） |
| 验证维度 | 数据溯源、逻辑审查、风险检查、空话检测 |

#### ToolAgent（工具执行者）

| 属性 | 值 |
|------|-----|
| 角色 | 工具执行者（不做分析、不写报告） |
| 注册工具 | `write_file`, `bash`, `read_file`, `run_pytest`, `run_ruff` |
| 职责 | 执行 DSML 工具调用（Planner/Specialist/Evaluator 发出的 `<tool_calls>` 标签） |
| 自动保存 | Evaluator PASS 判决后，保存 Specialist 最终输出到 `output/weekly_review_YYYYMMDD.md` |

### 3. 循环控制流程

```
第 N 轮开始
  │
  ├─ Planner → 分析任务、读取数据、制定计划
  ├─ Specialist → 执行分析、输出报告
  ├─ Evaluator → 验证报告、给出判决
  └─ ToolAgent → 执行工具调用、保存产物
       │
       └─ 判决判定
            ├─ PASS     → 交付完成，退出循环
            ├─ PARTIAL  → 记录次数，≤3 次则带判决摘要重试，>3 次自动 BLOCKED
            ├─ FAIL     → 记录次数，≤2 次则清空上下文重新 plan，>2 次自动 BLOCKED
            └─ TIMEOUT  → 达到 max_turns=20，退出
```

**关键参数：**
- `TURNS_PER_CYCLE = 20` — 每轮最大发言次数
- `MAX_PARTIAL_RETRIES = 3` — PARTIAL 最大重试次数
- `MAX_FAIL_RETRIES = 2` — FAIL 最大重试次数

**Speaker 顺序：** `[Planner, Specialist, Evaluator, ToolAgent]`（RoundRobinGroupChat）

### 4. PSE 编排层 (orchestrator.py)

`orchestrator.py` 是 AutoGen RoundRobinGroupChat 的上层封装，提供：

- **循环控制**：参考 agentic-souls 的 plan→execute→evaluate 循环模式，支持多轮迭代修正
- **Step buffer**：PARTIAL 时只传判决摘要避免 token 膨胀；FAIL 时清空上下文重新 plan
- **执行跟踪**：每轮循环的完整 Trace（判决、Token 消耗、耗时、对话记录）写入 `outputs/traces/trace_*.json`
- **Token 统计**：按 Agent 统计输入/输出 Token 数，预估费用

### 5. 提示词系统 (prompts.py)

提示词按角色和任务分离，存储在 `tasks/<task>/prompts/<role>.md`：

```python
def load_prompt(name: str, task: str | None = None) -> str:
    # 优先加载任务特定提示词
    # 回退到 demo 通用提示词
```

任务特定提示词的优先级高于通用提示词。不同任务可为同一角色定义不同的行为。

### 6. 工具系统 (tools.py)

#### 共享工具

| 工具 | 说明 | 绑定 Agent |
|------|------|-----------|
| `read_file(path)` | 读取文件内容 | Planner, Specialist, Evaluator, ToolAgent |
| `bash(command)` | 执行 shell 命令 | Planner, ToolAgent |
| `write_file(path, content)` | 写入文件 | ToolAgent |
| `run_pytest(test_path)` | 运行测试 | Evaluator, ToolAgent |
| `run_ruff(path)` | 代码风格检查 | Evaluator, ToolAgent |

工具注册策略：**最小权限原则**
- Planner：数据分析权限（read_file + bash）
- Specialist：只读权限（read_file）— 移除写文件和 bash 防止编辑循环
- Evaluator：只读 + 验证权限（read_file + pytest + ruff）
- ToolAgent：全部权限，但仅通过 DSML 标签被动调用

#### DSML 工具调用

DSML (Domain-Specific Markup Language) 是一种基于 XML 标签的工具调用协议，用于 Agent 之间的工具调用委托：

```xml
<tool_calls>
<invoke name="bash">
<parameter name="command" string="true">python3 script.py</parameter>
</invoke>
</tool_calls>
```

Planner/Specialist/Evaluator 通过 DSML 标签委托 ToolAgent 执行操作，ToolAgent 解析标签并调用对应工具函数。

#### Token 统计

`TokenTracker` 从 AutoGen 消息流中自动追踪每个 Agent 的 Token 消耗，按角色汇总并预估费用：

| 角色 | 计价 |
|------|------|
| 输入 Token | ¥2.0 / 1M tokens |
| 输出 Token | ¥8.0 / 1M tokens |
| 典型单次分析费用 | ¥0.08 - ¥0.65 |

---

### 7. RAG 知识库集成

可选模块，从 langchain-llm-toolkit 的 FAISS 向量库中检索个人投资知识，注入 PSE 分析上下文。

#### 检索流程

```
retrieve_knowledge(kb_path)
  │
  ├─ RAGSystem(faiss, ollama nomic-embed-text)
  │     │
  │     ├─ 4 个预设查询
  │     │   ├─ "投资策略 投资偏好 风险偏好"
  │     │   ├─ "个人投资经验 资产配置"
  │     │   ├─ "投资目标 收益预期"
  │     │   └─ "交易纪律 止损 止盈"
  │     └─ 混合检索：k=3, bm25_weight=0.3
  │
  └─ format_knowledge_context(knowledge)
        │
        └─ INVEST_CATS 白名单过滤
             ├─ 允许：01-Investment, 03-Financial
             ├─ 允许：advice, financial, investment, strategy
             └─ 过滤：05-FinTech, fintech（KYC/PayPal 业务笔记）
```

### 8. 数据管道

```
asset-lens (make calculate)
  │
  ├─ JSON: 组合概览、资产配置、风险分布、投资效率
  ├─ CSV: 逐产品明细（名称、金额、收益率、类型等）
  │
  └─ prepare.py
       │
       ├─ 规则引擎检测 4 类问题
       │   ├─ 长期亏损（天数 > PSE_LONG_LOSS_DAYS 且实际收益 < 0）
       │   ├─ 资金效率低（天数 > PSE_LOW_EFF_DAYS 且年化 < PSE_LOW_EFF_MAX_RETURN）
       │   ├─ 高波动（年化 > PSE_HIGH_VOL_MIN_RETURN 且天数 < PSE_HIGH_VOL_MAX_DAYS）
       │   └─ 结构问题（平台集中度 + 关键词聚类重复产品）
       │
       └─ 输出 portfolio_review_prompt.md
            │
            └─ run.py → PSE 分析 → weekly_review_YYYYMMDD.md
```

#### 实时行情

Agent 首次发言时通过两条命令获取最新市场数据：

1. `prepare_market.py` — 本地 money-csv 周环比数据
2. `curl hq.sinajs.cn` — 新浪财经实时指数行情

---

### 9. 执行跟踪 (Trace)

每次 PSE 执行生成一个 JSON trace 文件 `outputs/traces/trace_YYYYMMDD_HHMMSS.json`：

```json
{
  "started_at": "2026-06-27T17:50:23",
  "verdict": "PASS",
  "total_cycles": 3,
  "total_prompt_tokens": 215199,
  "total_completion_tokens": 28116,
  "cycles": [
    {
      "cycle": 1,
      "outcome": "PARTIAL",
      "token": { "total_prompt": 28897, "total_completion": 3025 },
      "messages": [ { "source": "Planner", "content": "..." } ]
    }
  ]
}
```

#### 周报提取

`run.py` 的 `extract_review_from_trace()` 函数从 trace 中提取最终结论：

1. 回溯所有 Specialist 消息，找到包含 `## 🎯 最终结论`（行首正则）的那条
2. 提取该标题后的全部内容
3. 在 `---` 边界处截断，移除验收清单等附加内容
4. 保存到 `output/weekly_review_YYYYMMDD.md`

---

### 10. 配置系统 (config.py)

基于 `pydantic-settings`，所有配置集中在 `.env` 文件：

| 变量 | 说明 | 是否必填 |
|------|------|---------|
| `OPENAI_API_KEY` | LLM API Key | 是 |
| `OPENAI_BASE_URL` | API 地址（默认 DeepSeek） | 否 |
| `OPENAI_MODEL` | 模型名 | 否 |
| `ASSET_LENS_DIR` | asset-lens 项目路径 | 是 |
| `MONEY_CSV_DIR` | 资产汇总 CSV 路径 | 是 |
| `KNOWLEDGE_BASE_PATH` | langchain-llm-toolkit 路径（RAG） | 否 |
| `PSE_*` 系列 | 问题检测阈值（10 项） | 全部必填 |
| `MARKET_INDICES` | 指数列名（逗号分隔） | 是 |

---

### 11. Web Dashboard

- **后端**：FastAPI（`web_server.py`）
- **前端**：Vite + React + Chart.js（`web/`）
- **功能**：资产趋势图、一键触发任务、执行历史查看
- **端口**：`http://localhost:8080`

---

### 12. 设计决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| Agent 工具权限 | Planner: read+bash; Specialist: read 仅; Evaluator: read+pytest+ruff; ToolAgent: 全部 | 防止 Agent 编辑文件陷入循环 |
| 实时行情获取归属 | Planner（第 1 个发言） | ToolAgent 是第 4 个发言，到它时 Evaluator 已可能 PASS |
| 报告保存方式 | `run.py` 从 trace 提取最终结论 | 比 ToolAgent 主动 write_file 更可靠（避免时序问题） |
| 周报内容策略 | 仅保存 `## 🎯 最终结论` 章节 | 消除完整报告正文和 Agent 对话历史的冗余 |
| RAG 分类过滤 | INVEST_CATS 白名单 | "05-FinTech"/"fintech" 含 KYC/PayPal 业务笔记，与投资分析无关 |
| LLM 模型 | DeepSeek Chat（兼容 OpenAI SDK） | 性价比高（¥2/8 per 1M tokens），支持 function calling |
| 发言顺序 | Planner→Specialist→Evaluator→ToolAgent | 计划先行、执行随后、验证收尾、工具最后 |

---

### 13. 快速参考

```bash
# 运行投资周报分析（完整流程）
make review

# 仅生成数据摘要（零 LLM 成本）
make summarize

# 查看实时行情
make market

# 运行 demo 验证 PSE 流程
make demo

# 查看最新执行 trace
python cli.py trace -n 3

# 启动 Web Dashboard
make serve
```
