"""投资周报生成器 — 从 asset-lens 生成结构化摘要。"""

import csv
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).parent  # tasks/portfolio-review/
load_dotenv(BASE.parent.parent / ".env")

ASSET_LENS_DIR = os.getenv("ASSET_LENS_DIR")
MONEY_CSV_DIR = os.getenv("MONEY_CSV_DIR")
if not ASSET_LENS_DIR or not MONEY_CSV_DIR:
    sys.exit("请先配置 .env 中的 ASSET_LENS_DIR 和 MONEY_CSV_DIR")
ASSET_LENS = Path(ASSET_LENS_DIR)
CSV_DIR = Path(MONEY_CSV_DIR)

_MARKET_INDICES = os.getenv("MARKET_INDICES")
if not _MARKET_INDICES:
    sys.exit("请先配置 .env 中的 MARKET_INDICES（逗号分隔的指数列名）")
MARKET_INDICES = [name.strip() for name in _MARKET_INDICES.split(",")]


# ── 数据加载 ──


def _latest_output_file(suffix: str) -> Path:
    output_dir = ASSET_LENS / "output"
    files = sorted(output_dir.glob(f"投资收益率分析_*{suffix}"), reverse=True)
    return (
        files[0]
        if files
        else output_dir / f"投资收益率分析_{datetime.now():%Y%m%d}{suffix}"
    )


def load_json() -> dict:
    subprocess.run(
        ["make", "calculate"],
        cwd=str(ASSET_LENS),
        capture_output=True,
        text=True,
        timeout=120,
    )
    path = _latest_output_file(".json")
    return json.loads(path.read_text(encoding="utf-8"))


def load_products() -> list:
    path = _latest_output_file(".csv")
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ── 报告生成 ──


def _get_val(ev: dict, key: str) -> str:
    return ev.get(key, "?")


def build_overview(data: dict) -> str:
    ev = data.get("comprehensive_evaluation", {})

    def g(k):
        return _get_val(ev, k)

    return "\n".join(
        [
            f"- 当前总资产: {float(g('total_current_amount')) / 10000:.2f}万元",
            f"- 总投入: {float(g('total_investment')) / 10000:.2f}万元",
            f"- 已实现收益: +{float(g('realized_profit')) / 10000:.2f}万元",
            f"- 未实现收益: +{float(g('unrealized_profit')) / 10000:.2f}万元",
            f"- 整体收益率: {g('overall_return_rate')}",
            f"- 加权年化收益率: {g('weighted_annual_return')}",
            f"- 时间加权年化: {g('time_weighted_return')}",
        ]
    )


def build_allocation(data: dict) -> str:
    items = data.get("type_distribution", {})
    lines = []
    sorted_items = sorted(
        items.items(),
        key=lambda x: float(str(x[1].get("percentage", "0%")).rstrip("%")),
        reverse=True,
    )
    for _name, info in sorted_items:
        pct = info.get("percentage", "?")
        amt = float(info.get("total_value", 0))
        if amt >= 10000:
            lines.append(f"  {_name}: {pct}（{amt / 10000:.1f}万元）")
        else:
            lines.append(f"  {_name}: {pct}（{amt:.0f}元）")
    return "\n".join(lines)


def build_risk(data: dict) -> str:
    rd = data.get("risk_distribution", {})
    sorted_items = sorted(
        rd.items(),
        key=lambda x: float(x[1].get("total_value", 0)),
        reverse=True,
    )
    lines = []
    for level, info in sorted_items:
        amt = float(info.get("total_value", 0))
        lines.append(
            f"  {level}: {info.get('percentage', '?')}（¥{amt / 10000:.1f}万）"
        )
    return "\n".join(lines)


# ── 检测阈值（全部从环境变量读取，无默认值） ──


def _env_int(key: str) -> int:
    val = os.getenv(key)
    if val is None:
        sys.exit(f"请先配置 .env 中的 {key}（整数）")
    return int(val)


def _env_float(key: str) -> float:
    val = os.getenv(key)
    if val is None:
        sys.exit(f"请先配置 .env 中的 {key}（数字）")
    return float(val)


def _env_list(key: str) -> list:
    val = os.getenv(key)
    if val is None:
        sys.exit(f"请先配置 .env 中的 {key}（逗号分隔）")
    return [x.strip() for x in val.split(",")]


