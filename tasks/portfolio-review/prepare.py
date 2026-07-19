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
# 统一从项目根解析相对路径，与 prepare_market.py 行为一致
_project_root = BASE.parent.parent
ASSET_LENS = (_project_root / ASSET_LENS_DIR).resolve() if not Path(ASSET_LENS_DIR).is_absolute() else Path(ASSET_LENS_DIR)
CSV_DIR = (_project_root / MONEY_CSV_DIR).resolve() if not Path(MONEY_CSV_DIR).is_absolute() else Path(MONEY_CSV_DIR)

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


def _get_exchange_rates() -> tuple[float, float]:
    """从 money-csv 最后一行提取美元/港元汇率。"""
    dirs = sorted(CSV_DIR.glob("money_csv_*"), reverse=True)
    if not dirs:
        return 1.0, 1.0
    f = dirs[0] / "资产汇总-表格 1.csv"
    if not f.exists():
        return 1.0, 1.0
    with open(f, encoding="utf-8-sig") as fp:
        rows = list(csv.DictReader(fp))
    if not rows:
        return 1.0, 1.0
    last = rows[-1]
    try:
        usd = float(str(last.get("美元汇率", "1")).replace("%", ""))
        hkd = float(str(last.get("港元汇率", "1")).replace("%", ""))
    except (ValueError, TypeError):
        return 1.0, 1.0
    return usd, hkd


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


def build_allocation(data: dict, products: list = None) -> str:
    """输出资产配置，与 build_role_breakdown 保持一致的黄金修正。

    type_distribution 按产品「类型」字段聚合，但华安黄金ETF联接A 类型是"基金"实际是黄金。
    这里同步修正：将名称含黄金关键词的基金金额从"基金"移到"黄金"，避免两个数据源冲突。
    """
    items = data.get("type_distribution", {})
    # 先复制一份，避免修改原始 data
    adjusted = {}
    for name, info in items.items():
        adjusted[name] = {"percentage": info.get("percentage", "?"), "total_value": float(info.get("total_value", 0))}

    # 修正：名称含黄金关键词的基金从"基金"移到"黄金"
    if products:
        gold_keywords = set(os.getenv("GOLD_KEYWORDS", "黄金,gold").split(","))
        gold_types = set(os.getenv("GOLD_TYPES", "黄金").split(","))
        growth_types = set(os.getenv("GROWTH_TYPES", "基金,美元基金,美元基金（美元）,美股,定投基金,ETF,个股").split(","))
        gold_fund_amt = 0.0
        for r in products:
            typ = r.get("类型", "")
            name = r.get("\ufeff名称", r.get("名称", ""))
            if typ in growth_types and any(kw in name for kw in gold_keywords):
                try:
                    gold_fund_amt += float(r.get("当前金额", "0") or "0")
                except (ValueError, TypeError):
                    continue
        if gold_fund_amt > 0 and "基金" in adjusted and "黄金" in adjusted:
            # 从基金扣除，加到黄金
            adjusted["基金"]["total_value"] -= gold_fund_amt
            adjusted["黄金"]["total_value"] += gold_fund_amt
            # 重新计算百分比
            total_all = sum(v["total_value"] for v in adjusted.values())
            if total_all > 0:
                for v in adjusted.values():
                    v["percentage"] = f"{v['total_value'] / total_all * 100:.2f}%"

    lines = []
    sorted_items = sorted(
        adjusted.items(),
        key=lambda x: x[1]["total_value"],
        reverse=True,
    )
    for _name, info in sorted_items:
        pct = info["percentage"]
        amt = info["total_value"]
        if amt >= 10000:
            lines.append(f"  {_name}: {pct}（{amt / 10000:.1f}万元）")
        else:
            lines.append(f"  {_name}: {pct}（{amt:.0f}元）")
    return "\n".join(lines)


