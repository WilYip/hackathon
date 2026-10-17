# Usland 的容器镜像（Zenith 用它来构建和运行；本地有 Docker 时也可以直接用）。
#
# - 应用监听 0.0.0.0:8080，日志输出到 stdout / stderr
# - 数据（SQLite 数据库、上传的照片、自动生成的 SECRET_KEY）都在 /app/data，
#   由 zenith-compose.yml 挂一个持久卷上去；镜像里不带任何数据和 .env
# - gunicorn 只开 1 个进程 + 多线程：SQLite 和"启动时建表 / 生成密钥"都只适合单进程
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/app/data \
    PORT=8080 \
    TRUST_PROXY=1

WORKDIR /app

# 先只装依赖：代码改了但依赖没变时，这一层可以复用，构建更快
COPY requirements.txt .
RUN pip install -r requirements.txt

# 再复制代码（.dockerignore 排除了 .env、.venv、data/、测试和文档）
COPY . .

# 用普通用户运行；先建好数据目录并交给这个用户，新挂上的卷会沿用这个属主
RUN useradd --create-home --uid 10001 usland \
    && mkdir -p /app/data \
    && chown -R usland:usland /app/data
USER usland

EXPOSE 8080

# 单进程 8 线程；超时放宽到 60 秒（温柔传话要等 DeepSeek，最长 20 秒）
CMD ["sh", "-c", "exec gunicorn --workers 1 --threads 8 --timeout 60 --bind 0.0.0.0:${PORT} --access-logfile - --error-logfile - 'app:create_app()'"]
