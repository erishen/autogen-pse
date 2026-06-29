.PHONY: help demo review summarize market lint fix test dev serve kill review-deepseek review-agnes

VENV_PY := .venv/bin/python
PY := $(shell command -v $(VENV_PY) 2>/dev/null || echo "python3")
CLI := $(PY) cli.py

help: ## 显示帮助
	@echo "autogen-pse 可用命令:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  make %-18s %s\n", $$1, $$2}'

test: ## 运行测试
	$(PY) -m pytest tests/ -v

lint: ## 代码检查
	$(PY) -m ruff check src/ tasks/ tests/
	$(PY) -m ruff format --check src/ tasks/ tests/

fix: ## 自动修复代码风格
	$(PY) -m ruff check src/ tasks/ tests/ --fix
	$(PY) -m ruff format src/ tasks/ tests/

demo: ## 运行 PSE 代码交付 Demo
	$(CLI) run demo

summarize: ## 生成投资结构化摘要（零 LLM 成本）
	$(CLI) prepare portfolio-review

market: ## 查看最新市场指数行情
	$(PY) tasks/portfolio-review/prepare_market.py

review: review-deepseek ## 默认用 DeepSeek V4 Pro（等价于 make review-deepseek）

# 开发模式：通过 MODEL 环境变量切换模型
#   MODEL=deepseek-v4-flash make dev-review      # DeepSeek Flash
#   MODEL=llama3.1:8b       make dev-review      # 本地 Ollama
dev-review: summarize
	OPENAI_API_KEY=$(shell grep '^DEEPSEEK_KEY=' .env | cut -d= -f2) \
	OPENAI_BASE_URL=https://api.deepseek.com/v1 \
	OPENAI_MODEL=$(MODEL) $(PY) tasks/portfolio-review/run.py

local-review: summarize ## 开发模式：使用本地 Ollama llama3.1:8b
	OPENAI_BASE_URL=http://localhost:11434/v1 \
	OPENAI_MODEL=llama3.1:8b \
	OPENAI_API_KEY=ollama \
	$(PY) tasks/portfolio-review/run.py

flash-review: summarize ## 开发模式：DeepSeek Flash（更快）
	OPENAI_API_KEY=$(shell grep '^DEEPSEEK_KEY=' .env | cut -d= -f2) \
	OPENAI_BASE_URL=https://api.deepseek.com/v1 \
	OPENAI_MODEL=deepseek-v4-flash \
	$(PY) tasks/portfolio-review/run.py

# ── 多模型快捷命令 ──
review-deepseek: summarize ## 用 DeepSeek V4 Pro 跑周报（流式，稳定）
	OPENAI_API_KEY=$(shell grep '^DEEPSEEK_KEY=' .env | cut -d= -f2) \
	OPENAI_BASE_URL=https://api.deepseek.com/v1 \
	OPENAI_MODEL=deepseek-chat \
	PSE_MODEL_STREAM=true \
	$(PY) tasks/portfolio-review/run.py

review-agnes: summarize ## 用 Agnes 2.0 Flash 跑周报（非流式，免费，放宽循环参数）
	OPENAI_API_KEY=$(shell grep '^AGNES_KEY=' .env | cut -d= -f2) \
	OPENAI_BASE_URL=https://apihub.agnes-ai.com/v1 \
	OPENAI_MODEL=agnes-2.0-flash \
	PSE_MODEL_STREAM=false \
	PSE_TURNS_PER_CYCLE=25 \
	PSE_MAX_PARTIAL_RETRIES=5 \
	$(PY) tasks/portfolio-review/run.py

serve: web-build ## 启动 Web Dashboard（http://localhost:8080）
	$(PY) -m uvicorn web_server:app --host 0.0.0.0 --port 8080

dev: kill ## 开发模式：先杀旧进程，再启动 FastAPI + Vite
	$(PY) -m uvicorn web_server:app --host 0.0.0.0 --port 8080 &
	@sleep 2
	cd web && npm run dev

web-build: ## 构建前端
	cd web && npm install --silent && npm run build

kill: ## 杀掉开发服务器进程（8080 / 5173）
	@lsof -ti:8080 | xargs kill -9 2>/dev/null && echo "✅ 已杀掉 :8080" || echo "  :8080 无进程"
	@lsof -ti:5173 | xargs kill -9 2>/dev/null && echo "✅ 已杀掉 :5173" || echo "  :5173 无进程"
