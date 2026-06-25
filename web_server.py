"""PSE Web Dashboard — FastAPI + Vite/React 前端。

启动: make serve  或  uvicorn web_server:app --port 8080
开发: make serve-dev  (FastAPI 8080 + Vite 5173 热更新)
"""

import asyncio
import json
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent
TASKS_DIR = ROOT / "tasks"
TRACE_DIR = ROOT / "outputs" / "traces"
WEB_DIST = ROOT / "web" / "dist"


def _read_registry() -> dict:
    return json.loads((TASKS_DIR / "_registry.json").read_text())


app = FastAPI(title="PSE Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── API ──

@app.get("/api/tasks")
def list_tasks():
    return _read_registry()["tasks"]


@app.get("/api/run/{task_name}")
@app.post("/api/run/{task_name}")
async def run_task(task_name: str):
    registry = _read_registry()["tasks"]
    if task_name not in registry:
        raise HTTPException(404, f"未知任务: {task_name}")
    runner = TASKS_DIR / task_name / "run.py"
    if not runner.exists():
        raise HTTPException(404, f"{task_name} 无 run.py")

    async def stream():
        process = await asyncio.create_subprocess_exec(
            str(ROOT / ".venv/bin/python"), "-u", str(runner),
            cwd=str(ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"},
        )
        # 逐行推送 stdout
        while process.stdout:
            line = await process.stdout.readline()
            if not line:
                break
            yield f"data: {line.decode('utf-8', errors='replace').rstrip()}\n\n"
        # stderr 也推
        stderr_data = await process.stderr.read()
        if stderr_data:
            for line in stderr_data.decode("utf-8", errors="replace").split("\n"):
                if line.strip():
                    yield f"data: [stderr] {line.rstrip()}\n\n"
        await process.wait()
        yield f"event: done\ndata: exit_code={process.returncode}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/traces")
def list_traces(limit: int = 10, id: str = ""):
    """列表或单条 trace 详情。传 ?id=xxx 返回单条，否则返回列表。"""
    if id:
        f = TRACE_DIR / f"{id}.json"
        if not f.exists():
            raise HTTPException(404, f"Trace 不存在: {id}")
        return json.loads(f.read_text())
    if not TRACE_DIR.is_dir():
        return []
    traces = []
    for f in sorted(TRACE_DIR.glob("trace_*.json"), reverse=True)[:limit]:
        data = json.loads(f.read_text())
        traces.append({
            "id": f.stem,
            "time": data.get("started_at", "?")[:16],
            "verdict": data.get("verdict", "?"),
            "cycles": data.get("total_cycles", 0),
            "tokens": data.get("total_tokens", 0),
        })
    return traces


@app.get("/api/report/{task_name}")
def latest_report(task_name: str):
    """返回最新报告的 HTML 版本。"""
    import markdown

    output_dir = TASKS_DIR / task_name / "output"
    if not output_dir.is_dir():
        return {"html": "<p>暂无报告</p>"}
    md_files = sorted(output_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not md_files:
        return {"html": "<p>暂无报告</p>"}
    md = md_files[0].read_text(encoding="utf-8")
    html = markdown.markdown(md, extensions=["tables", "fenced_code"])
    return {"html": html, "file": str(md_files[0].relative_to(ROOT))}


@app.get("/api/archive/{task_name}")
def list_archive(task_name: str, limit: int = 12):
    archive_dir = TASKS_DIR / task_name / "output" / "archive"
    if not archive_dir.is_dir():
        return []
    files = sorted(archive_dir.glob("weekly_*.md"), reverse=True)[:limit]
    result = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        assets = re.search(r"当前总资产:\s*([\d.]+)万元", text)
        ret = re.search(r"整体收益率:\s*([+-][\d.]+%)", text)
        result.append({
            "date": f.stem.replace("weekly_", ""),
            "total_assets": assets.group(1) if assets else None,
            "return_rate": ret.group(1) if ret else None,
        })
    return result


# ── 前端静态文件 ──

if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def serve_react(path: str):
        f = WEB_DIST / path
        if f.is_file():
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
