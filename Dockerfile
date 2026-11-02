# 本地/服务器工作台；WITH_RAG=true 加装 CPU 语义模型依赖。
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 RAG_PROJECT_ROOT=/app
ARG WITH_RAG=false

# GitHub skill imports use a quarantined git clone; no repository code is run.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY scripts ./scripts
RUN pip install --no-cache-dir '.[web]' && \
    if [ "$WITH_RAG" = "true" ]; then \
      pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
      pip install --no-cache-dir '.[rag]'; \
    fi

RUN useradd --create-home --uid 10001 workspace && \
    mkdir -p data/local output/stages /home/workspace/.cache/huggingface && \
    chown -R workspace:workspace /app /home/workspace/.cache
USER workspace

EXPOSE 8000
CMD ["uvicorn", "rag_tech_retriever.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
