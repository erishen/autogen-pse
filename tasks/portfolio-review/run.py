"""用 PSE 做投资周报。读取 prepare 生成的摘要，合并知识库后喂给 PSE 分析。"""

import asyncio
import json
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


def extract_data_date(task: str) -> str:
    """从任务文本中提取数据截止日期，如 2026年06月27日 → 20260627"""
    m = re.search(r"(\d{4})年(\d{2})月(\d{2})日", task)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return ""


def extract_review_from_trace(task: str) -> str | None:
    """读取最新的 trace JSON，提取 Specialist 最终结论部分。"""
    trace_dir = settings.trace_dir
    if not trace_dir or not trace_dir.is_dir():
        return None

    files = sorted(trace_dir.glob("trace_*.json"), reverse=True)
    if not files:
        return None

    trace = json.loads(files[0].read_text())

    # 收集所有 Specialist 消息，找到最后一条
    specialist_msgs = []
    for cycle in trace.get("cycles", []):
        for msg in cycle.get("messages", []):
            source = msg.get("source", "")
            content = msg.get("content", "")
            if source != "Specialist" or not content.strip():
                continue
            # 只移除 AutoGen 的 DSML/xml 标签，保留 Markdown 中的 < > 字符（如「年化 < 2%」）
            clean = re.sub(
                r"</?\s*(tool_calls|invoke|parameter|read_file|write_file|bash|run_pytest|run_ruff)[^>]*>",
                "",
                content,
            ).strip()
            if clean:
                specialist_msgs.append(clean)

    if not specialist_msgs:
        return None

    # 取 Specialist 中包含「最终结论」的最长消息（最完整版本）
    # 多个 cycle 时后轮消息可能被截断得更短，取最长而非最后
    best = ""
    for s in specialist_msgs:
        if re.search(r"^##\s*🎯?\s*最终结论", s, re.MULTILINE):
            if len(s) > len(best):
                best = s

    if not best:
        best = specialist_msgs[-1]  # fallback
    last = best

    # 用正则匹配行首的「最终结论」标题（避免匹配到表格中的文字引用）
    m = re.search(r"^##\s*🎯?\s*最终结论", last, re.MULTILINE)
    if m:
        result = last[m.start() :].strip()
        # 截断后续无关章节（最终结论章节内不含 --- 分隔线，遇到即截断）
        result = re.split(r"\n---\n+", result, maxsplit=1)[0].strip()
        parts = files[0].stem.split("_")
        ts = f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:]} {parts[2][:2]}:{parts[2][2:4]}:{parts[2][4:]}"
        return f"# 投资组合诊断 — 最终结论\n\n{result}\n\n---\n*报告生成时间: {ts}*"

    # 无「最终结论」标记时，尝试从尾部关键标记处截取
    parts = files[0].stem.split("_")
    ts = f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:]} {parts[2][:2]}:{parts[2][2:4]}:{parts[2][4:]}"
    for marker in [
        "### 整体评估",
        "## 🎯 整体评估",
        "整体评估",
        "### 建议操作",
        "### 关键发现",
        "### 后续跟踪",
        "建议操作",
        "关键发现",
    ]:
        pos = last.rfind(marker)
        if pos > len(last) * 0.4:  # 确保在后半部分，避免匹配到文中引用
            result = last[pos:].strip()
            result = re.split(r"\n---\n+", result, maxsplit=1)[0].strip()
            return f"# 投资组合诊断 — 最终结论\n\n{result}\n\n---\n*报告生成时间: {ts}*"
    # 兜底：取最后 30%
    cutoff = len(last) * 7 // 10
    return f"# 投资组合诊断 — 最终结论\n\n{last[cutoff:].strip()}"


async def main():
    if not PROMPT_FILE.exists():
        print(f"❌ 未找到 {PROMPT_FILE}，请先运行 prepare.py（make summarize）")
        return

    task = clean_ansi(PROMPT_FILE.read_text(encoding="utf-8"))
    data_date = extract_data_date(task)

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

    # 从 trace 提取并保存 review 文件
    review = extract_review_from_trace(task)
    if review:
        review_file = BASE / f"output/weekly_review_{data_date}.md"
        review_file.write_text(review, encoding="utf-8")
        print(f"✅ Review 已保存 → {review_file}")
    else:
        print("⚠️ 未能从 trace 提取 review 内容（trace 可能为空）")


if __name__ == "__main__":
    asyncio.run(main())
