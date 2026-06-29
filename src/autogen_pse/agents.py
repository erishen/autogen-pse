"""Agent 定义：Planner, Specialist, Evaluator。"""

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient

from .config import settings
from .prompts import load_prompt
from .tools import bash, read_file, run_pytest, run_ruff


def write_file(path: str, content: str) -> str:
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"已写入 {p} ({len(content)} 字符)"


# ---- Agent 工厂函数 ----


def create_planner(
    model_client: OpenAIChatCompletionClient, task: str | None = None
) -> AssistantAgent:
    """创建 Planner Agent。"""
    return AssistantAgent(
        name="Planner",
        model_client=model_client,
        system_message=load_prompt("planner", task),
        description="交付负责人",
        model_client_stream=settings.PSE_MODEL_STREAM,
        tools=[read_file, bash],
        reflect_on_tool_use=False,
    )


def create_specialist(
    model_client: OpenAIChatCompletionClient, task: str | None = None
) -> AssistantAgent:
    """创建 Specialist Agent。"""
    return AssistantAgent(
        name="Specialist",
        model_client=model_client,
        system_message=load_prompt("specialist", task),
        description="实施者",
        model_client_stream=settings.PSE_MODEL_STREAM,
        tools=[read_file],
        reflect_on_tool_use=False,
    )


def create_tool_agent(
    model_client: OpenAIChatCompletionClient,
) -> AssistantAgent:
    """创建 ToolAgent — 解析并执行工具调用，自动保存 review 文件，查询市场行情。"""
    return AssistantAgent(
        name="ToolAgent",
        model_client=model_client,
        system_message=(
            "你是 ToolAgent，负责执行工具调用。\n\n"
            "## 角色定位\n\n"
            "你不做投资分析，不写报告，只负责执行工具调用。\n\n"
            "## 执行 DSML 工具调用\n\n"
            "读取上一条来自 Planner/Specialist/Evaluator 的消息，"
            "如果包含 `<tool_calls>`...</tool_calls>` 格式的 DSML 标签，"
            "解析并执行对应的工具函数。\n"
            "如果上一条消息不包含 DSML 标签，回复「无待执行操作」。\n\n"
            "## 自动保存 review\n\n"
            "当 Evaluator 给出 PASS 判决后，找到对话中 Specialist 最后一次输出的完整 review 内容，"
            "用 write_file 保存到 `tasks/portfolio-review/output/weekly_review_YYYYMMDD.md`。"
            "日期从对话中提取（如「2026年06月27日」→ `20260627`）。\n\n"
            "## 可用工具\n\n"
            "- `write_file(path, content)` — 写入文件\n"
            "- `read_file(path)` — 读取文件\n"
            "- `bash(command)` — 执行 shell 命令\n"
            "- `run_pytest(test_path)` — 运行测试\n"
            "- `run_ruff(path)` — 运行 ruff 检查"
        ),
        description="工具执行者",
        model_client_stream=settings.PSE_MODEL_STREAM,
        tools=[write_file, bash, read_file, run_pytest, run_ruff],
        reflect_on_tool_use=False,
    )


def create_evaluator(
    model_client: OpenAIChatCompletionClient, task: str | None = None
) -> AssistantAgent:
    """创建 Evaluator Agent。"""
    return AssistantAgent(
        name="Evaluator",
        model_client=model_client,
        system_message=load_prompt("evaluator", task),
        description="独立评审官",
        model_client_stream=settings.PSE_MODEL_STREAM,
        tools=[read_file, bash, run_pytest, run_ruff],
        reflect_on_tool_use=False,
    )
