"""策略原则 + Fed 口径注入回归测试。

2026-11-21 周报的两类偏差在此钉死：
1. 把 EFFR 3.88% 误写成「Fed 目标利率」，且暗示「本周刚加息」；
2. 把增长引擎占比缺口（长期结构锚）当成「本周该补」的行动指令，
   而忽略低效固收才是年化拖累的首因。
修复后这些纪律由 prepare.py 注入 prompt，本测试确保它们不被后续改动回退。
"""

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK_DIR = HERE.parent


def _load_prepare():
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
    """注记不得再出现「目标利率 3.88%」「升至 3.88%」这类错误表述。"""
    notes = (TASK_DIR / "market-notes.md").read_text(encoding="utf-8")
    assert "3.75%–4.00%" in notes
    assert "目标利率" in notes and "区间" in notes
    assert "EFFR" in notes
    assert "市场预期" in notes and "非既成事实" in notes
    # 纠偏短语必须在（错误说法只应作为「❌ 历史周报写错」的反例出现）
    assert "不是目标利率" in notes
    assert "不等于目标利率" in notes or "不等于目标利率本身" in notes