def build_role_breakdown(data: dict, products: list) -> str:
    """按资产角色分层计算占比，供 Specialist 引用（避免用风险分布替代）。

    注意：type_distribution 按产品「类型」字段聚合，但某些产品类型与资产角色不一致
    （如华安黄金ETF联接A 类型是"基金"但实际是黄金持仓）。
    因此在产品级别用关键词重新分类：名称含黄金关键词的基金 → 归入黄金而非增长引擎。
    """
    items = data.get("type_distribution", {})
    growth_types = set(os.getenv("GROWTH_TYPES", "基金,美元基金,美元基金（美元）,美股,定投基金,ETF,个股").split(","))
    defense_types = set(os.getenv("DEFENSE_TYPES", "债券,特别国债,公募固收,高端理财").split(","))
    liquid_types = set(os.getenv("LIQUID_TYPES", "理财,货币,券商理财").split(","))
    gold_types = set(os.getenv("GOLD_TYPES", "黄金").split(","))
    gold_keywords = set(os.getenv("GOLD_KEYWORDS", "黄金,gold").split(","))

    # 先按 type_distribution 聚合
    growth_pct, growth_amt = 0.0, 0.0
    defense_pct, defense_amt = 0.0, 0.0
    liquid_pct, liquid_amt = 0.0, 0.0
    gold_pct, gold_amt = 0.0, 0.0

    for name, info in items.items():
        pct = float(str(info.get("percentage", "0%")).rstrip("%"))
        amt = float(info.get("total_value", 0))
        if name in growth_types:
            growth_pct += pct
            growth_amt += amt
        elif name in defense_types:
            defense_pct += pct
            defense_amt += amt
        elif name in liquid_types:
            liquid_pct += pct
            liquid_amt += amt
        elif name in gold_types:
            gold_pct += pct
            gold_amt += amt

    # 修正：名称含黄金关键词的产品从增长引擎移到黄金
    gold_fund_amt = 0.0
    for r in products:
        typ = r.get("类型", "")
        name = r.get("\ufeff名称", r.get("名称", ""))
        if typ in growth_types and any(kw in name for kw in gold_keywords):
            try:
                amt = float(r.get("当前金额", "0") or "0")
            except (ValueError, TypeError):
                continue
            gold_fund_amt += amt

    if gold_fund_amt > 0:
        # 从增长引擎扣除，加到黄金
        total_assets = growth_amt + defense_amt + liquid_amt + gold_amt
        if total_assets > 0:
            shift_pct = gold_fund_amt / total_assets * 100
        else:
            shift_pct = 0.0
        growth_amt -= gold_fund_amt
        growth_pct -= shift_pct
        gold_amt += gold_fund_amt
        gold_pct += shift_pct

    # ── 形式视角（原始四行，保留不变）──
    formal_lines = (
        f"  增长引擎: {growth_pct:.2f}%（{growth_amt / 10000:.1f}万元）\n"
        f"  防御底仓: {defense_pct:.2f}%（{defense_amt / 10000:.1f}万元）\n"
        f"  流动性储备: {liquid_pct:.2f}%（{liquid_amt / 10000:.1f}万元）\n"
        f"  黄金: {gold_pct:.2f}%（{gold_amt / 10000:.1f}万元）"
    )

    # ── 功能视角：将 DEFENSIVE_LIQUID_TYPES 从流动性移入防御 ──
    defensive_liquid_types = set(
        os.getenv("DEFENSIVE_LIQUID_TYPES", "理财,高端理财").split(",")
    )
    # 只取同时存在于 liquid_types 中的类型（避免误移动已在防御中的高端理财）
    dl_names = defensive_liquid_types & liquid_types

    dl_pct, dl_amt = 0.0, 0.0
    for name, info in items.items():
        if name in dl_names:
            pct = float(str(info.get("percentage", "0%")).rstrip("%"))
            amt = float(info.get("total_value", 0))
            dl_pct += pct
            dl_amt += amt

    func_lines = ""
    if dl_amt > 0:
        func_defense_pct = defense_pct + dl_pct
        func_defense_amt = defense_amt + dl_amt
        func_liquid_pct = liquid_pct - dl_pct
        func_liquid_amt = liquid_amt - dl_amt
        dl_display = "、".join(sorted(dl_names))
        func_lines = (
            f"\n\n  ▶ 功能视角（{dl_display}视为防御）：\n"
            f"    增长引擎: {growth_pct:.2f}%（{growth_amt / 10000:.1f}万元）\n"
            f"    防御（含低波理财）: {func_defense_pct:.2f}%（{func_defense_amt / 10000:.1f}万元）\n"
            f"    纯流动性: {func_liquid_pct:.2f}%（{func_liquid_amt / 10000:.1f}万元）\n"
            f"    黄金: {gold_pct:.2f}%（{gold_amt / 10000:.1f}万元）\n"
            f"    ⚠️ {dl_display}为低波固收产品（90+天持有期，本金安全），功能上等价防御底仓。\n"
            f"    分析配置比例是否合理时，必须以功能视角为准；形式视角仅供合规参考。"
        )

    return formal_lines + func_lines


