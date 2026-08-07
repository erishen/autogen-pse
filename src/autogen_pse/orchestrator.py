"""RoundRobinGroupChat 编排层 — 含循环控制、执行 Trace 和 Token 统计。"""

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from autogen_agentchat.base import TaskResult
from autogen_agentchat.conditions import ExternalTermination, TextMentionTermination
from autogen_agentchat.messages import TextMessage
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_core.models import LLMMessage, UserMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient

from .agents import (
    create_evaluator,
    create_planner,
    create_specialist,
)
from .config import settings
from .tools import AgentTokenStats, TokenReport, TokenTracker

logger = logging.getLogger(__name__)

# ── 循环控制参数 ──
MAX_PARTIAL_RETRIES = int(os.getenv("PSE_MAX_PARTIAL_RETRIES", "3"))
MAX_FAIL_RETRIES = int(os.getenv("PSE_MAX_FAIL_RETRIES", "2"))
TURNS_PER_CYCLE = int(os.getenv("PSE_TURNS_PER_CYCLE", "9"))
PSE_TIMEOUT = int(os.getenv("PSE_TIMEOUT", "180"))

TRACE_DIR = settings.trace_dir


def _create_model_client() -> OpenAIChatCompletionClient:
    # 推理模型（deepseek-v4-flash, Kimi-K2.6 等）的 reasoning_tokens 计入 max_tokens，
    # 导致 content 被截断为空。解决方案：
    # - 推理模型：用 max_completion_tokens 代替 max_tokens，reasoning 不计入此预算
    # - 普通模型：用 max_tokens
    model_name = settings.OPENAI_MODEL.lower()
    is_reasoning = any(kw in model_name for kw in ["flash", "reasoner", "kimi", "r1", "v4"])

    kwargs: dict = dict(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
    )
    if is_reasoning:
        # max_completion_tokens: reasoning 不计入此预算，只限制最终输出
        kwargs["max_completion_tokens"] = int(os.getenv("PSE_MAX_TOKENS", "8192"))
    else:
        kwargs["max_tokens"] = int(os.getenv("PSE_MAX_TOKENS", "8192"))
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    if not settings.OPENAI_MODEL.startswith("gpt-"):
        kwargs["model_info"] = {
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "structured_output": False,  # 非 OpenAI 模型不支持 structured output
            "family": "unknown",
        }
    inner = OpenAIChatCompletionClient(**kwargs, timeout=PSE_TIMEOUT)
    return _SafeModelClient(inner)


class _SafeModelClient(OpenAIChatCompletionClient):
    """包装 OpenAIChatCompletionClient，修复第三方 API 的兼容性问题：

    1. 空 user 消息填充占位符 — 推理模型可能返回 content=null，
       AutoGen 转为空字符串，某些 API 拒绝空 user 消息导致 400。
    2. 推理模型 content 为空时的两步处理 — 推理模型（如 deepseek-v4-flash、
       Kimi-K2.6）将全部输出放在 reasoning_content 中而 content=null。
       AutoGen 存入 thought 字段，content 为空字符串。
       处理流程：
       a) 优先重试：将 thought 摘要作为上下文，让模型输出正式中文结论
       b) 兜底回填：如果重试仍失败，将 thought 回填到 content（防止死循环）
    """

    def __init__(self, inner: OpenAIChatCompletionClient):
        # 不调用 super().__init__()，直接复用内部 client 的状态
        self.__dict__ = inner.__dict__.copy()
        self._inner = inner

    def _sanitize_messages(self, messages: Sequence[LLMMessage]) -> list[LLMMessage]:
        """过滤/修复可能导致 API 400 的消息。"""
        result = []
        for msg in messages:
            if isinstance(msg, UserMessage):
                content = msg.content
                # 空字符串或纯空白的 user 消息 → 填充占位符
                if isinstance(content, str) and not content.strip():
                    msg = UserMessage(
                        content="(继续执行上一条指令)",
                        source=msg.source,
                    )
                    logger.debug("替换空 user 消息: source=%s", msg.source)
            result.append(msg)
        return result

    def _has_real_content(self, result) -> bool:
        """判断 result.content 是否包含实质内容（非空白、非纯推理草稿）。"""
        if not isinstance(result.content, str):
            return bool(result.content)
        text = result.content.strip()
        if not text:
            return False
        # 如果 content 全是英文且超长，很可能是推理草稿
        cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        if cn_chars == 0 and len(text) > 200:
            logger.warning("检测到纯英文长文本（%d字符），疑似推理草稿", len(text))
            return False
        return True

    def _backfill_thought(self, result):
        """兜底：将 thought 回填到 content，防止空消息死循环。"""
        if isinstance(result.content, str) and not result.content.strip():
            if result.thought and result.thought.strip():
                logger.warning("thought 回填（兜底）: thought 长度=%d", len(result.thought))
                result.content = result.thought
        return result

    async def create(self, messages, **kwargs):
        sanitized = self._sanitize_messages(messages)
        result = await self._inner.create(sanitized, **kwargs)

        if not self._has_real_content(result):
            if result.thought and result.thought.strip():
                # 第一步：将 thought 摘要作为上下文，重试让模型输出正式结论
                thought_preview = result.thought[:2000]
                context_msg = UserMessage(
                    content=(
                        f"你刚才完成了推理分析（摘要如下），请基于推理结果，"
                        f"直接输出正式的中文结论，严格按照格式要求，"
                        f"不要输出推理过程：\n\n{thought_preview}"
                    ),
                    source="user",
                )
                logger.warning(
                    "推理模型 content 为空（thought 长度=%d），带上下文重试",
                    len(result.thought),
                )
                try:
                    retry_result = await self._inner.create(
                        sanitized + [context_msg], **kwargs
                    )
                    if self._has_real_content(retry_result):
                        return retry_result
                    # 重试成功但内容仍无实质 → 兜底回填
                    logger.warning("重试后 content 仍无实质内容，兜底回填 thought")
                    return self._backfill_thought(retry_result)
                except Exception as e:
                    logger.error("重试失败: %s，兜底回填 thought", e)
                    return self._backfill_thought(result)
            else:
                logger.warning("content 为空且无 thought，无法处理")
        return result

    async def create_stream(self, messages, **kwargs):
        result = None
        async for chunk in self._inner.create_stream(self._sanitize_messages(messages), **kwargs):
            if isinstance(chunk, str):
                yield chunk
            else:
                result = chunk
                yield result


