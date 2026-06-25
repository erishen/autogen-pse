"""用 PSE 做投资周报。读取 prepare 生成的摘要，喂给 PSE 分析。"""

import asyncio
import re
import sys
from pathlib import Path

BASE = Path(__file__).parent  # tasks/portfolio-review/
sys.path.insert(0, str(BASE.parent.parent / "src"))
from autogen_pse import create_pse_team, run_task  # noqa: E402

PROMPT_FILE = BASE / "output/portfolio_review_prompt.md"


def clean_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


async def main():
    if not PROMPT_FILE.exists():
        print(f"❌ 未找到 {PROMPT_FILE}，请先运行 prepare.py（make summarize）")
        return

    task = clean_ansi(PROMPT_FILE.read_text(encoding="utf-8"))
    team = create_pse_team(task="portfolio-review")
    result, report = await run_task(team, task, verbose=True)
    print(report.summary())


if __name__ == "__main__":
    asyncio.run(main())
