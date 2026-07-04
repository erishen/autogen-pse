"""加载系统提示词，自动注入私密规则文件。"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent.parent / "tasks"


def _load_private_rules(task_dir: Path, name: str) -> str:
    """加载任务私密规则文件（_rules.md），不存在时返回空字符串。"""
    rules_path = task_dir / f"{name}_rules.md"
    if rules_path.exists():
        return rules_path.read_text(encoding="utf-8").strip()
    return ""


def _inject_rules(template: str, name: str, task_dir: Path) -> str:
    """将 {INVESTMENT_RULES} / {STOP_LOSS_RULES} 占位符替换为私密规则文件内容。"""
    rules = _load_private_rules(task_dir, name)
    if not rules:
        return template

    # 替换可能的占位符
    for placeholder in ("INVESTMENT_RULES", "STOP_LOSS_RULES"):
        key = "{" + placeholder + "}"
        template = template.replace(key, rules)
    return template


def load_prompt(name: str, task: str | None = None) -> str:
    """加载指定角色的系统提示词。

    Args:
        name: 角色名称（planner, specialist, evaluator）
        task: 任务目录名（如 "portfolio_review"），为 None 时用通用提示词

    Returns:
        完整的系统提示词文本
    """
    if task:
        task_dir = PROMPTS_DIR / task
        prompt_path = task_dir / "prompts" / f"{name}.md"
        if prompt_path.exists():
            template = prompt_path.read_text(encoding="utf-8")
            return _inject_rules(template, name, task_dir / "prompts")

    # 回退到通用提示词
    prompt_path = PROMPTS_DIR / "demo" / "prompts" / f"{name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")