def create_pse_team(
    model_client: Optional[OpenAIChatCompletionClient] = None,
    task: Optional[str] = None,
) -> RoundRobinGroupChat:
    if model_client is None:
        model_client = _create_model_client()

    planner = create_planner(model_client, task)
    specialist = create_specialist(model_client, task)
    evaluator = create_evaluator(model_client, task)

    text_term = TextMentionTermination("交付完成") | TextMentionTermination("BLOCKED")
    return RoundRobinGroupChat(
        participants=[planner, specialist, evaluator],
        termination_condition=text_term | ExternalTermination(),
        max_turns=TURNS_PER_CYCLE,
    )


class CycleResult:
    def __init__(
        self,
        outcome: str,
        summary: str,
        report: TokenReport,
        messages: list | None = None,
        reason: str = "",
    ):
        self.outcome = outcome
        self.summary = summary
        self.report = report
        self.messages = messages or []
        self.reason = reason


_REASON_RE = re.compile(r"原因码\**\s*[：:]\s*(\w+)", re.IGNORECASE)


def _detect_outcome(messages: list) -> tuple[str, str, str]:
    """从消息列表中检测判决结果，返回 (outcome, reason_code, summary)"""
    last_text = ""
    for msg in reversed(messages):
        if isinstance(msg, TextMessage) and msg.source in ("Planner", "Evaluator"):
            content = msg.content
            if "交付完成" in content:
                return "PASS", "OK", content[:2000]
            if "BLOCKED" in content:
                return "BLOCKED", "UNKNOWN", content[:2000]
            if msg.source == "Evaluator":
                for kw in ["PASS", "FAIL", "PARTIAL"]:
                    if kw in content:
                        m = _REASON_RE.search(content)
                        return kw, (m.group(1).upper() if m else kw), content[:2000]
            if not last_text:
                last_text = content[:2000]
    return "TIMEOUT", "UNKNOWN", last_text


def _make_trace(report: TokenReport) -> dict:
    agents = {}
    for name, stats in report.agents.items():
        agents[name] = {
            "rounds": stats.rounds,
            "prompt_tokens": stats.prompt_tokens,
            "completion_tokens": stats.completion_tokens,
        }
    return {
        "total_rounds": report.total_rounds,
        "total_prompt": report.total_prompt,
        "total_completion": report.total_completion,
        "agents": agents,
        "cost_yuan": round(report.estimated_cost, 4),
    }


async def _run_one_cycle(
    team: RoundRobinGroupChat,
    task: str,
    verbose: bool,
) -> CycleResult:
    tracker = TokenTracker()
    messages = []

    async for msg in team.run_stream(task=task):
        tracker.feed(msg)
        if isinstance(msg, TaskResult):
            continue
        messages.append(msg)
        if verbose:
            _print_message(msg)

    outcome, reason, summary = _detect_outcome(messages)
    chat_log = []
    for m in messages:
        if isinstance(m, TextMessage):
            chat_log.append({"source": m.source, "content": m.content})
    return CycleResult(outcome, summary, tracker.report, chat_log, reason=reason)


