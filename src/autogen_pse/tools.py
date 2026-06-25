"""共享工具函数和 Token 计数器。"""

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from autogen_agentchat.messages import AgentEvent, ChatMessage


@dataclass
class AgentTokenStats:
    """单个 Agent 的 Token 统计。"""

    name: str
    rounds: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class TokenReport:
    """完整的 Token 消耗报告。"""

    agents: dict[str, AgentTokenStats] = field(default_factory=dict)
    total_rounds: int = 0
    total_prompt: int = 0
    total_completion: int = 0
    currency: str = "¥"
    price_per_1m_input: float = 2.0
    price_per_1m_output: float = 8.0

    @property
    def total_tokens(self) -> int:
        return self.total_prompt + self.total_completion

    @property
    def estimated_cost(self) -> float:
        return (
            self.total_prompt / 1_000_000 * self.price_per_1m_input
            + self.total_completion / 1_000_000 * self.price_per_1m_output
        )

    def summary(self) -> str:
        lines = [
            "",
            "=" * 60,
            "📊 Token 消耗报告",
            "=" * 60,
        ]
        for agent in self.agents.values():
            lines.append(
                f"  {agent.name:12s} | 轮次: {agent.rounds:2d}  |  "
                f"输入: {agent.prompt_tokens:>6d}  |  输出: {agent.completion_tokens:>6d}  |  "
                f"合计: {agent.total_tokens:>6d}"
            )
        lines.append("-" * 60)
        lines.append(
            f"  {'总计':12s} | 轮次: {self.total_rounds:2d}  |  "
            f"输入: {self.total_prompt:>6d}  |  输出: {self.total_completion:>6d}  |  "
            f"合计: {self.total_tokens:>6d}"
        )
        lines.append("-" * 60)
        cost = self.estimated_cost
        if cost < 0.01:
            lines.append(f"  💰 预估费用: < {self.currency}0.01")
        else:
            lines.append(f"  💰 预估费用: {self.currency}{cost:.4f}")
        lines.append("=" * 60)
        return "\n".join(lines)


class TokenTracker:
    """从消息流中追踪 Token 消耗。"""

    def __init__(self, currency: str = "¥"):
        self.report = TokenReport(currency=currency)

    def feed(self, message: ChatMessage | AgentEvent) -> None:
        if hasattr(message, "models_usage") and message.models_usage is not None:
            usage = message.models_usage
            source = getattr(message, "source", "unknown")
            if source not in self.report.agents:
                self.report.agents[source] = AgentTokenStats(name=source)
            stats = self.report.agents[source]
            stats.rounds += 1
            stats.prompt_tokens += usage.prompt_tokens
            stats.completion_tokens += usage.completion_tokens
            self.report.total_rounds += 1
            self.report.total_prompt += usage.prompt_tokens
            self.report.total_completion += usage.completion_tokens


def read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"[错误] 文件不存在: {path}"
    return p.read_text(encoding="utf-8")


def run_pytest(test_path: str = ".") -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout + "\n" + result.stderr
    except Exception as e:
        return f"[错误] pytest 执行失败: {e}"


def run_ruff(path: str = ".") -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout or "ruff 检查通过，无问题。"
    except Exception as e:
        return f"[错误] ruff 执行失败: {e}"
