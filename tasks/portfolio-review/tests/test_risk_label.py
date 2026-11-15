"""口径校验回归测试。

2026-11-15 的周报把「增长引擎 12.95%」写成了「中高风险资产占 12.95%」，
而快照 risk_distribution 的中高 + 高合计是 9.06%，报告自身后文也写的 9.06%。
这里把「权威值比对 + 标注」的行为钉死。
"""

import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK_DIR = HERE.parent


def _load(name: str, filename: str, redacted: bool = True):
    os.environ["PSE_REDACT_AMOUNTS"] = "1" if redacted else "0"
    spec = importlib.util.spec_from_file_location(name, TASK_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mismatch_is_detected_on_the_real_sentence():
    run = _load("review_risk_detect", "run.py")
    text = "- 🔴 **结构失衡是首要矛盾** | 中高风险资产占 **12.95%**（中性档 30–40%）"
    bad = run._risk_label_mismatches(text, 9.06)
    assert bad, "12.95% 冒充中高风险必须被检出"
    assert "12.95" in bad[0]


def test_correct_value_is_not_flagged():
    run = _load("review_risk_ok", "run.py")
    text = "中高风险合计 9.06%（中高 5.88% + 高 3.18%）"
    assert run._risk_label_mismatches(text, 9.06) == []


def test_annotate_appends_warning_only_when_meta_disagrees(tmp_path):
    run = _load("review_risk_annotate", "run.py")
    out = tmp_path / "output"
    out.mkdir()
    run.BASE = tmp_path
    body = "中高风险资产占 12.95%，防御 66.59%"

    # 没有 meta：原样返回，不臆造警示
    assert run.annotate_risk_label(body) == body

    (out / "portfolio_review_meta.json").write_text(
        json.dumps({"redacted": True, "risk_mid_high_pct": 9.06}), encoding="utf-8"
    )
    annotated = run.annotate_risk_label(body)
    assert annotated.startswith(body)
    assert "口径校验未通过" in annotated
    assert "9.06%" in annotated
    assert "增长引擎" in annotated

    # 口径一致时不加噪声
    ok = run.annotate_risk_label("中高风险合计 9.06%")
    assert "口径校验未通过" not in ok


def test_prepare_computes_mid_high_total():
    prep = _load("prepare_risk_total", "prepare.py")
    data = {"risk_distribution": {"中高": {"percentage": "5.88%"}, "高": {"percentage": "3.18%"}}}
    assert prep.mid_high_risk_pct(data) == 9.06
    assert prep.mid_high_risk_pct({}) == 0.0
