"""共享工具函数、Token 计数器和 RAG 知识库检索。"""

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autogen_agentchat.messages import AgentEvent, ChatMessage

from .config import ROOT

logger = logging.getLogger(__name__)


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
        p = Path(test_path)
        resolve_dir = str(p.parent.resolve()) if p.parent.exists() else None
        result = subprocess.run(
            [sys.executable, "-m", "pytest", p.name, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=resolve_dir,
        )
        return result.stdout + "\n" + result.stderr
    except Exception as e:
        return f"[错误] pytest 执行失败: {e}"


def run_ruff(path: str = ".") -> str:
    try:
        p = Path(path)
        resolve_dir = str(p.parent.resolve()) if p.parent.exists() else None
        target = p.name if resolve_dir else path
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", target],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=resolve_dir,
        )
        return result.stdout or "ruff 检查通过，无问题。"
    except Exception as e:
        return f"[错误] ruff 执行失败: {e}"


def bash(command: str, timeout: int = 30) -> str:
    # 禁止通过 bash heredoc 写入文件（内容过长时闭合符易被截断，导致文件损坏）
    import re

    if re.search(r"(cat|tee|python)\s+.*>\s*\S+.*<<\s*['\"]?\w*['\"]?", command):
        return (
            "[禁止] 不允许在 bash 中使用 heredoc 写入文件（存在截断风险）。"
            "请使用 write_file 工具代替。"
        )

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            shell=True,
            timeout=timeout,
            cwd=str(ROOT),
        )
        return result.stdout.strip() + "\n" + result.stderr.strip()
    except subprocess.TimeoutExpired:
        return f"[超时] 命令执行超过 {timeout} 秒"
    except Exception as e:
        return f"[错误] 命令执行失败: {e}"


# ── RAG 知识库检索 ──


def retrieve_knowledge(
    kb_path: str, queries: list[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """从 langchain-llm-toolkit RAG 系统中检索个人投资知识。

    Args:
        kb_path: 指向 langchain-llm-toolkit 项目的路径。
        queries: 检索查询列表，默认为投资相关查询。

    Returns:
        Dict 映射 query -> document 列表。
    """
    kb_dir = Path(kb_path).resolve()
    if not kb_dir.exists():
        logger.warning("知识库路径不存在: %s", kb_dir)
        return {}

    if queries is None:
        queries = [
            "投资策略 投资偏好 风险偏好",
            "个人投资经验 资产配置",
            "投资目标 收益预期",
            "交易纪律 止损 止盈",
        ]

    sys.path.insert(0, str(kb_dir / "src"))
    try:
        from langchain_llm_toolkit.rag import RAGSystem
    except ImportError:
        logger.warning("无法导入 langchain_llm_toolkit.rag，跳过知识库检索")
        sys.path.pop(0)
        return {}

    try:
        rag = RAGSystem(
            vector_store_type="faiss",
            embedding_type="ollama",
            embedding_model="nomic-embed-text:latest",
        )
        rag.vector_store_dir = str(kb_dir / "vector_store")
        rag.faiss_persist_dir = str(kb_dir / "vector_store")
        rag.load_vector_store()

        results: dict[str, list[dict[str, Any]]] = {}
        for query in queries:
            try:
                docs = rag.retrieve_hybrid(query, k=3, bm25_weight=0.3)
                results[query] = [
                    {
                        "content": doc.page_content[:500],
                        "category": doc.metadata.get("category", "unknown"),
                        "source": doc.metadata.get("source", "unknown"),
                    }
                    for doc in docs
                ]
            except Exception as e:
                logger.warning("查询 '%s' 失败: %s", query, e)
                results[query] = []

        logger.info(
            "检索到 %d 个查询的知识，共 %d 篇文档",
            len(queries),
            sum(len(v) for v in results.values()),
        )
        return results
    except Exception as e:
        logger.warning("加载向量库失败: %s", e)
        return {}
    finally:
        sys.path.pop(0)


def format_knowledge_context(knowledge: dict[str, list[dict[str, Any]]]) -> str:
    """将检索到的知识格式化为可读的上下文字符串。

    Args:
        knowledge: Dict 映射 query -> document 列表。

    Returns:
        格式化后的字符串，供 PSE 分析使用。
    """
    if not knowledge:
        return ""
    total_docs = sum(len(v) for v in knowledge.values())
    if total_docs == 0:
        return ""

    lines = [
        "=== 投资人个人知识库（投资偏好、策略经验） ===",
        "",
    ]
    INVEST_CATS = {
        "01-Investment",
        "03-Financial",
        "advice",
        "financial",
        "investment",
        "strategy",
    }
    for query, docs in knowledge.items():
        if not docs:
            continue
        # 只保留与投资相关的分类，过滤掉个人简介、工作经验等无关内容
        docs = [d for d in docs if d.get("category", "") in INVEST_CATS]
        if not docs:
            continue
        lines.append(f"关于「{query}」的相关知识：")
        for i, doc in enumerate(docs, 1):
            lines.append(f"  [{doc['category']}] {doc['content'][:300]}")
        lines.append("")

    lines.append("请结合以上个人投资偏好和知识进行分析。")
    return "\n".join(lines)
