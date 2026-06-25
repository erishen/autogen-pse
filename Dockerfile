FROM node:22-slim AS frontend
WORKDIR /build
COPY web/package.json ./
RUN npm install
COPY web/ .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

RUN pip install uv

COPY pyproject.toml README.md src/ ./
RUN uv sync --no-dev

COPY tasks/ tasks/
COPY cli.py web_server.py ./
COPY --from=frontend /build/dist web/dist

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "web_server:app", "--host", "0.0.0.0", "--port", "8080"]
