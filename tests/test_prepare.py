"""prepare.py 关键函数测试 — 纯逻辑验证，不依赖真实 CSV 数据。"""

import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

_HERE = Path(__file__).parent
_BASE = _HERE.parent
_PREPARE_PATH = _BASE / "tasks/portfolio-review/prepare.py"
_RUN_PATH = _BASE / "tasks/portfolio-review/run.py"

spec = importlib.util.spec_from_file_location("prepare", _PREPARE_PATH)
prepare = importlib.util.module_from_spec(spec)

run_spec = importlib.util.spec_from_file_location("run_mod", _RUN_PATH)
run_mod = importlib.util.module_from_spec(run_spec)

_ENV_MOCK = {
    "PSE_LONG_LOSS_DAYS": "180",
    "PSE_LOW_EFF_DAYS": "365",
    "PSE_LOW_EFF_MAX_RETURN": "1.5",
    "PSE_LOW_EFF_MIN_AMOUNT": "10000",
    "PSE_HIGH_VOL_MIN_RETURN": "50",
    "PSE_HIGH_VOL_MAX_DAYS": "180",
    "PSE_HIGH_VOL_MIN_AMOUNT": "5000",
    "PSE_LARGE_POS_TYPES": "理财,债券",
    "PSE_LARGE_POS_MIN_AMOUNT": "100000",
    "PSE_LARGE_POS_MAX_RETURN": "2.5",
    "PSE_CUR_LOSS_THRESHOLD": "-5",
    "PSE_CUR_LOSS_MIN_AMOUNT": "3000",
    "MARKET_INDICES": "上证指数,沪深300",
    "PROP_CORE_VALUE": "住宅估值",
    "PROP_CORE_ESTIMATE": "住宅估价",
    "PROP_CORE_DIFF": "住宅差价",
    "PROP_CORE_UNITS": "",
    "PROP_CORE_PRICE": "",
    "PROP_CORE_LISTING": "",
    "PROP_DISTRICTS": "区域A,区域B",
    "PROP_OLD_VALUE": "旧资产1,旧资产2",
    "GOLD_GLD_COL": "黄金GLD",
    "GOLD_DOMESTIC_COL": "黄金",
    "GOLD_EXCHANGE_COL": "兑换黄金",
    "MARKET_EXTRA": "恐慌VXX,美联基利率",
}


def _make_products(rows: list[dict]) -> list[dict]:
    """补充产品记录 — prepare.py 优先使用 \ufeff名称。"""
    return [{k: v for k, v in r.items()} for r in rows]


@pytest.fixture(autouse=True)
def _setup_env():
    """每个测试前注入环境变量并导入模块。"""
    with patch.dict(os.environ, _ENV_MOCK, clear=False):
        os.chdir(str(_BASE))
        sys.path.insert(0, str(_BASE))
        # run.py 需要 TRACE_DIR 和 PROMT_FILE
        from pathlib import Path as P

        run_mod.TRACE_DIR = P("/tmp/test_traces")
        run_mod.PROMPT_FILE = P("/tmp/test_prompt.md")
        spec.loader.exec_module(prepare)
        run_spec.loader.exec_module(run_mod)
        yield


# ── detect_issues ──


@pytest.mark.parametrize(
    "products,expected_section,expected_count",
    [
        (
            [
                {
                    "名称": "测试理财",
                    "类型": "理财",
                    "投资天数": "400",
                    "年化收益率(%)": "1.2",
                    "当前金额": "50000",
                    "实际收益率(%)": "2",
                }
            ],
            "资金效率低",
            1,
        ),
        (
            [
                {
                    "名称": "边界理财",
                    "类型": "理财",
                    "投资天数": "400",
                    "年化收益率(%)": "1.5",
                    "当前金额": "50000",
                    "实际收益率(%)": "2",
                }
            ],
            "资金效率低",
            0,
        ),
        (
            [
                {
                    "名称": "亏损基金",
                    "类型": "基金",
                    "投资天数": "50",
                    "年化收益率(%)": "-10",
                    "实际收益率(%)": "-8.0",
                    "当前金额": "5000",
                }
            ],
            "当期亏损",
            1,
        ),
        (
            [
                {
                    "名称": "微亏基金",
                    "类型": "基金",
                    "投资天数": "50",
                    "年化收益率(%)": "-4",
                    "实际收益率(%)": "-4.0",
                    "当前金额": "5000",
                }
            ],
            "当期亏损",
            0,
        ),
    ],
)
def test_detect_issues(products, expected_section, expected_count):
    result = prepare.detect_issues(_make_products(products))
    count = result.count(expected_section)
    assert count == expected_count, f"期望 {expected_count}，实际 {count}\n{result}"


# ── build_dca_review / build_c_class_alert ──


def test_build_dca_review():
    products = [
        {
            "名称": "沪深300定投",
            "类型": "定投基金",
            "当前金额": "50000",
            "实际收益率(%)": "-3.0",
            "投资天数": "200",
            "年化收益率(%)": "-5.5",
        },
        {
            "名称": "纳指定投",
            "类型": "定投基金",
            "当前金额": "30000",
            "实际收益率(%)": "8.0",
            "投资天数": "400",
            "年化收益率(%)": "7.3",
        },
        {"名称": "普通理财", "类型": "理财", "当前金额": "100000"},
    ]
    result = prepare.build_dca_review(products)
    assert "⚠️" in result or "✅" in result
    assert "普通理财" not in result


def test_build_c_class_alert():
    products = [
        {"名称": "沪深300增强C", "投资天数": "200", "当前金额": "50000"},
        {"名称": "沪深300增强A", "投资天数": "200", "当前金额": "50000"},
        {"名称": "短持C基", "投资天数": "100", "当前金额": "50000"},
        {"名称": "红利Y份额", "投资天数": "300", "当前金额": "3000"},
    ]
    result = prepare.build_c_class_alert(products)
    # C 类长持应触发，A 类和短持 C 不应触发
    assert "增强C" in result
    assert "增强A" not in result
    assert "短持C" not in result
    assert "红利Y" in result  # Y 类也处理


# ── extract_review_from_trace ──


@pytest.mark.parametrize(
    "specialist_content,should_find",
    [
        (
            "## 🎯 最终结论\n\n### 关键发现\n- test\n\n### 建议操作\n- do\n\n### 整体评估\nok",
            True,
        ),
        ("## 最终结论\n\n### 建议操作\n- test\n\n整体评估: ok", True),
        ("# 报告\nsome text\n### 关键发现\n- item\n### 建议操作\n- do", True),
        ("some random text without any markers", "fallback"),  # 无标记时兜底返回尾部
    ],
)
def test_extract_format_compatibility(specialist_content, should_find, tmp_path):
    trace_data = {
        "verdict": "PASS",
        "total_cycles": 1,
        "total_tokens": 100,
        "cycles": [
            {"messages": [{"source": "Specialist", "content": specialist_content}]}
        ],
    }
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    trace_file = trace_dir / f"trace_{ts}.json"
    trace_file.write_text(json.dumps(trace_data, ensure_ascii=False))

    with patch.object(run_mod, "TRACE_DIR", trace_dir):
        result = run_mod.extract_review_from_trace("test-task")
        assert result is not None
        if should_find == "fallback":
            assert "投资组合诊断" in result
        else:
            assert any(kw in result for kw in ["最终结论", "关键发现", "建议操作"])
