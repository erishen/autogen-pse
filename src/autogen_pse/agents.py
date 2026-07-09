"""Agent 定义：Planner, Specialist, Evaluator。"""

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient

from .config import settings
from .prompts import load_prompt
from .tools import bash, read_file, run_pytest, run_ruff


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
    # 文章写作任务不需要工具（Planner 已读源码、出提纲）
    tools = [read_file]
    return AssistantAgent(
        name="Specialist",
        model_client=model_client,
        system_message=load_prompt("specialist", task),
        description="实施者",
        model_client_stream=settings.PSE_MODEL_STREAM,
        tools=tools,
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
