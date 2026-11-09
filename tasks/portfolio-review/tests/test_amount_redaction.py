"""金额脱敏回归测试。

覆盖三件事：
1. `PSE_REDACT_AMOUNTS=1` 时 `amount()` 只给占组合百分比，不给钱；
2. 外部文本里的历史金额会被 `scrub_amounts()` 抹掉；
3. run.py 能把 `[[AMT:12.5]]` 占位符按本机总额回填成真实金额，并把模型自作主张写的金额打码。

运行：`uv run python -m pytest tasks/portfolio-review/tests -q`
"""

import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK_DIR = HERE.parent


def _load(name: str, filename: str, redacted: bool):
    """按指定的脱敏开关重新加载模块（模块级常量在 import 时求值）。"""
    # 显式写 0/1：仓库 .env 本身可能开着脱敏，pop 掉会被 load_dotenv 重新填上
    os.environ["PSE_REDACT_AMOUNTS"] = "1" if redacted else "0"
    spec = importlib.util.spec_from_file_location(name, TASK_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_amount_is_percentage_when_redacted():
    prep = _load("prepare_redacted", "prepare.py", redacted=True)
    prep._TOTAL_ASSETS = 1_000_000
    assert prep.amount(50_000) == "5.0%"
    assert "¥" not in prep.amount(50_000)
    assert prep.paren_amount(50_000) == ""


def test_amount_keeps_cny_when_not_redacted():
    prep = _load("prepare_plain", "prepare.py", redacted=False)
    assert prep.amount(50_000) == "¥5.0万"
    assert prep.paren_amount(50_000) == "（¥5.0万）"


def test_size_tier_hides_scale():
    prep = _load("prepare_tier", "prepare.py", redacted=True)
    assert prep.size_tier(60_000) == "10万以下"
    assert prep.size_tier(300_000) == "10-50万"
    assert prep.size_tier(1_500_000) == "50-200万"
    assert prep.size_tier(5_000_000) == "200万以上"


def test_scrub_amounts_removes_historical_money():
    prep = _load("prepare_scrub", "prepare.py", redacted=True)
    text = "加仓黄金 ¥2.44万，合计 ¥5.94 万；另有 88 万元固收"
    scrubbed = prep.scrub_amounts(text)
    assert "¥" not in scrubbed
    assert "万元" not in scrubbed
    assert "加仓黄金" in scrubbed


def test_backfill_restores_placeholders_and_masks_guesses(tmp_path):
    run = _load("review_run", "run.py", redacted=True)
    out = tmp_path / "output"
    out.mkdir()
    (out / "portfolio_review_meta.json").write_text(
        json.dumps({"redacted": True, "total_assets": 1_000_000}), encoding="utf-8"
    )
    run.BASE = tmp_path

    text = "减仓至 [[AMT:12.5]]，另超配 ¥3.2万"
    result = run.backfill_amounts(text)
    assert result.startswith("减仓至 ¥12.5万"), result
    assert "[金额已按比例隐去]" in result
    assert "¥3.2万" not in result


def test_backfill_noop_when_not_redacted(tmp_path):
    run = _load("review_run_plain", "run.py", redacted=False)
    out = tmp_path / "output"
    out.mkdir()
    (out / "portfolio_review_meta.json").write_text(
        json.dumps({"redacted": False, "total_assets": 1_000_000}), encoding="utf-8"
    )
    run.BASE = tmp_path
    assert run.backfill_amounts("[[AMT:12.5]] 原样") == "[[AMT:12.5]] 原样"
