"""共享工具函数、Token 计数器和 RAG 知识库检索。"""

import json
import logging
import os
import re
import socket
import subprocess
import sys
import urllib.request
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


def _ensure_ollama_endpoint() -> str:
    """确保 OLLAMA_BASE_URL 指向可达的 ollama 服务并返回该 URL。

    容器场景下 localhost:11434 不可达，回退探测 host.docker.internal:11434
    （docker compose 默认提供）。RAGSystem.setup_embeddings 从该 env 读端点。
    向量库为 nomic-embed-text 768 维，检索必须保持同模型语义空间，
    不可静默换成其它 embedding（维度不符会直接报错）。
    """
    import socket
    from urllib.parse import urlparse

    def _reachable(url: str) -> bool:
        try:
            p = urlparse(url)
            with socket.create_connection((p.hostname, p.port or 11434), timeout=2):
                return True
        except OSError:
            return False

    candidates = (
        [os.environ["OLLAMA_BASE_URL"]]
        if os.getenv("OLLAMA_BASE_URL")
        else ["http://localhost:11434", "http://host.docker.internal:11434"]
    )
    for url in candidates:
        if _reachable(url):
            os.environ["OLLAMA_BASE_URL"] = url
            return url
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def _bm25_fallback(rag, query: str, k: int = 3) -> list:
    """语义检索不可用时的纯 BM25 降级（本地关键词检索，无需 embedding 服务）。"""
    if getattr(rag, "bm25", None) is None:
        return []
    return [doc for doc, _ in rag.bm25.search(query, k=k * 2)[:k]]


DEFAULT_KB_QUERIES = [
    "investment strategy risk preference",
    "asset allocation experience",
    "investment goals return expectations",
    "trading discipline stop-loss take-profit",
]

# 只接受投资策略相关的文档来源目录（大小写不敏感匹配，库内混有
# investment/ 与 01-Investment/ 两种写法）；家庭资产/职业/健康等与周报无关。
_INVEST_SOURCE_DIRS = set(
    os.getenv(
        "RAG_SOURCE_DIRS",
        "investment-strategy,01-investment-notes,investment,strategy",
    ).split(",")
)


def _dotenv_value(path: Path, key: str) -> str | None:
    """从指定 .env 文件读取单个键的值（不存在/无该键返回 None）。"""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return None