async def run_task(
    team: RoundRobinGroupChat,
    task: str,
    verbose: bool = False,
) -> tuple[TaskResult, TokenReport]:
    traces = []
    all_reports = []
    partial_count = 0
    fail_count = 0
    last_verdict = ""
    cycle = 0
    started_at = datetime.now().isoformat()

    current_task = task

    while True:
        cycle += 1
        cycle_start = datetime.now().isoformat()
        if verbose:
            print(f"\n{'─' * 60}")
            print(f"  🔄 第 {cycle} 次循环")
            print(f"{'─' * 60}")

        result = await _run_one_cycle(team, current_task, verbose)
        cycle_end = datetime.now().isoformat()
        last_verdict = result.outcome
        all_reports.append(result.report)

        trace_entry = {
            "cycle": cycle,
            "started": cycle_start,
            "ended": cycle_end,
            "outcome": result.outcome,
            "reason": result.reason,
            "verdict_summary": result.summary[:2000],
            "token": _make_trace(result.report),
            "messages": result.messages,
        }
        traces.append(trace_entry)

        if result.outcome == "PASS":
            if verbose:
                print("\n✅ 交付完成")
            break

        if result.outcome == "PARTIAL":
            partial_count += 1
            if partial_count > MAX_PARTIAL_RETRIES:
                current_task = (
                    f"连续 PARTIAL {partial_count} 次，已达上限。"
                    f"最近原因: {result.reason}。"
                    f"请评估是否仍有可交付内容，或宣布 BLOCKED。\n\n"
                    f"原始任务: {task}\n\n"
                    f"最近判决: {result.summary}"
                )
                continue
            current_task = (
                f"上一轮 Evaluator 判决 PARTIAL (原因: {result.reason})。"
                f"请修复以下问题后重新提交：\n\n{result.summary}"
            )
            continue

        if result.outcome == "FAIL":
            fail_count += 1
            fail_rem = MAX_FAIL_RETRIES - fail_count
            if fail_rem < 0:
                if verbose:
                    print(f"\n❌ 连续 FAIL {MAX_FAIL_RETRIES}+ 次，强制 BLOCKED")
                break
            current_task = (
                f"上一轮被判 FAIL (原因: {result.reason})。请基于原始任务重新制定计划。"
                f"（剩余重试次数: {fail_rem}）\n\n"
                f"原始任务: {task}\n\n"
                f"失败原因: {result.summary}"
            )
            continue

        if verbose:
            print(f"\n⏹ 退出: {result.outcome}")
        break

    if fail_count > MAX_FAIL_RETRIES:
        last_verdict = f"FAIL→BLOCKED（{MAX_FAIL_RETRIES}次FAIL后自动终止）"
    elif partial_count > MAX_PARTIAL_RETRIES:
        last_verdict = f"PARTIAL→BLOCKED（{MAX_PARTIAL_RETRIES}次PARTIAL后自动终止）"

    merged = TokenReport()
    for r in all_reports:
        merged.total_rounds += r.total_rounds
        merged.total_prompt += r.total_prompt
        merged.total_completion += r.total_completion
        for name, stats in r.agents.items():
            existing = merged.agents.setdefault(name, AgentTokenStats(name=name))
            existing.rounds += stats.rounds
            existing.prompt_tokens += stats.prompt_tokens
            existing.completion_tokens += stats.completion_tokens

    trace_file = _write_trace(started_at, last_verdict, cycle, traces, merged, task)
    if verbose:
        print(f"\n📋 执行 Trace → {trace_file}")

    _cleanup_old_traces()

    return (
        TaskResult(
            messages=[],
            stop_reason=f"Evaluator 最终判决: {last_verdict}（{cycle}次循环）",
        ),
        merged,
    )


def _cleanup_old_traces() -> None:
    """清理 7 天前的 trace 文件。"""
    cutoff = time.time() - 7 * 86400
    trace_dir = TRACE_DIR
    if not trace_dir.exists():
        return
    deleted = 0
    for f in trace_dir.glob("trace_*.json"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1
    if deleted:
        pass  # silent cleanup, no log to keep output clean


def _write_trace(
    started_at: str,
    verdict: str,
    total_cycles: int,
    traces: list,
    report: TokenReport,
    task: str,
) -> Path:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)

    total_prompt = sum(r["token"]["total_prompt"] for r in traces if "token" in r)
    total_completion = sum(
        r["token"]["total_completion"] for r in traces if "token" in r
    )

    trace_data = {
        "started_at": started_at,
        "ended_at": datetime.now().isoformat(),
        "verdict": verdict,
        "total_cycles": total_cycles,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "cycles": traces,
        "task": task[:500],
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    trace_file = TRACE_DIR / f"trace_{ts}.json"
    trace_file.write_text(json.dumps(trace_data, ensure_ascii=False, indent=2))
    return trace_file


def _print_message(message) -> None:
    if isinstance(message, TextMessage):
        print(f"\n{'=' * 60}\n[{message.source}]\n{'=' * 60}\n{message.content}")
