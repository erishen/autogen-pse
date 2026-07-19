.PHONY: help demo review summarize market lint fix test dev serve kill review-deepseek review-agnes review-kimi review-minimax _auto-summarize

VENV_PY := .venv/bin/python
PY := $(shell command -v $(VENV_PY) 2>/dev/null || echo "python3")
CLI := $(PY) cli.py

# Web 服务绑定地址：默认仅本机；对外暴露须 WEB_BIND_HOST=0.0.0.0 且先设 WEB_AUTH_TOKEN
WEB_BIND_HOST ?= 127.0.0.1

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

# 自动检测：比对 portfolio_review_prompt.md 日期 vs asset-lens / money-csv 最新数据
_auto-summarize:
	@ASSET_DIR=$(shell grep '^ASSET_LENS_DIR=' .env | cut -d= -f2); \
	MONEY_DIR=$(shell grep '^MONEY_CSV_DIR=' .env | cut -d= -f2); \
	PROMPT_DATE=$$(sed -n 's/.*截止 \([0-9]\{4\}\)年\([0-9]\{2\}\)月\([0-9]\{2\}\)日.*/\1\2\3/p' tasks/portfolio-review/output/portfolio_review_prompt.md 2>/dev/null | head -1); \
	[ -z "$$PROMPT_DATE" ] && PROMPT_DATE="00000000"; \
	ASSET_DATE=$$(ls -t "$$ASSET_DIR"/output/投资收益率分析_*.json 2>/dev/null | head -1 | grep -o '[0-9]\{8\}' || echo "00000000"); \
	MONEY_DATE=$$(ls -td "$$MONEY_DIR"/money_csv_* 2>/dev/null | head -1 | grep -o '[0-9]\{8\}' || echo "00000000"); \
	if [ "$$ASSET_DATE" -gt "$$PROMPT_DATE" ] 2>/dev/null || [ "$$MONEY_DATE" -gt "$$PROMPT_DATE" ] 2>/dev/null; then \
		echo "🔍 检测到新数据 (prompt: $$PROMPT_DATE  asset: $$ASSET_DATE  money: $$MONEY_DATE)，自动 summarize..."; \
		$(MAKE) summarize; \
	else \
		echo "✅ 数据已是最新 (prompt: $$PROMPT_DATE  asset: $$ASSET_DATE  money: $$MONEY_DATE)"; \
	fi

# 开发模式：通过 MODEL 环境变量切换模型
#   MODEL=your-model-name make dev-review      # DeepSeek Flash
#   MODEL=llama3.1:8b       make dev-review      # 本地 Ollama
dev-review: _auto-summarize
	OPENAI_BASE_URL=$(shell grep '^OPENAI_BASE_URL=' .env | cut -d= -f2) \
	OPENAI_MODEL=$(MODEL) $(PY) tasks/portfolio-review/run.py

local-review: _auto-summarize ## 开发模式：使用本地 Ollama llama3.1:8b
	OPENAI_BASE_URL=http://localhost:11434/v1 \
	OPENAI_MODEL=llama3.1:8b \
	OPENAI_API_KEY=ollama \
	$(PY) tasks/portfolio-review/run.py

flash-review: _auto-summarize ## 开发模式：DeepSeek Flash（更快）
	OPENAI_API_KEY=$(shell grep '^OPENAI_API_KEY=' .env | cut -d= -f2) \
	OPENAI_BASE_URL=$(shell grep '^OPENAI_BASE_URL=' .env | cut -d= -f2) \
	OPENAI_MODEL=$(MODEL) \
	$(PY) tasks/portfolio-review/run.py

# ── 多模型快捷命令 ──
review-deepseek: _auto-summarize ## 用 DeepSeek V4 Pro 跑周报（流式，稳定）
	OPENAI_API_KEY=$(shell grep '^OPENAI_API_KEY=' .env | cut -d= -f2) \
	OPENAI_BASE_URL=$(shell grep '^OPENAI_BASE_URL=' .env | cut -d= -f2) \
	OPENAI_MODEL=$(shell grep '^OPENAI_MODEL=' .env | cut -d= -f2) \
	PSE_MODEL_STREAM=true \
	PSE_TIMEOUT=300 \
	$(PY) tasks/portfolio-review/run.py