def build_growth_details(products: list) -> str:
    """列出增长引擎每只产品的关键数据，供 Specialist 逐只分析加减仓。"""
    growth_types = {"基金", "美元基金", "美元基金（美元）", "美股", "定投基金", "ETF", "个股"}
    gold_keywords = set(os.getenv("GOLD_KEYWORDS", "黄金,gold").split(","))
    skip_keywords = set(os.getenv("GROWTH_SKIP_KEYWORDS", "").split(",")) if os.getenv("GROWTH_SKIP_KEYWORDS") else set()
    skip_platforms = set(os.getenv("GROWTH_SKIP_PLATFORMS", "").split(",")) if os.getenv("GROWTH_SKIP_PLATFORMS") else set()
    usd_rate, hkd_rate = _get_exchange_rates()
    lines = ["| 名称 | 平台 | 金额 | 天数 | 实亏 | 年化 |", "|------|------|:---:|:---:|:---:|:---:|"]
    for r in products:
        typ = r.get("类型", "")
        if typ not in growth_types:
            continue
        name = r.get("\ufeff名称", r.get("名称", ""))
        # 排除黄金类基金（已归入黄金持仓明细）
        if any(kw in name for kw in gold_keywords):
            continue
        if any(kw in name for kw in skip_keywords):
            continue
        plat = r.get("所属平台", "")
        if plat in skip_platforms:  # 不展示的平台
            continue
        try:
            amt = float(r.get("当前金额", "0") or "0")
            # 汇率转换：根据平台选择对应汇率
            usd_platforms = set(os.getenv("GROWTH_USD_PLATFORMS", "").split(",")) if os.getenv("GROWTH_USD_PLATFORMS") else set()
            hkd_platforms = set(os.getenv("GROWTH_HKD_PLATFORMS", "").split(",")) if os.getenv("GROWTH_HKD_PLATFORMS") else set()
            if "美元" in typ or plat in usd_platforms:
                amt *= usd_rate
            elif plat in hkd_platforms:
                amt *= hkd_rate
            days = int(r.get("投资天数", "0") or "0")
            real_val = float(r.get("实际收益率(%)", "0") or "0")
            ann = float(r.get("年化收益率(%)", "0") or "0")
        except (ValueError, TypeError):
            continue
        lines.append(
            f"| {name} | {plat} | ¥{amt/10000:.2f}万 | {days}天 | {real_val:+.1f}% | {ann:+.0f}% |"
        )
    return "\n".join(lines) if len(lines) > 2 else ""


def build_gold_details(products: list) -> str:
    """列出黄金持仓每只产品的关键数据，供 Specialist 逐只分析加减仓。

    黄金是对冲仓位，独立于增长引擎和防御底仓，必须逐只覆盖。
    包括：黄金ETF联接、银行黄金活期/定期、实物黄金等。
    也包括类型为"基金"但名称含黄金关键词的产品（如华安黄金ETF联接A）。
    """
    gold_types = set(os.getenv("GOLD_TYPES", "黄金").split(","))
    gold_keywords = set(os.getenv("GOLD_KEYWORDS", "黄金,gold").split(","))
    lines = ["| 名称 | 平台 | 金额 | 天数 | 实亏 | 年化 |", "|------|------|:---:|:---:|:---:|:---:|"]
    total = 0.0
    for r in products:
        typ = r.get("类型", "")
        name = r.get("\ufeff名称", r.get("名称", ""))
        # 类型为黄金，或类型为基金但名称含黄金关键词
        is_gold_type = typ in gold_types
        is_gold_name = any(kw in name for kw in gold_keywords)
        if not (is_gold_type or is_gold_name):
            continue
        plat = r.get("所属平台", "")
        try:
            amt = float(r.get("当前金额", "0") or "0")
            days = int(r.get("投资天数", "0") or "0")
            real_val = float(r.get("实际收益率(%)", "0") or "0")
            ann = float(r.get("年化收益率(%)", "0") or "0")
            total += amt
        except (ValueError, TypeError):
            continue
        lines.append(
            f"| {name[:22]} | {plat} | ¥{amt/10000:.2f}万 | {days}天 | {real_val:+.1f}% | {ann:+.0f}% |"
        )
    if len(lines) <= 2:
        return ""
    lines.append(f"| **合计** | | **¥{total/10000:.2f}万** | | | |")
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

