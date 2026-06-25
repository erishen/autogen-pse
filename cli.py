#!/usr/bin/env python3
"""PSE 任务平台 CLI — pse list / pse run <task> / pse trace。

用法:
    python cli.py list                         # 列出所有任务
    python cli.py run <task>                   # 运行任务（prepare + run）
    python cli.py prepare <task>               # 仅运行数据准备
    python cli.py trace                        # 查看最近的执行 trace
"""

import json
import subprocess
import sys
from argparse import ArgumentParser
from pathlib import Path

ROOT = Path(__file__).parent  # project root
TASKS_DIR = ROOT / "tasks"
VENV_PYTHON = ROOT / ".venv/bin/python" if (ROOT / ".venv").exists() else Path(sys.executable)


def _load_registry() -> dict:
    return json.loads((TASKS_DIR / "_registry.json").read_text())


def _check_task(name: str) -> Path:
    task_dir = TASKS_DIR / name
    if not task_dir.is_dir():
        valid = ", ".join(_load_registry()["tasks"].keys())
        sys.exit(f"未知任务: {name}（可用: {valid}）")
    return task_dir


def cmd_list():
    registry = _load_registry()
    print("可用任务:\n")
    for name, info in registry["tasks"].items():
        print(f"  {name:20s}  {info['label']}")
        print(f"  {'':20s}  {info['description']}")
        print()


def cmd_prepare(name: str):
    task_dir = _check_task(name)
    prepare_script = task_dir / "prepare.py"
    if not prepare_script.exists():
        print(f"⚠️  {name} 无 prepare.py，跳过数据准备")
        return
    print(f"⏳ {name}: prepare ...")
    subprocess.run([str(VENV_PYTHON), str(prepare_script)], check=True, cwd=str(ROOT))


def cmd_run(name: str, skip_prepare: bool = False):
    task_dir = _check_task(name)
    if not skip_prepare:
        cmd_prepare(name)
    run_script = task_dir / "run.py"
    if not run_script.exists():
        sys.exit(f"❌ 未找到 run.py: {run_script}")
    print(f"🚀 {name}: run ...")
    subprocess.run([str(VENV_PYTHON), str(run_script)], check=True, cwd=str(ROOT))


def cmd_trace(_n: int = 5):
    trace_dir = ROOT / "outputs" / "traces"
    if not trace_dir.is_dir():
        print("还没有执行 trace")
        return
    files = sorted(trace_dir.glob("trace_*.json"), reverse=True)
    if not files:
        print("还没有执行 trace")
        return
    print(f"最近 {min(len(files), _n)} 次执行:\n")
    for f in files[:_n]:
        data = json.loads(f.read_text())
        t = data.get("started_at", "?")[:16]
        v = data.get("verdict", "?")
        cyc = data.get("total_cycles", "?")
        tokens = data.get("total_tokens", 0)
        print(f"  {f.stem}  [{t}]  {v}  {cyc}轮  {tokens} tokens")


def main():
    parser = ArgumentParser(description="PSE 任务平台")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出所有任务")

    r = sub.add_parser("run", help="运行任务")
    r.add_argument("task")
    r.add_argument("--skip-prepare", action="store_true", help="跳过数据准备")

    p = sub.add_parser("prepare", help="仅运行数据准备")
    p.add_argument("task")

    t = sub.add_parser("trace", help="查看执行 trace")
    t.add_argument("-n", type=int, default=5, help="显示最近 N 条")

    args = parser.parse_args()
    if args.cmd == "list":
        cmd_list()
    elif args.cmd == "run":
        cmd_run(args.task, args.skip_prepare)
    elif args.cmd == "prepare":
        cmd_prepare(args.task)
    elif args.cmd == "trace":
        cmd_trace(args.n)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
