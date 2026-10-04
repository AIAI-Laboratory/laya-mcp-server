FROM python:3.11-slim-bookworm
LABEL org.opencontainers.image.authors="htrnguyen" \
      org.opencontainers.image.title="Laya MCP Server" \
      org.opencontainers.image.description="Local CPU classification over MCP and REST" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 USE_TF=0 TOKENIZERS_PARALLELISM=false HF_HOME=/data/models TORCH_DISABLE_NATIVE_JIT=1
RUN pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt /app/requirements.txt
COPY vendor/laya /app/laya
RUN pip install -r /app/requirements.txt '/app/laya[serve,mcp]' && pip check && pip freeze > /app/build-packages.txt
COPY server.py web_docs.py mcp_http.py observability.py decisions.py /app/
COPY VERSION /app/VERSION
COPY scripts/verify_mcp.py /app/scripts/verify_mcp.py
COPY static /app/static
COPY examples /app/examples
COPY docs/AGENT_GUIDE.md /app/docs/AGENT_GUIDE.md
COPY skills/laya-mcp-server/SKILL.md /app/skills/laya-mcp-server/SKILL.md
COPY assets/logo.png /app/assets/logo.png
WORKDIR /app
CMD ["python", "server.py"]
