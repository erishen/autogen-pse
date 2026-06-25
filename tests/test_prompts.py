"""提示词加载测试。"""

from pathlib import Path

from src.autogen_pse.prompts import load_prompt

PROMPTS_ROOT = Path(__file__).parent.parent / "prompts"


class TestLoadPrompt:
    def test_load_demo_planner(self):
        content = load_prompt("planner", task="demo")
        assert "Planner" in content
        assert len(content) > 100

    def test_load_demo_specialist(self):
        content = load_prompt("specialist", task="demo")
        assert "Specialist" in content
        assert len(content) > 50

    def test_load_demo_evaluator(self):
        content = load_prompt("evaluator", task="demo")
        assert "Evaluator" in content
        assert len(content) > 50

    def test_load_portfolio_planner(self):
        content = load_prompt("planner", task="portfolio_review")
        assert "投资" in content or "Planner" in content
        assert len(content) > 100

    def test_load_portfolio_evaluator(self):
        content = load_prompt("evaluator", task="portfolio_review")
        assert "PASS" in content and "FAIL" in content
        assert len(content) > 100

    def test_task_separate_prompts_exist(self):
        # 两个任务各有独立的提示词文件目录
        demo = load_prompt("planner", task="demo")
        pr = load_prompt("planner", task="portfolio-review")
        assert len(demo) > 100
        assert len(pr) > 100
        # portfolio-review 有投资相关内容
        assert "投资" in pr or "执行报告" in pr.lower() or "数据" in pr
        assert "代码" in demo or "实现" in demo or "交付" in demo

    def test_file_not_found(self):
        try:
            load_prompt("nonexistent", task="demo")
            assert False, "应该抛出 FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_no_task_falls_back_to_demo(self):
        content = load_prompt("planner")
        assert "Planner" in content