# 固收类产品类型，报告中只聚合不逐只列出
FIXED_INCOME_TYPES = set(os.getenv("FIXED_INCOME_TYPES", "理财,债券,高端理财,货币,券商理财,短债").split(","))


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
            low_eff.append((amt, typ, line))
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
            big_fixed.append((amt, typ, line))
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
    # 过滤固收类产品名模式：理财/债券的碎片化是常态，不视为重复
    words: Counter[str] = Counter()
    name_map: dict = {}
    for r in products:
        name = r.get("\ufeff名称", r.get("名称", ""))
        typ = r.get("类型", "")
        if typ in FIXED_INCOME_TYPES:  # 理财/债券等不参与重复检测
            continue
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
        sections.append(f"### 需关注 — 长期持有且累计亏损（{len(loss)}只）\n{body}")
    if cur_loss:
        cur_loss.sort()  # 从最亏到最不亏
        body = "\n".join(line for _, line in cur_loss)
        sections.append(
            f"### 累计亏损（持有以来实亏 < {CUR_LOSS_THRESHOLD}%，非本周跌幅）\n{body}"
        )
    if low_eff or big_fixed:
        items = low_eff + big_fixed
        # 分离固收类（理财/债券）和其他产品
        fixed_income = []
        others = []
        for amt, typ, line in items:
            if typ in FIXED_INCOME_TYPES:
                fixed_income.append((amt, typ, line))
            else:
                others.append((amt, typ, line))
        # 固收类聚合为一行摘要
        sections_parts = []
        if fixed_income:
            total_amt = sum(amt for amt, _, _ in fixed_income)
            annual_values = []
            for _, _, l in fixed_income:
                m = re.search(r"年化([\d.]+)%", l)
                if m:
                    annual_values.append(float(m.group(1)))
            min_ret = min(annual_values) if annual_values else 0.0
            max_ret = max(annual_values) if annual_values else 0.0
            sections_parts.append(
                f"- 💰 低效固收：¥{total_amt/10000:.0f}万（{len(fixed_income)}只，年化{min_ret:.1f}%-{max_ret:.1f}%），明细见原始数据"
            )
        # 其他产品逐只列出
        seen: dict = {}
        for amt, typ, line in others:
            key = line.split("|")[1].strip()
            if key not in seen or amt > seen[key][0]:
                seen[key] = (amt, line)
        deduped = sorted(seen.values(), key=lambda x: -x[0])
        sections_parts.extend(line for _, line in deduped)
        body = "\n".join(sections_parts)
        sections.append(f"### 资金效率低（{len(items)}项）\n{body}")
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


def get_market() -> tuple[str, str, dict, dict]:
    """返回 (行情日期, markdown文本, 上一行数据, 当前行数据)。行情日期取 money-csv 最新数据的日期。"""
    dirs = sorted(CSV_DIR.glob("money_csv_*"), reverse=True)
    if not dirs:
        return "", "（无数据）", {}, {}
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
    extra_names = _env_list("MARKET_EXTRA") if os.getenv("MARKET_EXTRA") else []
    for name in extra_names:
        extra_cols.append((name, name))
    lines.append("")
    lines.append("| 指标 | 值 | 周变化 |")
    lines.append("|------|:---:|:-----:|")
    for name, col in extra_cols:
        try:
            p_raw, c_raw = str(pv[col]), str(cv[col])
            p, c = float(p_raw.replace("%", "")), float(c_raw.replace("%", ""))
            chg = (c - p) / abs(p) * 100 if p else 0
            lines.append(f"| {name} | {cv[col]} | {'+' if chg > 0 else ''}{chg:.2f}% |")
        except (ValueError, KeyError):
            pass

    return data_date, "\n".join(lines), pv, cv


