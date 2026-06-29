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
        check=True,
    )
    path = _latest_output_file(".json")
    return json.loads(path.read_text(encoding="utf-8"))


def get_csv_date() -> str:
    """返回最新 money-csv 数据日期（YYYYMMDD）。"""
    dirs = sorted(CSV_DIR.glob("money_csv_*"), reverse=True)
    if not dirs:
        return ""
    with open(dirs[0] / "资产汇总-表格 1.csv") as f:
        rows = list(csv.DictReader(f))
    return rows[-1]["日期"].replace(".", "")


def check_freshness(json_path: Path) -> None:
    """检查 JSON 数据日期是否与最新 CSV 一致，不一致则退出。"""
    import re

    m = re.search(r"(\d{8})", json_path.name)
    if not m:
        return
    json_date = m.group(1)
    csv_date = get_csv_date()
    if not csv_date:
        return
    if json_date < csv_date:
        print(
            f"❌ 数据过期: JSON 截止 {json_date}，CSV 已有 {csv_date} 的数据\n"
            f"   请先确保 asset-lens 的 make calculate 执行成功，再重试。"
        )
        sys.exit(1)


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


def _env_str(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# 房产列名（从 .env 读取，代码中不暴露具体名称）
PROP_CORE_VALUE = _env_str("PROP_CORE_VALUE")
PROP_CORE_ESTIMATE = _env_str("PROP_CORE_ESTIMATE")
PROP_CORE_DIFF = _env_str("PROP_CORE_DIFF")
PROP_CORE_UNITS = _env_str("PROP_CORE_UNITS")
PROP_CORE_PRICE = _env_str("PROP_CORE_PRICE")
PROP_CORE_LISTING = _env_str("PROP_CORE_LISTING")
PROP_DISTRICTS = _env_list("PROP_DISTRICTS") if os.getenv("PROP_DISTRICTS") else []
PROP_OLD = _env_list("PROP_OLD_VALUE") if os.getenv("PROP_OLD_VALUE") else []

# 市场数据列名
GOLD_GLD_COL = _env_str("GOLD_GLD_COL", "")
GOLD_DOMESTIC_COL = _env_str("GOLD_DOMESTIC_COL", "")
GOLD_EXCHANGE_COL = _env_str("GOLD_EXCHANGE_COL", "")


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
CUR_LOSS_THRESHOLD = _env_float("PSE_CUR_LOSS_THRESHOLD")
CUR_LOSS_MIN_AMOUNT = _env_int("PSE_CUR_LOSS_MIN_AMOUNT")


def detect_issues(products: list) -> str:
    loss = []
    low_eff = []
    volatile = []
    big_fixed = []
    cur_loss = []

    for r in products:
        name = r.get("\ufeff名称", r.get("名称", ""))
        typ = r.get("类型", "")
        plat = r.get("所属平台", "")
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
            line = f"- ¥{amt / 10000:.1f}万 | {name[:20]} | {plat} | {days}天 | 年化{ann:.1f}%"
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
        if real_val < CUR_LOSS_THRESHOLD and amt > CUR_LOSS_MIN_AMOUNT:
            line = f"- ¥{amt / 10000:.1f}万 | {name[:22]} | {plat} | {typ} | {days}天 | 实亏{real_val:+.1f}%（年化{ann:+.0f}%）"
            cur_loss.append((real_val, line))

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
    if cur_loss:
        cur_loss.sort()  # 从最亏到最不亏
        body = "\n".join(line for _, line in cur_loss)
        sections.append(
            f"### 当期亏损（{len(cur_loss)}只，收益 < {CUR_LOSS_THRESHOLD}%）\n{body}"
        )
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

    lines = [f"## 市场行情快照（截止 {cv['日期']}，非实时数据）", ""]

    # 从 MARKET_INDICES 配置动态读取，不再硬编码分组
    indices = MARKET_INDICES
    lines.append("| 指标 | 值 | 周变化 |")
    lines.append("|------|:---:|:-----:|")
    for name in indices:
        try:
            p, c = float(pv[name]), float(cv[name])
            chg = (c - p) / abs(p) * 100 if p else 0
            lines.append(
                f"| {name} | {cv[name]} | {'+' if chg > 0 else ''}{chg:.2f}% |"
            )
        except (ValueError, KeyError):
            pass

    # 额外指标（非行情指数但有用）
    extra_cols = []
    extra_cols = []
    extra_names = _env_list("MARKET_EXTRA") if os.getenv("MARKET_EXTRA") else []
    for name in extra_names:
        extra_cols.append((name, name))
    lines.append("")
    lines.append("| 指标 | 值 | 周变化 |")
    lines.append("|------|:---:|:-----:|")
    for name, col in extra_cols:
        try:
            p, c = float(pv[col]), float(cv[col])
            chg = (c - p) / abs(p) * 100 if p else 0
            lines.append(f"| {name} | {cv[col]} | {'+' if chg > 0 else ''}{chg:.2f}% |")
        except (ValueError, KeyError):
            pass

    return data_date, "\n".join(lines)


def build_gold_trend() -> str:
    """读取最近 8 周黄金价格趋势，返回简短 markdown。"""
    dirs = sorted(CSV_DIR.glob("money_csv_*"), reverse=True)
    if not dirs:
        return ""
    rows = []
    for d in dirs[:8]:
        f = d / "资产汇总-表格 1.csv"
        if not f.exists():
            continue
        with open(f) as fp:
            data = list(csv.DictReader(fp))
        if data:
            rows.append(data[-1])
    if len(rows) < 2:
        return ""

    gl = []
    for r in rows:
        try:
            gld = float(r.get(GOLD_GLD_COL, "0") or "0")
            gold = float(r.get(GOLD_DOMESTIC_COL, "0") or "0")
            ex_g = float(r.get(GOLD_EXCHANGE_COL, "0") or "0")
            gl.append((r["日期"], gld, gold, ex_g))
        except (ValueError, KeyError):
            continue
    gl.sort()

    if len(gl) < 2:
        return ""

    lines = ["## 黄金价格趋势（近 8 周）", ""]
    lines.append("| 日期 | GLD (美元) | 国内金价 | 兑换值 | 周变化 |")
    lines.append("|------|:---------:|:-------:|:-----:|:------:|")
    for i, (d, gld, gold, ex) in enumerate(gl):
        chg = ""
        if i > 0:
            prev = gl[i - 1][1]
            pct = (gld - prev) / prev * 100 if prev else 0
            chg = f"{'+' if pct > 0 else ''}{pct:.1f}%"
        lines.append(f"| {d} | {gld:.2f} | {gold:.0f} | {ex:.2f} | {chg} |")

    # 总结
    curr = gl[-1]
    peak_8w = max(g[1] for g in gl)
    trough_8w = min(g[1] for g in gl)
    chg_8w = (curr[1] - gl[0][1]) / gl[0][1] * 100
    chg_4w = (curr[1] - gl[-5][1]) / gl[-5][1] * 100 if len(gl) >= 5 else 0

    lines.append("")
    lines.append(f"- 近 4 周变化: **{chg_4w:+.1f}%**")
    lines.append(f"- 近 8 周变化: **{chg_8w:+.1f}%**")
    lines.append(f"- 8 周高/低: {peak_8w:.2f} / {trough_8w:.2f}")
    lines.append(
        f"- 当前距 8 周低点: **{(curr[1] - trough_8w) / trough_8w * 100:+.1f}%**"
    )
    return "\n".join(lines)


def build_property_trend() -> str:
    """读取最近 8 周房产数据，返回简短 markdown。列名从 .env 读取，代码不暴露具体名称。"""
    if not PROP_CORE_VALUE:
        return ""  # 未配置房产列名，跳过
    dirs = sorted(CSV_DIR.glob("money_csv_*"), reverse=True)
    if not dirs:
        return ""
    all_rows = []
    for d in dirs[:8]:
        f = d / "资产汇总-表格 1.csv"
        if not f.exists():
            continue
        with open(f) as fp:
            data = list(csv.DictReader(fp))
        if data:
            all_rows.append(data[-1])
    if len(all_rows) < 2:
        return ""

    # 核心住宅数据
    core = []
    for r in all_rows:
        try:
            val = float(r.get(PROP_CORE_VALUE, "0") or "0")
            est = (
                float(r.get(PROP_CORE_ESTIMATE, "0") or "0")
                if PROP_CORE_ESTIMATE
                else 0
            )
            diff = float(r.get(PROP_CORE_DIFF, "0") or "0") if PROP_CORE_DIFF else 0
            units = (
                int(float(r.get(PROP_CORE_UNITS, "0") or "0")) if PROP_CORE_UNITS else 0
            )
            price = float(r.get(PROP_CORE_PRICE, "0") or "0") if PROP_CORE_PRICE else 0
            listing = (
                float(r.get(PROP_CORE_LISTING, "0") or "0") if PROP_CORE_LISTING else 0
            )
            core.append((r["日期"], val, est, diff, units, price, listing))
        except (ValueError, KeyError):
            continue
    core.sort()

    # 周边区域
    districts_data = []
    for r in all_rows:
        try:
            row = [r["日期"]]
            for c in PROP_DISTRICTS:
                row.append(float(r.get(c, "0") or "0"))
            districts_data.append(tuple(row))
        except (ValueError, KeyError):
            continue
    districts_data.sort()

    # 旧资产
    old_data = []
    for r in all_rows:
        try:
            row = [r["日期"]]
            for c in PROP_OLD:
                row.append(float(r.get(c, "0") or "0"))
            old_data.append(tuple(row))
        except (ValueError, KeyError):
            continue
    old_data.sort()

    if len(core) < 2:
        return ""

    cur = core[-1]
    first = core[0]
    prev = core[-2]
    cur_d = districts_data[-1] if districts_data else None
    first_d = districts_data[0] if districts_data else None
    cur_o = old_data[-1] if old_data else None
    first_o = old_data[0] if old_data else None

    lines = ["## 房产快照", ""]

    # 核心住宅
    lines.append("### 核心住宅")
    parts = []
    if cur[1]:
        parts.append(f"当前价值: **¥{cur[1]:.1f}万**")
    if cur[2]:
        parts.append(f"估价: ¥{cur[2]:.1f}万")
    if PROP_CORE_DIFF:
        parts.append(f"差价: ¥{cur[3]:.1f}万")
    lines.append("- " + " | ".join(parts))
    extra = []
    if PROP_CORE_LISTING and cur[6]:
        extra.append(f"挂牌: ¥{cur[6]:.0f}/m²")
    if PROP_CORE_PRICE and cur[5]:
        extra.append(f"成交: ¥{cur[5]:.0f}/m²")
    if PROP_CORE_UNITS and cur[4]:
        extra.append(f"在售: {cur[4]} 套（周 {cur[4] - prev[4]:+d}）")
    if extra:
        lines.append("- " + " | ".join(extra))
    val_8w = (cur[1] - first[1]) / first[1] * 100
    lines.append(f"- 8 周价值变化: **{val_8w:+.1f}%**")

    # 周边区域
    if cur_d and first_d and PROP_DISTRICTS:
        lines.append("")
        lines.append("### 周边区域")
        lines.append("| 区域 | 最新 | 8周前 | 变化 |")
        lines.append("|------|:---:|:---:|:---:|")
        for i, label in enumerate(PROP_DISTRICTS):
            c_val = cur_d[i + 1]
            f_val = first_d[i + 1]
            chg = (c_val - f_val) / f_val * 100 if f_val else 0
            lines.append(f"| {label} | {c_val:.2f} | {f_val:.2f} | {chg:+.1f}% |")

    # 旧资产
    if cur_o and first_o and PROP_OLD:
        lines.append("")
        lines.append("### 旧资产")
        lines.append("| 名称 | 最新 | 8周前 | 变化 |")
        lines.append("|------|:---:|:---:|:---:|")
        for i, label in enumerate(PROP_OLD):
            c_val = cur_o[i + 1]
            f_val = first_o[i + 1]
            chg = (c_val - f_val) / f_val * 100 if f_val else 0
            lines.append(f"| {label} | {c_val:.2f} | {f_val:.2f} | {chg:+.1f}% |")

    # 综合判断
    if PROP_CORE_DIFF and cur[3] < -15:
        signal = "⚠️ 估价显著低于价值，关注市场下行"
    elif PROP_CORE_DIFF and cur[3] > 10:
        signal = "✅ 估价高于价值，资产溢价"
    else:
        signal = "➡️ 估价与价值接近，市场平稳"
    lines.append(f"\n{signal}")

    return "\n".join(lines)


def build_exchange_rates() -> str:
    """提取最新汇率数据，返回简短 markdown。"""
    dirs = sorted(CSV_DIR.glob("money_csv_*"), reverse=True)
    if not dirs:
        return ""
    with open(dirs[0] / "资产汇总-表格 1.csv") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return ""
    r = rows[-1]
    try:
        usd = float(r.get("美元汇率", "0") or "1")
        hkd = float(r.get("港元汇率", "0") or "1")
    except (ValueError, KeyError):
        return ""
    lines = ["## 汇率快照", ""]
    lines.append(f"- 美元/人民币: {usd:.4f}")
    lines.append(f"- 港元/人民币: {hkd:.4f}")
    return "\n".join(lines)


def build_dca_review(products: list) -> str:
    """识别定投产品并列出当前收益状态。"""
    dca_products = []
    for r in products:
        name = r.get("\ufeff名称", r.get("名称", ""))
        typ = r.get("类型", "")
        if "定投" not in typ:
            continue
        try:
            amt = float(r.get("当前金额", "0") or "0")
            real_val = float(r.get("实际收益率(%)", "0") or "0")
            days = int(r.get("投资天数", "0") or "0")
            ann = float(r.get("年化收益率(%)", "0") or "0")
            dca_products.append((name, amt, real_val, days, ann))
        except (ValueError, TypeError):
            continue
    if not dca_products:
        return ""

    dca_products.sort(key=lambda x: -x[1])
    lines = ["## 定投审查", ""]
    for name, amt, real_val, days, ann in dca_products:
        status = "✅" if real_val > 0 else "⚠️" if real_val > -5 else "🔴"
        lines.append(
            f"- {status} {name[:25]} | ¥{amt:.0f} | {days}天 | 实{real_val:+.1f}% | 年化{ann:+.0f}%"
        )
    return "\n".join(lines)


def build_c_class_alert(products: list) -> str:
    """检测 C 类份额长持，计算费率差异。"""
    alerts = []
    for r in products:
        name = r.get("\ufeff名称", r.get("名称", ""))
        if "C" not in name and "Y" not in name:
            continue
        try:
            days = int(r.get("投资天数", "0") or "0")
            amt = float(r.get("当前金额", "0") or "0")
        except (ValueError, TypeError):
            continue
        if days > 180 and amt > 1000:
            extra = amt * 0.004
            alerts.append((name, days, amt, extra))
    if not alerts:
        return ""
    alerts.sort(key=lambda x: -x[2])
    lines = ["## C类份额费率提醒", ""]
    for name, days, amt, extra in alerts:
        lines.append(f"- {name[:25]} | {days}天 | ¥{amt:.0f} | 预估年多付 ¥{extra:.0f}")
    return "\n".join(lines)


# ── 主入口 ──


def main():
    data = load_json()
    products = load_products()
    check_freshness(_latest_output_file(".json"))
    data_date, market = get_market()
    gold_trend = build_gold_trend()
    property_trend = build_property_trend()
    exchange_rates = build_exchange_rates()
    dca_review = build_dca_review(products)
    c_class_alert = build_c_class_alert(products)
    snapshot_date = f"{data_date[:4]}年{data_date[4:6]}月{data_date[6:8]}日"

    md = f"""# 投资周报分析

你是投资顾问团队。以下投资数据截止 {snapshot_date}（快照日期，非真实"本周"范围）。
请始终以 {snapshot_date} 作为分析的时间基准，不要推定数据覆盖了后续日期。

## 组合概览

{build_overview(data)}

## 自动检测问题

{detect_issues(products)}

{gold_trend}

{property_trend}

{exchange_rates}

{dca_review}

{c_class_alert}

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
