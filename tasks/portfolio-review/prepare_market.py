"""从最新的 money-csv 目录提取市场指数行情。"""

import csv
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).parent  # tasks/portfolio-review/
load_dotenv(BASE.parent.parent / ".env")

DATA_DIR = os.getenv("MONEY_CSV_DIR")
if not DATA_DIR:
    sys.exit("请先配置 .env 中的 MONEY_CSV_DIR")
DATA_DIR = Path(DATA_DIR)
PROMPT_FILE = BASE / "output/portfolio_review_prompt.md"
_MARKET_INDICES = os.getenv("MARKET_INDICES")
if not _MARKET_INDICES:
    sys.exit("请先配置 .env 中的 MARKET_INDICES（逗号分隔的指数列名）")
MARKET_INDICES = [name.strip() for name in _MARKET_INDICES.split(",")]
INDICES = [(name, name) for name in MARKET_INDICES]


def _pct(prev_val: str, curr_val: str) -> float:
    try:
        p, c = float(prev_val), float(curr_val)
        return (c - p) / abs(p) * 100 if p != 0 else 0
    except (ValueError, TypeError):
        return 0


def get_latest_data() -> tuple[str, list]:
    """返回 (目录名, 最后两行数据)。"""
    dirs = sorted(DATA_DIR.glob("money_csv_*"), reverse=True)
    if not dirs:
        raise FileNotFoundError(f"未找到 money_csv_* 目录，路径: {DATA_DIR}")
    latest = dirs[0]
    csv_path = latest / "资产汇总-表格 1.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"未找到资产汇总: {csv_path}")

    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    if len(rows) < 2:
        raise ValueError(f"行数不足: {len(rows)}")

    return latest.name, rows[-2:]


def build_markdown(latest_dir: str, prev: dict, curr: dict) -> str:
    lines = [
        f"## 近期市场行情（来源: {latest_dir}）",
        "",
        f"| 指数 | 上周 ({prev['日期']}) | 本周 ({curr['日期']}) | 周涨跌 |",
        "|------|------|------|------|",
    ]
    for display_name, col_name in INDICES:
        pv = prev.get(col_name, "0")
        cv = curr.get(col_name, "0")
        chg = _pct(pv, cv)
        lines.append(
            f"| {display_name} | {pv} | {cv} | {'+' if chg > 0 else ''}{chg:.2f}% |"
        )
    return "\n".join(lines)


def update_prompt_file(market_md: str) -> None:
    content = PROMPT_FILE.read_text(encoding="utf-8")
    content = re.sub(
        r"## 近期市场行情.*?(?=## 任务)",
        market_md + "\n\n",
        content,
        flags=re.DOTALL,
    )
    PROMPT_FILE.write_text(content, encoding="utf-8")
    print(f"✅ 已更新 {PROMPT_FILE}")


def main():
    latest_dir, (prev, curr) = get_latest_data()
    market_md = build_markdown(latest_dir, prev, curr)
    print(market_md)

    if "--prompt" in sys.argv:
        update_prompt_file(market_md)


if __name__ == "__main__":
    main()
