"""用 PSE 做投资周报。读取 prepare 生成的摘要，合并知识库后喂给 PSE 分析。"""

import asyncio
import re
import sys
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE.parent.parent / "src"))
from autogen_pse import (  # noqa: E402
    create_pse_team,
    run_task,
    format_knowledge_context,
    retrieve_knowledge,
    settings,
)

PROMPT_FILE = BASE / "output/portfolio_review_prompt.md"


def clean_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


async def main():
    if not PROMPT_FILE.exists():
        print(f"❌ 未找到 {PROMPT_FILE}，请先运行 prepare.py（make summarize）")
        return

    task = clean_ansi(PROMPT_FILE.read_text(encoding="utf-8"))

    # 注入个人投资知识（可选）
    if settings.has_knowledge_base:
        print("📚 正在检索个人投资知识库...")
        knowledge = retrieve_knowledge(settings.KNOWLEDGE_BASE_PATH)
        ctx = format_knowledge_context(knowledge)
        if ctx:
            task = f"{task}\n\n{ctx}"
            print("✅ 知识已注入分析上下文")
    else:
        print("ℹ️ 未配置 KNOWLEDGE_BASE_PATH，跳过知识库检索")

    team = create_pse_team(task="portfolio-review")
    result, report = await run_task(team, task, verbose=True)
    print(report.summary())


if __name__ == "__main__":
    asyncio.run(main())
