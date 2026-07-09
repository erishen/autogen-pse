"""PSE Web Dashboard — FastAPI + Vite/React 前端。

启动: make serve  或  uvicorn web_server:app --port 8080
开发: make serve-dev  (FastAPI 8080 + Vite 5173 热更新)
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from autogen_pse.config import settings  # noqa: E402

TASKS_DIR = ROOT / "tasks"
TRACE_DIR = ROOT / "outputs" / "traces"
WEB_DIST = ROOT / "web" / "dist"

# 外部数据目录从 .env 经 settings 读取（与 config.py 统一，不再重复解析 .env）
_ASSET_LENS_DIR = settings.ASSET_LENS_DIR
_MONEY_CSV_DIR = settings.MONEY_CSV_DIR

ASSET_LENS_OUTPUT = (ROOT / _ASSET_LENS_DIR / "output").resolve() if _ASSET_LENS_DIR else None
MONEY_CSV_DATA_DIR = (ROOT / _MONEY_CSV_DIR).resolve() if _MONEY_CSV_DIR else None


def _read_registry() -> dict:
    return json.loads((TASKS_DIR / "_registry.json").read_text())


def _extract_prompt_date(task_name: str) -> str:
    """从 portfolio_review_prompt.md 提取数据截止日期，返回 'YYYYMMDD' 或 '00000000'"""
    prompt_file = TASKS_DIR / task_name / "output" / "portfolio_review_prompt.md"
    if not prompt_file.exists():
        return "00000000"
    text = prompt_file.read_text(encoding="utf-8")
    m = re.search(r"截止\s*(\d{4})年(\d{2})月(\d{2})日", text)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return "00000000"


def _get_latest_data_dates() -> tuple[str, str]:
    """返回 (asset_lens 最新日期, money_csv 最新日期)，均为 'YYYYMMDD' 或 '00000000'"""
    asset_date = "00000000"
    if ASSET_LENS_OUTPUT and ASSET_LENS_OUTPUT.is_dir():
        files = sorted(ASSET_LENS_OUTPUT.glob("投资收益率分析_*.json"), reverse=True)
        if files:
            m = re.search(r"(\d{8})", files[0].name)
            if m:
                asset_date = m.group(1)

    money_date = "00000000"
    if MONEY_CSV_DATA_DIR and MONEY_CSV_DATA_DIR.is_dir():
        dirs = sorted(MONEY_CSV_DATA_DIR.glob("money_csv_*"), reverse=True)
        if dirs:
            m = re.search(r"money_csv_(\d{8})", dirs[0].name)
            if m:
                money_date = m.group(1)

    return asset_date, money_date


def _needs_prepare(task_name: str) -> bool:
    """检查底层数据是否比 prompt 更新，需要则返回 True"""
    prompt_date = _extract_prompt_date(task_name)
    asset_date, money_date = _get_latest_data_dates()
    return asset_date > prompt_date or money_date > prompt_date


app = FastAPI(title="PSE Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── 鉴权中间件 ──
# 仅当设置了 WEB_AUTH_TOKEN 时，对所有 /api/* 接口要求 `Authorization: Bearer <token>`。
# 未设置 token 时接口开放，但 Makefile 默认仅绑定 127.0.0.1（本机访问）。
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        token = settings.WEB_AUTH_TOKEN
        if token and request.headers.get("authorization", "") != f"Bearer {token}":
            return JSONResponse(
                status_code=401,
                content={"detail": "未授权：请在请求头携带 Authorization: Bearer <WEB_AUTH_TOKEN>"},
            )
    return await call_next(request)


@app.on_event("startup")
async def _startup_check():
    if not settings.WEB_AUTH_TOKEN:
        print(
            "\n⚠️  [安全提示] WEB_AUTH_TOKEN 未设置，Web 接口无鉴权。"
            "请仅通过 127.0.0.1 本机访问；如需对外暴露，先在 .env 设置 WEB_AUTH_TOKEN，"
            "再用 make serve WEB_BIND_HOST=0.0.0.0 启动。\n"
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
    preparer = TASKS_DIR / task_name / "prepare.py"
    if not runner.exists():
        raise HTTPException(404, f"{task_name} 无 run.py")

    async def stream():
        python = str(ROOT / ".venv/bin/python")

        # 自动检测是否需要 prepare
        if preparer.exists() and _needs_prepare(task_name):
            prompt_date = _extract_prompt_date(task_name)
            asset_date, money_date = _get_latest_data_dates()
            yield f"data: 🔍 检测到新数据 (prompt: {prompt_date}  asset: {asset_date}  money: {money_date})，自动 prepare...\n\n"

            prep_process = await asyncio.create_subprocess_exec(
                python, "-u", str(preparer),
                cwd=str(ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            while prep_process.stdout:
                line = await prep_process.stdout.readline()
                if not line:
                    break
                yield f"data: [prepare] {line.decode('utf-8', errors='replace').rstrip()}\n\n"
            stderr_data = await prep_process.stderr.read()
            if stderr_data:
                for line in stderr_data.decode("utf-8", errors="replace").split("\n"):
                    if line.strip():
                        yield f"data: [stderr] {line.rstrip()}\n\n"
            await prep_process.wait()
            if prep_process.returncode != 0:
                yield f"event: done\ndata: exit_code={prep_process.returncode}\n\n"
                return
            yield "data: ✅ prepare 完成\n\n"
        else:
            prompt_date = _extract_prompt_date(task_name)
            asset_date, money_date = _get_latest_data_dates()
            yield f"data: ✅ 数据已是最新 (prompt: {prompt_date}  asset: {asset_date}  money: {money_date})，跳过 prepare\n\n"

        # 运行 run.py
        process = await asyncio.create_subprocess_exec(
            python, "-u", str(runner),
            cwd=str(ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        while process.stdout:
            line = await process.stdout.readline()
            if not line:
                break
            yield f"data: {line.decode('utf-8', errors='replace').rstrip()}\n\n"
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