LONG_LOSS_DAYS = _env_int("PSE_LONG_LOSS_DAYS")
LOW_EFF_DAYS = _env_int("PSE_LOW_EFF_DAYS")
LOW_EFF_MAX_RETURN = _env_float("PSE_LOW_EFF_MAX_RETURN")
LOW_EFF_MIN_AMOUNT = _env_int("PSE_LOW_EFF_MIN_AMOUNT")
HIGH_VOL_MIN_RETURN = _env_float("PSE_HIGH_VOL_MIN_RETURN")
HIGH_VOL_MAX_DAYS = _env_int("PSE_HIGH_VOL_MAX_DAYS")
HIGH_VOL_MIN_AMOUNT = _env_int("PSE_HIGH_VOL_MIN_AMOUNT")
LARGE_POS_TYPES = _env_list("PSE_LARGE_POS_TYPES")
LARGE_POS_MIN_AMOUNT = _env_int("PSE_LARGE_POS_MIN_AMOUNT")
LARGE_POS_MAX_RETURN = _env_float("PSE_LARGE_POS_MAX_RETURN")


def detect_issues(products: list) -> str:
    loss = []
    low_eff = []
    volatile = []
    big_fixed = []

    for r in products:
        name = r.get("\ufeff名称", r.get("名称", ""))
        typ = r.get("类型", "")
        try:
            days = int(r.get("投资天数", "0") or "0")
            ann = float(r.get("年化收益率(%)", "0") or "0")
            real_val = float(r.get("实际收益率(%)", "0") or "0")
            amt = float(r.get("当前金额", "0") or "0")
        except (ValueError, TypeError):
            continue

        if days > LONG_LOSS_DAYS and real_val < 0:
            line = f"- ¥{amt / 10000:.1f}万 | {name[:20]} | {days}天 | {real_val:+.2f}%"
            loss.append((amt, line))
        if (
            days > LOW_EFF_DAYS
            and 0 <= ann < LOW_EFF_MAX_RETURN
            and amt > LOW_EFF_MIN_AMOUNT
        ):
            line = f"- ¥{amt / 10000:.1f}万 | {name[:20]} | {days}天 | 年化{ann:.1f}%"
            low_eff.append((amt, line))
        if (
            ann > HIGH_VOL_MIN_RETURN
            and days < HIGH_VOL_MAX_DAYS
            and amt > HIGH_VOL_MIN_AMOUNT
        ):
            line = (
                f"- ¥{amt / 10000:.2f}万 | {name[:20]} | 年化{ann:.0f}%（仅{days}天）"
            )
            volatile.append((amt, line))
        if (
            amt > LARGE_POS_MIN_AMOUNT
            and typ in LARGE_POS_TYPES
            and ann < LARGE_POS_MAX_RETURN
        ):
            line = f"- ¥{amt / 10000:.0f}万 | {name[:20]} | {typ} | 年化{ann:.1f}%"
            big_fixed.append((amt, line))

    # 平台集中度
    pt: dict = {}
    for r in products:
        try:
            plat = r.get("所属平台", "")
            pt[plat] = pt.get(plat, 0) + float(r.get("当前金额", "0") or "0")
        except (ValueError, TypeError):
            pass
    total_amt = sum(pt.values()) or 1
    plat_risk = [
        f"- {p}：¥{a / 10000:.0f}万（{a / total_amt * 100:.0f}%）"
        for p, a in sorted(pt.items(), key=lambda x: -x[1])[:3]
    ]

    # 同类重复 — 动态发现产品名中的高频词
    words: Counter[str] = Counter()
    name_map: dict = {}
    for r in products:
        name = r.get("\ufeff名称", r.get("名称", ""))
        try:
            amt = float(r.get("当前金额", "0") or "0")
        except (ValueError, TypeError):
            amt = 0
        for m in re.finditer(r"[\u4e00-\u9fff]{3,5}", name):
            w = m.group()
            words[w] += 1
            name_map.setdefault(w, []).append((name[:18], amt))

    skip = {
        "基金",
        "债券",
        "理财",
        "指数",
        "ETF",
        "联接",
        "增强",
        "混合",
        "持有",
        "发起式",
        "证券",
        "投资",
    }
    dupes = []
    top_words = [x for x in words.most_common(30) if x[1] >= 2][:10]
    for w, _count in top_words:
        if w in skip or any(s in w for s in skip):
            continue
        lst = sorted(name_map[w], key=lambda x: -x[1])
        total_kw = sum(a for _, a in lst)
        dupes.append(
            f"- {w}（{len(lst)}只，¥{total_kw / 10000:.1f}万）："
            + ", ".join(f"{n} ¥{a / 10000:.1f}万" for n, a in lst)
        )

    sections = []
    if loss:
        loss.sort(key=lambda x: -x[0])
        body = "\n".join(line for _, line in loss)
        sections.append(f"### 需关注 — 长期亏损（{len(loss)}只）\n{body}")
    if low_eff or big_fixed:
        items = low_eff + big_fixed
        seen: dict = {}
        for amt, line in items:
            key = line.split("|")[1].strip()
            if key not in seen or amt > seen[key][0]:
                seen[key] = (amt, line)
        deduped = sorted(seen.values(), key=lambda x: -x[0])
        body = "\n".join(line for _, line in deduped)
        sections.append(f"### 资金效率低（{len(deduped)}项）\n{body}")
    if volatile:
        volatile.sort(key=lambda x: -x[0])
        body = "\n".join(line for _, line in volatile)
        sections.append(f"### 高波动（{len(volatile)}只）\n{body}")
    if plat_risk or dupes:
        body = "\n".join(plat_risk + dupes)
        sections.append("### 结构问题\n" + body)
    return "\n\n".join(sections) if sections else "✅ 未发现明显问题。"