review-agnes: _auto-summarize ## 用 Agnes 2.0 Flash 跑周报（非流式，免费，放宽循环参数）
	OPENAI_API_KEY=$(shell grep '^AGNES_KEY=' .env | cut -d= -f2) \
	OPENAI_BASE_URL=$(shell grep '^AGNES_BASE_URL=' .env | cut -d= -f2) \
	OPENAI_MODEL=$(shell grep '^AGNES_MODEL=' .env | cut -d= -f2) \
	PSE_MODEL_STREAM=false \
	PSE_TURNS_PER_CYCLE=25 \
	PSE_MAX_PARTIAL_RETRIES=5 \
	PSE_TIMEOUT=300 \
	$(PY) tasks/portfolio-review/run.py

review-kimi: _auto-summarize ## ⚠️ Kimi-K2.6 推理模型输出在 reasoning_content 中，周报质量不佳，建议用 MiniMax 替代
	OPENAI_API_KEY=$(shell sed -n 's/^SCNET_KEY=//p' .env) \
	OPENAI_BASE_URL=$(shell sed -n 's/^SCNET_BASE_URL=//p' .env) \
	OPENAI_MODEL=$(shell sed -n 's/^SCNET_KIMI_MODEL=//p' .env) \
	PSE_MODEL_STREAM=false \
	PSE_TURNS_PER_CYCLE=25 \
	PSE_MAX_PARTIAL_RETRIES=3 \
	PSE_TIMEOUT=300 \
	$(PY) tasks/portfolio-review/run.py

review-minimax: _auto-summarize ## 用 MiniMax M2.5 跑周报（SCNet，非流式）
	OPENAI_API_KEY=$(shell sed -n 's/^SCNET_KEY=//p' .env) \
	OPENAI_BASE_URL=$(shell sed -n 's/^SCNET_BASE_URL=//p' .env) \
	OPENAI_MODEL=$(shell sed -n 's/^SCNET_MINIMAX_MODEL=//p' .env) \
	PSE_MODEL_STREAM=false \
	PSE_TURNS_PER_CYCLE=25 \
	PSE_MAX_PARTIAL_RETRIES=3 \
	PSE_TIMEOUT=300 \
	$(PY) tasks/portfolio-review/run.py

# 绑定守卫：仅在对外暴露（0.0.0.0）且未设 WEB_AUTH_TOKEN 时拒绝启动
guard-bind:
	@if [ "$(WEB_BIND_HOST)" = "0.0.0.0" ] && ! grep -q '^WEB_AUTH_TOKEN=' .env 2>/dev/null; then \
		echo "❌ 拒绝绑定 0.0.0.0：未设置 WEB_AUTH_TOKEN。本机访问用 make serve，或先设 WEB_AUTH_TOKEN 再 make serve WEB_BIND_HOST=0.0.0.0"; exit 1; \
	fi

serve: guard-bind serve-web ## 启动 Web Dashboard（默认仅本机 127.0.0.1）
serve-web: web-build
	$(PY) -m uvicorn web_server:app --host $(WEB_BIND_HOST) --port 8080

dev: guard-bind kill ## 开发模式：先杀旧进程，再启动 FastAPI + Vite
	$(PY) -m uvicorn web_server:app --host $(WEB_BIND_HOST) --port 8080 &
	@sleep 2
	cd web && npm run dev

web-build: ## 构建前端
	cd web && npm install --silent && npm run build

kill: ## 杀掉开发服务器进程（8080 / 5173）
	@lsof -ti:8080 | xargs kill -9 2>/dev/null && echo "✅ 已杀掉 :8080" || echo "  :8080 无进程"
	@lsof -ti:5173 | xargs kill -9 2>/dev/null && echo "✅ 已杀掉 :5173" || echo "  :5173 无进程"
