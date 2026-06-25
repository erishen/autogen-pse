"""Token 统计测试。"""

from unittest.mock import MagicMock

from src.autogen_pse.tools import AgentTokenStats, TokenReport, TokenTracker


class TestAgentTokenStats:
    def test_basic(self):
        s = AgentTokenStats(name="Planner")
        assert s.name == "Planner"
        assert s.rounds == 0
        assert s.prompt_tokens == 0
        assert s.completion_tokens == 0
        assert s.total_tokens == 0

    def test_total_tokens(self):
        s = AgentTokenStats(name="X", rounds=3, prompt_tokens=100, completion_tokens=50)
        assert s.total_tokens == 150


class TestTokenReport:
    def test_empty(self):
        r = TokenReport()
        assert r.total_rounds == 0
        assert r.total_tokens == 0
        assert r.estimated_cost == 0

    def test_cost_calculation(self):
        r = TokenReport(
            total_prompt=1_000_000,
            total_completion=500_000,
            price_per_1m_input=2.0,
            price_per_1m_output=8.0,
            currency="¥",
        )
        assert r.estimated_cost == 6.0  # 2 + 4

    def test_cost_floor(self):
        r = TokenReport(total_prompt=10, total_completion=5)
        cost = r.estimated_cost
        assert cost > 0
        assert cost < 0.01

    def test_summary_includes_agents(self):
        r = TokenReport(currency="¥")
        r.agents["Planner"] = AgentTokenStats(
            name="Planner", rounds=1, prompt_tokens=100, completion_tokens=50
        )
        r.total_rounds = 1
        r.total_prompt = 100
        r.total_completion = 50
        summary = r.summary()
        assert "Planner" in summary
        assert "100" in summary
        assert "50" in summary

    def test_agent_aggregation(self):
        r = TokenReport()
        r.agents["A"] = AgentTokenStats(
            name="A", rounds=2, prompt_tokens=200, completion_tokens=100
        )
        r.agents["B"] = AgentTokenStats(
            name="B", rounds=1, prompt_tokens=50, completion_tokens=25
        )
        assert len(r.agents) == 2
        assert r.agents["A"].total_tokens == 300
        assert r.agents["B"].total_tokens == 75


class TestTokenTracker:
    def _make_msg(self, source: str, usage):
        msg = MagicMock()
        msg.source = source
        msg.models_usage = usage
        return msg

    def _make_usage(self, prompt: int, completion: int):
        u = MagicMock()
        u.prompt_tokens = prompt
        u.completion_tokens = completion
        return u

    def test_feed_single_agent(self):
        tracker = TokenTracker()
        tracker.feed(self._make_msg("Planner", self._make_usage(100, 50)))
        tracker.feed(self._make_msg("Planner", self._make_usage(200, 100)))
        r = tracker.report
        assert r.total_rounds == 2
        assert r.total_prompt == 300
        assert r.total_completion == 150
        assert r.agents["Planner"].rounds == 2

    def test_feed_multiple_agents(self):
        tracker = TokenTracker()
        tracker.feed(self._make_msg("Planner", self._make_usage(100, 50)))
        tracker.feed(self._make_msg("Specialist", self._make_usage(500, 300)))
        tracker.feed(self._make_msg("Evaluator", self._make_usage(200, 100)))
        r = tracker.report
        assert len(r.agents) == 3
        assert r.total_prompt == 800
        assert r.total_completion == 450

    def test_skips_null_usage(self):
        tracker = TokenTracker()
        msg = MagicMock()
        msg.models_usage = None
        tracker.feed(msg)
        assert tracker.report.total_rounds == 0

    def test_unknown_source(self):
        tracker = TokenTracker()
        tracker.feed(self._make_msg("unknown", self._make_usage(10, 5)))
        assert "unknown" in tracker.report.agents
