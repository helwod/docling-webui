# ----------------------------------------------------------------------------
# Docling Serve WebUI — 镜像构建
# 说明：本镜像只打包 WebUI（FastAPI 后端 + 静态前端）。
#       Docling Serve（OCR 引擎）是独立服务，需另行运行并通过
#       DOCLING_BASE_URL 指向它（见 docker-compose.yml 或 -e 传入）。
# 构建：docker build -t docling-webui .
# 运行：docker run -p 8001:8001 -e DOCLING_BASE_URL=http://<host>:5001 docling-webui
# ----------------------------------------------------------------------------
FROM python:3.11-slim

# 不缓冲 Python 输出，方便看日志；不写 __pycache__
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8001

WORKDIR /app/src

# 先装依赖，利用 Docker 层缓存（仅 requirements.txt 变动时才重装）
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码与前端静态资源（前端已合并到 src/ 下）
# （.dockerignore 已排除 .env / data / uploads / __pycache__ 等）
COPY src/ ./

# 用示例配置生成默认 .env（容器内可被 -e 环境变量覆盖，优先级更高）
COPY src/.env.example ./.env

# 数据与上传目录用卷持久化，避免重建容器丢失
VOLUME ["/app/src/data", "/app/src/uploads"]

EXPOSE 8001

# 健康检查：探测后端 API
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/api/v1/health').status==200 else 1)" || exit 1

# PORT 可被 -e PORT=xxxx 覆盖；默认 8001
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
