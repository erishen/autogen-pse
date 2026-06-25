"""Agent 定义：Planner, Specialist, Evaluator。"""

from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient

from .prompts import load_prompt


# ---- 工具函数 ----


def write_file(path: str, content: str) -> str:
    """将 content 写入 path 指定的文件。会自动创建不存在的目录。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"已写入 {p} ({len(content)} 字符)"


def read_file(path: str) -> str:
    """读取指定文件的内容。"""
    p = Path(path)
    if not p.exists():
        return f"[错误] 文件不存在: {path}"
    return p.read_text(encoding="utf-8")


def run_pytest(test_path: str) -> str:
    """运行 pytest 并返回结果。"""
    import subprocess
    import sys

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(Path.cwd()),
        )
        return result.stdout + "\n" + result.stderr
    except Exception as e:
        return f"[错误] pytest 执行失败: {e}"


def run_ruff(path: str) -> str:
    """运行 ruff 代码检查。"""
    import subprocess
    import sys

    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", path],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path.cwd()),
        )
        return result.stdout or "ruff 检查通过，无问题。"
    except Exception as e:
        return f"[错误] ruff 执行失败: {e}"


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
        tools=[write_file],
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
        tools=[read_file, run_pytest, run_ruff],
        reflect_on_tool_use=True,
    )
