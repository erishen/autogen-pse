.PHONY: help demo review summarize market lint fix test dev serve kill

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

review: summarize ## 生成摘要并运行 PSE 投资周报分析
	$(CLI) run portfolio-review --skip-prepare

serve: web-build ## 启动 Web Dashboard（http://localhost:8080）
	$(PY) -m uvicorn web_server:app --host 0.0.0.0 --port 8080

dev: kill ## 开发模式：先杀旧进程，再启动 FastAPI + Vite
	$(PY) -m uvicorn web_server:app --host 0.0.0.0 --port 8080 &
	cd web && npm run dev

web-build: ## 构建前端
	cd web && npm install --silent && npm run build

kill: ## 杀掉开发服务器进程（8080 / 5173）
	@lsof -ti:8080 | xargs kill -9 2>/dev/null && echo "✅ 已杀掉 :8080" || echo "  :8080 无进程"
	@lsof -ti:5173 | xargs kill -9 2>/dev/null && echo "✅ 已杀掉 :5173" || echo "  :5173 无进程"
