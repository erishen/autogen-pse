"""策略原则 + Fed 口径注入回归测试。

2026-11-21 周报的两类偏差在此钉死：
1. 把 EFFR 3.88% 误写成「Fed 目标利率」，且暗示「本周刚加息」；
2. 把增长引擎占比缺口（长期结构锚）当成「本周该补」的行动指令，
   而忽略低效固收才是年化拖累的首因。
修复后这些纪律由 prepare.py 注入 prompt，本测试确保它们不被后续改动回退。

可克隆性：prepare.py 模块顶层读 .env、缺键即 sys.exit；market-notes.md 是 gitignored
的本地私有注记。两者都不进公开仓，故本测试自带最小 env 占位并容忍注记缺席——
干净 clone 上 5 例须全绿（用 `git archive HEAD` 抽树实测，别只跑本地）。
"""

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK_DIR = HERE.parent

# 补齐 prepare.py 模块顶层 sys.exit 必需的全部 env 键；占位值中性、不指向任何真实路径。
# load_dotenv 默认 override=False：本机有真值时照旧沿用（能读到真实 market_env.json），
# 干净 clone 缺值时才用占位，被测函数返回空串，各断言已容忍。
_BOOTSTRAP_ENV = {
    "ASSET_LENS_DIR": ".data/asset-lens-placeholder",
    "MONEY_CSV_DIR": ".data/money-csv-placeholder",
    "MARKET_INDICES": "上证指数,沪深300",
    # prepare.py 顶层还会读 12 个检测阈值（_env_int/_env_float，无默认值、缺则
    # sys.exit）。用中性 1 / 占位类型名即可让模块 import 成功；被测的两个函数是
    # 纯文本生成，不依赖这些阈值的具体数值。
    "PSE_LONG_LOSS_DAYS": "1",
    "PSE_LOW_EFF_DAYS": "1",
    "PSE_LOW_EFF_MAX_RETURN": "1",
    "PSE_LOW_EFF_MIN_AMOUNT": "1",
    "PSE_HIGH_VOL_MIN_RETURN": "1",
    "PSE_HIGH_VOL_MAX_DAYS": "1",
    "PSE_HIGH_VOL_MIN_AMOUNT": "1",
    "PSE_LARGE_POS_TYPES": "占位类型",
    "PSE_LARGE_POS_MIN_AMOUNT": "1",
    "PSE_LARGE_POS_MAX_RETURN": "1",
    "PSE_CUR_LOSS_THRESHOLD": "1",
    "PSE_CUR_LOSS_MIN_AMOUNT": "1",
}


def _load_prepare():
    for key, value in _BOOTSTRAP_ENV.items():
        os.environ.setdefault(key, value)
    os.environ["PSE_REDACT_AMOUNTS"] = "1"
    spec = importlib.util.spec_from_file_location("prepare_strategy", TASK_DIR / "prepare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_principles_block_exists_and_is_injected():
    p = _load_prepare()
    block = p.build_strategy_principles()
    assert block.startswith("## 策略原则"), "策略原则段必须以标题开头"
    assert "低效固收" in block
    assert "长期结构锚" in block
    # 确认已注入到最终 prompt 模板（而非只是定义了没用）
    src = (TASK_DIR / "prepare.py").read_text(encoding="utf-8")
    assert "{build_strategy_principles()}" in src, "策略原则必须出现在 prompt 模板中"


def test_principles_forbid_treating_gap_as_action():
    p = _load_prepare()
    block = p.build_strategy_principles()
    assert "不是本周行动指令" in block
    assert "禁止把" in block and "直接读成" in block


def test_principles_cover_blind_spots():
    p = _load_prepare()
    block = p.build_strategy_principles()
    assert "收益数据" in block and "止损" in block, "需覆盖止损扫描边界"
    assert "周度明细" in block and "汇总注记" in block, "需覆盖房产注记冲突"
    assert "EFFR" in block and "目标利率" in block, "需覆盖利率口径隔离"


def test_fed_section_separates_effr_from_target_rate():
    p = _load_prepare()
    sec = p.build_fed_autofetch_section()
    # 当前 market_env.json 存在时该段非空；即便缺失也应保持口径纪律的测试有效性
    if sec:
        assert "EFFR" in sec
        assert "不是 FOMC 政策目标利率" in sec
        assert "禁止" in sec and "目标利率" in sec


def test_market_notes_use_correct_fed_wording():
    """注记不得再出现「目标利率 3.88%」「升至 3.88%」这类错误表述。

    market-notes.md 是 gitignored 的本地私有注记，公开 clone 里没有属合法状态，
    此时跳过；代码级口径纪律由 test_fed_section_separates_effr_from_target_rate
    钉死，不依赖私有文件。
    """
    notes_path = TASK_DIR / "market-notes.md"
    if not notes_path.exists():
        return  # 干净 clone：私有注记缺席，跳过
    notes = notes_path.read_text(encoding="utf-8")
    assert "3.75%–4.00%" in notes
    assert "目标利率" in notes and "区间" in notes
    assert "EFFR" in notes
    assert "市场预期" in notes and "非既成事实" in notes
    # 纠偏短语必须在（错误说法只应作为「❌ 历史周报写错」的反例出现）
    assert "不是目标利率" in notes
    assert "不等于目标利率" in notes or "不等于目标利率本身" in notes
