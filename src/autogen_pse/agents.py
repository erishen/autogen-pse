"""Agent 定义：Planner, Specialist, Evaluator。"""

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient

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
        model_client_stream=True,
        tools=[read_file, bash],
        reflect_on_tool_use=True,
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
        model_client_stream=True,
        tools=[write_file, bash, read_file, run_ruff, run_pytest],
        reflect_on_tool_use=True,
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
        model_client_stream=True,
        tools=[read_file, run_pytest, run_ruff, bash],
        reflect_on_tool_use=True,
    )
