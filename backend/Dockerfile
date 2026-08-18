FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# 依赖按锁定的 requirements.txt 安装（由 uv export 生成，随代码提交）
COPY requirements.txt .
RUN pip install -U pip uv && uv venv /srv/.venv && VIRTUAL_ENV=/srv/.venv uv pip install -r requirements.txt

COPY app ./app
COPY alembic ./alembic

ENV PATH="/srv/.venv/bin:$PATH"
# 默认启动 API；worker/beat/relay 由 compose 覆盖 command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
