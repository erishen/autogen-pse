"""编排层测试 — 判决检测、循环控制。"""

from unittest.mock import MagicMock, patch

from autogen_agentchat.messages import TextMessage

from src.autogen_pse.orchestrator import (
    MAX_FAIL_RETRIES,
    MAX_PARTIAL_RETRIES,
    TURNS_PER_CYCLE,
    _detect_outcome,
    create_pse_team,
)


class TestDetectOutcome:
    def test_pass(self):
        msgs = [TextMessage(content="交付完成", source="Planner")]
        outcome, _summary = _detect_outcome(msgs)
        assert outcome == "PASS"

    def test_blocked(self):
        msgs = [TextMessage(content="BLOCKED: 无法完成", source="Planner")]
        outcome, _summary = _detect_outcome(msgs)
        assert outcome == "BLOCKED"

    def test_evaluator_fail(self):
        msgs = [TextMessage(content="FAIL: 关键数据错误", source="Evaluator")]
        outcome, _summary = _detect_outcome(msgs)
        assert outcome == "FAIL"

    def test_evaluator_partial(self):
        msgs = [TextMessage(content="PARTIAL: 第3项数据不符", source="Evaluator")]
        outcome, _summary = _detect_outcome(msgs)
        assert outcome == "PARTIAL"

    def test_pass_after_partial(self):
        """如果有 PASS 也有 PARTIAL，PASS 胜出。"""
        msgs = [
            TextMessage(content="PARTIAL: 小问题", source="Evaluator"),
            TextMessage(content="Specialist 已修复", source="Specialist"),
            TextMessage(content="PASS: 验证通过，交付完成", source="Evaluator"),
            TextMessage(content="交付完成", source="Planner"),
        ]
        outcome, _summary = _detect_outcome(msgs)
        assert outcome == "PASS"

    def test_timeout_when_no_verdict(self):
        msgs = [TextMessage(content="正在分析数据...", source="Planner")]
        outcome, summary = _detect_outcome(msgs)
        assert outcome == "TIMEOUT"
        assert "正在分析" in summary

    def test_summary_truncated(self):
        msgs = [TextMessage(content="FAIL: " + "X" * 3000, source="Evaluator")]
        _outcome, summary = _detect_outcome(msgs)
        assert len(summary) == 2000


class TestLoopParams:
    def test_max_partial_retries(self):
        assert MAX_PARTIAL_RETRIES == 3

    def test_max_fail_retries(self):
        assert MAX_FAIL_RETRIES == 2

    def test_turns_per_cycle(self):
        assert TURNS_PER_CYCLE == 20


class TestCreateTeam:
    @patch("src.autogen_pse.orchestrator.OpenAIChatCompletionClient")
    @patch("src.autogen_pse.orchestrator.create_planner")
    @patch("src.autogen_pse.orchestrator.create_specialist")
    @patch("src.autogen_pse.orchestrator.create_evaluator")
    def test_default_task_is_none(self, mock_ev, mock_sp, mock_pl, mock_cl):
        mock_pl.return_value = MagicMock()
        mock_sp.return_value = MagicMock()
        mock_ev.return_value = MagicMock()
        mock_cl.return_value = MagicMock()

        team = create_pse_team()
        assert team is not None
        # 默认 task=None 时应该用 demo 提示词
        mock_pl.assert_called_once()
        args, _kwargs = mock_pl.call_args
        assert args[1] is None  # task=None

    @patch("src.autogen_pse.orchestrator.OpenAIChatCompletionClient")
    @patch("src.autogen_pse.orchestrator.create_planner")
    @patch("src.autogen_pse.orchestrator.create_specialist")
    @patch("src.autogen_pse.orchestrator.create_evaluator")
    def test_task_passed_through(self, mock_ev, mock_sp, mock_pl, mock_cl):
        mock_pl.return_value = MagicMock()
        mock_sp.return_value = MagicMock()
        mock_ev.return_value = MagicMock()
        mock_cl.return_value = MagicMock()

        create_pse_team(task="portfolio_review")
        args, _kwargs = mock_pl.call_args
        assert args[1] == "portfolio_review"