def _tcp_probe(url: str, timeout: float = 1.0) -> bool:
    """TCP 探测 URL 的 host:port 是否可达（不做 HTTP 请求，够轻）。"""
    from urllib.parse import urlparse

    try:
        u = urlparse(url)
        port = u.port or (443 if u.scheme == "https" else 80)
        with socket.create_connection((u.hostname or "127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _rag_api_config(kb_dir: Path, allow_default: bool = False) -> tuple[str | None, str | None]:
    """解析 profile-rag HTTP 服务的 (base_url, api_key)，任一缺失返回 (None, None)。

    显式 opt-in：设置 ``RAG_API_BASE`` 才走 HTTP 模式。``allow_default=True``
    （qdrant 直读撞锁等兜底场景）时可从默认端点推断：127.0.0.1:18002（宿主
    本机）/ host.docker.internal:18002（容器内经 docker 网关），TCP 探测可达
    才算数——profile-rag 容器常驻时 qdrant 本地存储持排他锁（跨进程/容器
    互斥），直读必失败，HTTP 是唯一无损通路。

    key 优先级：RAG_API_KEY 环境变量 → kb 项目自身 .env 的 INTERNAL_API_KEY
    （profile-rag compose 启动要求；同属 kb 项目内复用，不跨仓扩散）。
    """
    base = os.getenv("RAG_API_BASE")
    if not base and allow_default:
        for cand in ("http://127.0.0.1:18002", "http://host.docker.internal:18002"):
            if _tcp_probe(cand):
                base = cand
                break
    key = os.getenv("RAG_API_KEY") or _dotenv_value(kb_dir / ".env", "INTERNAL_API_KEY")
    if not base or not key:
        return None, None
    return base.rstrip("/"), key


def _retrieve_via_api(
    api_base: str,
    api_key: str,
    queries: list[str],
    k: int = 3,
    apply_source_filter: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """经 profile-rag HTTP API（/api/v1/rag/search，不过 LLM 只返片段）检索。

    服务容器自带完整 RAG 依赖与 ollama 端点配置，是 toolkit 的原生部署形态；
    本地 import 模式仅在其不可用时兜底。

    apply_source_filter=False（RAG_STORE=full）时返回全量域文档——合并后的
    qdrant 库通吃职业/人格/AI/工作流 + 投资，与直读模式行为对称。
    """
    results: dict[str, list[dict[str, Any]]] = {}
    for query in queries:
        body = json.dumps({"query": query, "k": k}).encode()
        req = urllib.request.Request(
            f"{api_base}/api/v1/rag/search",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode())
        for src in payload.get("sources", []):
            meta = src.get("metadata") or {}
            source = str(meta.get("source", "unknown"))
            if apply_source_filter and not any(d in source.lower() for d in _INVEST_SOURCE_DIRS):
                logger.debug("跳过非投资策略文档: %s", source)
                continue
            results.setdefault(query, []).append(
                {
                    "content": src.get("content", "")[:500],
                    "category": meta.get("category", "unknown"),
                    "source": source,
                }
            )
    return results


# ── qdrant 直读（不依赖 profile-rag 容器）──
# 全量个人库（ts-demo/docs 职业/工作流/数字人格/投资等）建库时用的
# embedding 模型是 snowflake-arctic-embed2（1024 维），与 faiss 投资专题库的
# nomic-embed-text（768 维）不是同一语义空间，不可混用。
QDRANT_EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "snowflake-arctic-embed2")


def _rag_store_mode() -> str:
    """归一化 RAG_STORE 取值（2026-10-24 起默认 full）：

    - ``full``：全量域（默认）——投资 + 职业/人格/AI/工作流个人信息；
    - ``invest``：仅投资域（RAG_SOURCE_DIRS source 过滤，周报精准源）；
    - ``faiss``：跳过 qdrant，强制 faiss 兜底。

    未知值按 full 处理（个人信息默认可见，收窄需显式 opt-in）。
    注意：RAG_EXCLUDE_PATTERNS 敏感内容过滤与知识域无关，任何模式恒生效。
    """
    mode = os.getenv("RAG_STORE", "full").strip().lower()
    return mode if mode in ("full", "invest", "faiss") else "full"


def _qdrant_invest_filter():
    """qdrant 侧投资域预过滤（source 命中 RAG_SOURCE_DIRS 任一子串）。

    MatchText 做粗筛减少候选，精准判定仍由调用方的 _INVEST_SOURCE_DIRS
    本地过滤完成（qdrant 分词对路径的匹配不如 Python 子串精确）。
    仅 RAG_STORE=invest（投资域）时返回 Filter；full（默认）/ faiss 返回 None。
    """
    if _rag_store_mode() != "invest":
        return None
    dirs = [d.strip() for d in os.getenv("RAG_SOURCE_DIRS", "").split(",") if d.strip()]
    if not dirs:
        return None
    from qdrant_client.http import models as rest

    return rest.Filter(
        should=[
            rest.FieldCondition(key="metadata.source", match=rest.MatchText(text=d))
            for d in dirs
        ]
    )


def _retrieve_via_qdrant_direct(
    storage_path: str,
    collection: str,
    queries: list[str],
    k: int = 3,
    query_filter=None,
    apply_source_filter: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """薄客户端直读 qdrant 本地存储（不经 profile-rag 容器）。

    单一 qdrant 库 = 原全量个人库（198 点：职业/人格/AI/工作流）
    + faiss 投资专题灌入（310 篇，2026-10-24 合并）。与 HTTP 模式读同一份
    数据，但：

    - **不依赖容器运行**：qdrant local 模式只读访问不持排他锁，与开着的
      profile-rag 容器共存安全（实测：容器 Up 时宿主 scroll/query_points 均正常）；
      写操作（灌库）才需要容器停掉。
    - **绕开 langchain-qdrant 版本坑**：宿主 venv 的 langchain-qdrant 1.1.0 与
      qdrant-client 1.18 的 query_points 返回结构不兼容（AttributeError:
      'tuple' object has no attribute 'payload'），直接用 qdrant_client 取 payload。
    - embedding 模型必须与建库一致（snowflake-arctic-embed2 / 1024 维），
      宿主 ollama 已有该模型；端点经 _ensure_ollama_endpoint() 自适应。

    apply_source_filter=False（RAG_STORE=full 全量域）时跳过投资域过滤，
    直接返回语义最相关的片段（职业/人格/AI 上下文场景）。
    """
    import ollama
    from qdrant_client import QdrantClient

    ollama_url = _ensure_ollama_endpoint()
    logger.info("qdrant 直读模式：embedding 端点 %s，模型 %s", ollama_url, QDRANT_EMBED_MODEL)
    client_q = ollama.Client(host=ollama_url)
    store = QdrantClient(path=storage_path)

    results: dict[str, list[dict[str, Any]]] = {}
    for query in queries:
        emb = client_q.embeddings(model=QDRANT_EMBED_MODEL, prompt=query)["embedding"]
        hits = store.query_points(
            collection_name=collection,
            query=emb,
            limit=k * 2,
            with_payload=True,
            query_filter=query_filter,
        ).points
        for p in hits:
            meta = (p.payload or {}).get("metadata") or {}
            source = str(meta.get("source", "unknown"))
            if apply_source_filter and not any(d in source.lower() for d in _INVEST_SOURCE_DIRS):
                logger.debug("跳过非投资策略文档: %s", source)
                continue
            results.setdefault(query, []).append(
                {
                    "content": (p.payload or {}).get("page_content", "")[:500],
                    "category": meta.get("category", "unknown"),
                    "source": source,
                    "score": round(float(p.score), 4),
                }
            )
            if len(results[query]) >= k:
                break
    return results


def retrieve_knowledge(
    kb_path: str, queries: list[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """从 langchain-llm-toolkit RAG 系统中检索个人投资知识。

    单一 qdrant 库架构（2026-10-24 合并）：qdrant_storage/ = 个人全量库
    （职业/人格/AI/工作流 198 点）+ faiss 投资专题灌入（310 篇），
    四级降级（每级失败自动进下一级，知识库步骤不因单点故障整段失败）：

    1. **HTTP 服务**：显式设置 ``RAG_API_BASE`` 时走 profile-rag 容器
       （容器内/远程调用场景）；直读撞锁时也会自动兜底到此。
    2. **qdrant 直读**（默认）：薄客户端直读 qdrant_storage/，**不依赖容器**。
       默认**全量域**（投资 + 职业/人格/AI/工作流个人信息）；
       ``RAG_STORE=invest`` 时仅投资域（MatchText 预过滤 + 本地 source 过滤）。
    3. **faiss 直读**（兜底）：``RAG_STORE=faiss`` 或 qdrant 不可用时，
       本地 import kb 项目 + 宿主 ollama embedding 读 vector_store/ 投资专题库。
    4. **BM25 降级**：语义检索不可用时的纯关键词检索。

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
        queries = list(DEFAULT_KB_QUERIES)

    # 知识域开关（2026-10-24 起默认 full，见 _rag_store_mode）：
    #   full=全量域（默认，投资 + 职业/人格/AI/工作流个人信息）
    #   invest=仅投资域（MatchText 预过滤 + 本地 source 过滤双保险）
    #   faiss=跳过 qdrant，强制 faiss 兜底
    store_mode = _rag_store_mode()
    full_domain = store_mode != "invest"

    # 模式 1：profile-rag HTTP 服务（显式 opt-in）
    api_base, api_key = _rag_api_config(kb_dir)
    if api_base:
        try:
            results = _retrieve_via_api(
                api_base, api_key, queries, apply_source_filter=not full_domain
            )
            logger.info(
                "知识库检索经 HTTP 服务 %s：%d 个查询，共 %d 篇文档",
                api_base,
                len(queries),
                sum(len(v) for v in results.values()),
            )
            return results
        except Exception as e:
            logger.warning("RAG HTTP 服务不可用（%s），降级到下一模式", e)

    # 模式 2：qdrant 直读（默认；RAG_STORE=faiss 时跳过）
    if store_mode != "faiss":
        storage = os.getenv("RAG_QDRANT_PATH") or str(kb_dir / "qdrant_storage")
        collection = os.getenv("RAG_COLLECTION_NAME", "langchain_documents")
        if Path(storage).exists():
            try:
                results = _retrieve_via_qdrant_direct(
                    storage,
                    collection,
                    queries,
                    query_filter=_qdrant_invest_filter(),
                    apply_source_filter=not full_domain,
                )
                logger.info(
                    "知识库检索经 qdrant 直读 %s：%d 个查询，共 %d 篇文档",
                    storage,
                    len(queries),
                    sum(len(v) for v in results.values()),
                )
                return results
            except Exception as e:
                logger.warning("qdrant 直读失败（%s）", e)
                # 直读失败的高频原因 = profile-rag 容器持排他锁（qdrant local
                # 模式跨进程/容器互斥，2026-10-24 实测：容器 Up 时 resolve-studio
                # 容器内直读必撞锁）。此时容器常驻的 HTTP 服务是无损通路，
                # 优先兜底而非直接降级 faiss（会丢 198 点个人信息 + 310 篇投资）。
                api_base, api_key = _rag_api_config(kb_dir, allow_default=True)
                if api_base:
                    try:
                        results = _retrieve_via_api(
                            api_base,
                            api_key,
                            queries,
                            apply_source_filter=not full_domain,
                        )
                        logger.info(
                            "qdrant 直读撞锁，改经 HTTP 服务 %s：%d 个查询，共 %d 篇文档",
                            api_base,
                            len(queries),
                            sum(len(v) for v in results.values()),
                        )
                        return results
                    except Exception as e2:
                        logger.warning("RAG HTTP 兜底也不可用（%s），降级到 faiss", e2)
                logger.warning("qdrant 直读失败且 HTTP 兜底不可用，降级到 faiss 模式")
        else:
            logger.warning("qdrant 存储目录不存在: %s，降级到 faiss 模式", storage)

    # 模式 3：本地 import kb 项目（faiss 投资专题库，兜底）
    ollama_url = _ensure_ollama_endpoint()
    logger.info("知识库 embedding 端点: %s", ollama_url)

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
                try:
                    docs = rag.retrieve_hybrid(query, k=3, bm25_weight=0.3)
                except Exception as e:
                    # 语义检索不可用（ollama 离线/模型缺失）→ 降级纯 BM25，
                    # 知识库步骤不应因 embedding 服务缺席而整段失败。
                    logger.warning("查询 '%s' 语义检索失败，降级 BM25: %s", query, e)
                    docs = _bm25_fallback(rag, query)
                for doc in docs:
                    source = doc.metadata.get("source", "unknown")
                    # 检查 source 路径是否包含投资策略相关目录（大小写不敏感：
                    # 库内混有 investment/ 与 01-Investment/ 两种写法）
                    if not any(d in source.lower() for d in _INVEST_SOURCE_DIRS):
                        logger.debug("跳过非投资策略文档: %s", source)
                        continue
                    results.setdefault(query, []).append(
                        {
                            "content": doc.page_content[:500],
                            "category": doc.metadata.get("category", "unknown"),
                            "source": source,
                        }
                    )
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
        "⚠️ 以下为历史投资经验记录，仅供了解投资人偏好。当与 Specialist 规则冲突时，以 Specialist 规则为准（如止损线、配置比例目标等）。",
        "",
    ]
    INVEST_CATS = {
        "01-Investment",
        "investment",
        "strategy",
    }
    # 知识域开关与 retrieve_knowledge 一致（2026-10-24 起默认 full，见 _rag_store_mode）：
    #   full   = 放行全部分类（投资 + 职业/人格/AI 等个人信息域）
    #   invest = 仅放行 INVEST_CATS 三个投资分类
    #   faiss  = 同 invest（faiss 库本身只有投资专题）
    # ⚠️ 敏感内容过滤（RAG_EXCLUDE_PATTERNS）与知识域无关、恒生效：
    # 配偶/家庭资产、黄金数量、具体止损线等属隐私红线，任何模式都拦截。
    all_categories = _rag_store_mode() != "invest"
    # 敏感内容过滤：排除非本人资产信息（模式从 RAG_EXCLUDE_PATTERNS 环境变量读取）
    _exclude_cfg = os.getenv("RAG_EXCLUDE_PATTERNS", "")
    _EXCLUDE_PATTERNS = re.compile("|".join(_exclude_cfg.split(","))) if _exclude_cfg else None

    for query, docs in knowledge.items():
        if not docs:
            continue
        # 保留分类：full 域全放行；invest 域只保留投资相关分类，
        # 过滤掉个人简介、工作经验等无关内容
        docs = [d for d in docs if all_categories or d.get("category", "") in INVEST_CATS]
        if not docs:
            continue
        # 过滤含敏感信息的文档片段（如配偶/家庭资产等非本人信息）
        filtered = []
        for d in docs:
            content = d.get("content", "")
            if _EXCLUDE_PATTERNS and _EXCLUDE_PATTERNS.search(content):
                logger.info("过滤掉含敏感信息的RAG文档: category=%s", d.get("category"))
                continue
            filtered.append(d)
        if not filtered:
            continue
        lines.append(f"关于「{query}」的相关知识：")
        for doc in filtered:
            lines.append(f"  [{doc['category']}] {doc['content'][:300]}")
        lines.append("")

    lines.append("请结合以上个人投资偏好和知识进行分析。")
    return "\n".join(lines)