def build_efficiency(data: dict) -> str:
    eff = data.get("investment_efficiency", {})
    return (
        f"- 资金增值效率: {eff.get('capital_efficiency', '?')}\n"
        f"- 年化增长率: {eff.get('annual_growth_rate', '?')}"
    )


def build_time_groups(data: dict) -> str:
    groups = data.get("time_group_analysis", {}).get("groups", [])
    lines = [
        "| 分组 | 数量 | 金额 | 平均收益 | 持有时长 |",
        "|------|------|------|------|------|",
    ]
    for g in groups:
        amt = float(g.get("total_amount", 0))
        days = g.get("avg_holding_days", 0)
        days_str = f"{int(float(days))}天" if days else "-"
        lines.append(
            f"| {g.get('name', '?')} | {g.get('count', 0)}只 | "
            f"¥{amt / 10000:.1f}万 | {g.get('avg_return_rate', '?')} | {days_str} |"
        )
    return "\n".join(lines)


def get_market() -> tuple[str, str]:
    """返回 (行情日期, markdown文本)。行情日期取 money-csv 最新数据的日期。"""
    dirs = sorted(CSV_DIR.glob("money_csv_*"), reverse=True)
    if not dirs:
        return "", "（无数据）"
    with open(dirs[0] / "资产汇总-表格 1.csv") as f:
        rows = list(csv.DictReader(f))
    pv, cv = rows[-2], rows[-1]
    data_date = cv["日期"].replace(".", "")  # "2026.06.19" → "20260619"
    indices = [(name, name) for name in MARKET_INDICES]
    lines = [f"## 市场行情快照（截止 {cv['日期']}，非实时数据）", ""]
    for name, col in indices:
        p, c = float(pv[col]), float(cv[col])
        chg = (c - p) / abs(p) * 100 if p else 0
        lines.append(f"- {name}: {cv[col]} | {'+' if chg > 0 else ''}{chg:.2f}%")
    return data_date, "\n".join(lines)


# ── 主入口 ──


def main():
    data = load_json()
    products = load_products()
    data_date, market = get_market()
    # 用数据截止日期，不是脚本运行日期
    snapshot_date = f"{data_date[:4]}年{data_date[4:6]}月{data_date[6:8]}日"

    md = f"""# 投资周报分析

你是投资顾问团队。以下投资数据截止 {snapshot_date}（快照日期，非真实"本周"范围）。
请始终以 {snapshot_date} 作为分析的时间基准，不要推定数据覆盖了后续日期。

## 组合概览

{build_overview(data)}

## 自动检测问题

{detect_issues(products)}

## 资产配置

{build_allocation(data)}

## 风险分布

{build_risk(data)}

{market}

## 投资效率

{build_efficiency(data)}

## 时间分组

{build_time_groups(data)}

## 任务

⚠️ **重要：以上所有数据（组合概览、市场行情、收益排名）均为 {snapshot_date} 的快照，不代表当前实时状态。**
市场行情可能在快照日之后已发生变化，请勿将快照数据当作"本周最新"来分析。
调仓建议应基于快照反映的结构问题（如长期亏损、低效资金），而非假定行情延续。

1. **数据诊断**：基于快照数据，识别持仓中的结构问题（长期亏损、资金效率低、同类重复等）
2. **风险警示**：指出需要关注的风险点，标注数据截止日期
3. **调仓建议**：针对结构性问题提出具体操作建议，不预测市场方向
"""
    out = BASE / "output/portfolio_review_prompt.md"
    archive_dir = BASE / "output/archive"
    if "--print" in sys.argv:
        print(md)
    else:
        out.write_text(md, encoding="utf-8")
        # 按日期归档一份，供季度回顾用
        archive_dir.mkdir(exist_ok=True)
        # 使用 money-csv 数据的日期，而不是当前日期
        archive_file = archive_dir / f"weekly_{data_date}.md"
        archive_file.write_text(md, encoding="utf-8")
        print(f"✅ 已写入 {out} ({len(md)} 字符) → 已归档 {archive_file}")


if __name__ == "__main__":
    main()