def build_market_context(prev: dict, cv: dict) -> str:
    """基于周涨跌幅自动生成市场事件摘要，帮助 LLM 理解数字背后的市场环境。"""
    alerts = []
    crash_indices = []  # 单周跌幅 > 3% 的指数
    surge_indices = []  # 单周涨幅 > 3% 的指数

    for name in MARKET_INDICES:
        try:
            p, c = float(prev[name]), float(cv[name])
            chg = (c - p) / abs(p) * 100 if p else 0
            if chg <= -5:
                crash_indices.append((name, chg))
            elif chg <= -3:
                crash_indices.append((name, chg))
            if chg >= 5:
                surge_indices.append((name, chg))
            elif chg >= 3:
                surge_indices.append((name, chg))
        except (ValueError, KeyError):
            pass

    # VIX / 恐慌指标
    extra_names = _env_list("MARKET_EXTRA") if os.getenv("MARKET_EXTRA") else []
    vix_val = None
    vix_chg = None
    for name in extra_names:
        try:
            c_raw = str(cv.get(name, "0"))
            p_raw = str(prev.get(name, "0"))
            c = float(c_raw.replace("%", ""))
            p = float(p_raw.replace("%", ""))
            chg = (c - p) / abs(p) * 100 if p else 0
            if "恐慌" in name or "VIX" in name or "VXX" in name:
                vix_val = c
                vix_chg = chg
        except (ValueError, KeyError):
            pass

    # 判断市场环境
    if crash_indices:
        names_str = "、".join(f"{n}({chg:+.1f}%)" for n, chg in crash_indices)
        alerts.append(f"⚠️ **本周市场大幅下跌**：{names_str}")
        if len(crash_indices) >= 3:
            alerts.append("🔴 多指数同步暴跌，市场处于**恐慌**状态，建议适用恐慌档（VIX>25或周跌幅>5%的指数≥3个）")
        elif vix_val and vix_val >= 20:
            alerts.append(f"🟡 市场波动加剧（VIX={vix_val:.1f}），接近恐慌阈值，建议审慎加仓，分批入场")

    if surge_indices:
        names_str = "、".join(f"{n}({chg:+.1f}%)" for n, chg in surge_indices)
        alerts.append(f"📈 **本周市场大幅上涨**：{names_str}")

    if vix_val:
        if vix_val >= 25:
            alerts.append(f"🔴 VIX={vix_val:.1f} 已进入恐慌区间（>25），适用恐慌档，暂缓增长引擎加仓")
        elif vix_val >= 20:
            alerts.append(f"🟡 VIX={vix_val:.1f} 接近恐慌阈值（20-25），若配合大幅下跌应视同恐慌环境处理")
        elif vix_val < 15:
            alerts.append(f"🟢 VIX={vix_val:.1f} 处于贪婪区间（<15），市场情绪乐观但需警惕追高")

    if not alerts:
        return ""

    return "## ⚡ 本周市场事件（自动检测）\n\n" + "\n".join(f"- {a}" for a in alerts)


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
        typ = r.get("类型", "")
        if "C" not in name and "Y" not in name:
            continue
        if typ in FIXED_INCOME_TYPES:  # 理财/债券 C 类不逐只列出
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
    data_date, market, prev_row, curr_row = get_market()
    gold_trend = build_gold_trend()
    market_context = build_market_context(prev_row, curr_row)
    property_trend = build_property_trend()
    exchange_rates = build_exchange_rates()
    dca_review = build_dca_review(products)
    c_class_alert = build_c_class_alert(products)
    growth_details = build_growth_details(products)
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

{build_allocation(data, products)}

## 角色分层占比

{build_role_breakdown(data, products)}

## 增长引擎持仓明细（逐只分析加减仓）

{build_growth_details(products)}

## 黄金持仓明细（逐只覆盖，对冲仓位不止损）

{build_gold_details(products)}

## 风险分布

{build_risk(data)}

{market}

{market_context}

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
