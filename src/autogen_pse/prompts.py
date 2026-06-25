"""加载系统提示词。"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent.parent / "tasks"


def load_prompt(name: str, task: str | None = None) -> str:
    """加载指定角色的系统提示词。

    Args:
        name: 角色名称（planner, specialist, evaluator）
        task: 任务目录名（如 "portfolio_review"），为 None 时用通用提示词

    Returns:
        完整的系统提示词文本
    """
    if task:
        prompt_path = PROMPTS_DIR / task / "prompts" / f"{name}.md"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
    # 回退到通用提示词
    prompt_path = PROMPTS_DIR / "demo" / "prompts" / f"{name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")
