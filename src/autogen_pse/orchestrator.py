"""RoundRobinGroupChat 编排层 — 含循环控制、step_buffer、执行 Trace 和 Token 统计。"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from autogen_agentchat.base import TaskResult
from autogen_agentchat.conditions import ExternalTermination, TextMentionTermination
from autogen_agentchat.messages import TextMessage
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_ext.models.openai import OpenAIChatCompletionClient

from .agents import create_evaluator, create_planner, create_specialist
from .config import settings
from .tools import AgentTokenStats, TokenReport, TokenTracker

# ── 循环控制参数 ──
MAX_PARTIAL_RETRIES = 3
MAX_FAIL_RETRIES = 2
TURNS_PER_CYCLE = 20

TRACE_DIR = settings.trace_dir


def _create_model_client() -> OpenAIChatCompletionClient:
    kwargs: dict = dict(model=settings.OPENAI_MODEL, api_key=settings.OPENAI_API_KEY)
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    if not settings.OPENAI_MODEL.startswith("gpt-"):
        kwargs["model_info"] = {
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "structured_output": True,
            "family": "unknown",
        }
    return OpenAIChatCompletionClient(**kwargs)


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
    ):
        self.outcome = outcome
        self.summary = summary
        self.report = report
        self.messages = messages or []


def _detect_outcome(messages: list) -> tuple[str, str]:
    last_text = ""
    for msg in reversed(messages):
        if isinstance(msg, TextMessage) and msg.source in ("Planner", "Evaluator"):
            content = msg.content
            if "交付完成" in content:
                return "PASS", content[:2000]
            if "BLOCKED" in content:
                return "BLOCKED", content[:2000]
            if msg.source == "Evaluator":
                for kw in ["FAIL", "PARTIAL"]:
                    if kw in content:
                        return kw, content[:2000]
            if not last_text:
                last_text = content[:2000]
    return "TIMEOUT", last_text


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

    outcome, summary = _detect_outcome(messages)
    chat_log = []
    for m in messages:
        if isinstance(m, TextMessage):
            chat_log.append({"source": m.source, "content": m.content})
    return CycleResult(outcome, summary, tracker.report, chat_log)


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
                    f"请评估是否仍有可交付内容，或宣布 BLOCKED。\n\n"
                    f"原始任务: {task}\n\n"
                    f"最近判决: {result.summary}"
                )
                continue
            current_task = (
                f"上一轮 Evaluator 判决 PARTIAL。"
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
                f"上一轮被判 FAIL。请基于原始任务重新制定计划。"
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

    return (
        TaskResult(
            messages=[],
            stop_reason=f"Evaluator 最终判决: {last_verdict}（{cycle}次循环）",
        ),
        merged,
    )


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
