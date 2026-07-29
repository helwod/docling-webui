import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db.database import get_db, close_db
from app.config import settings
from app.routers import batches, files, config as config_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    db = await get_db()
    logger.info("Database initialized")

    # 启动恢复：将中断的 processing 批次重置为 created，交给调度器自动续跑
    try:
        from app.repositories.batch_repo import BatchRepo
        repo = BatchRepo(db)
        processing = await repo.get_batches_by_status("processing")
        for b in processing:
            logger.info(f"Recovery: resetting batch {b['id'][:8]} from processing to created")
            await repo.update_status(b["id"], "created")
        if processing:
            logger.info(f"Recovery: reset {len(processing)} orphaned processing batches")
    except Exception as e:
        logger.warning(f"Recovery check failed (non-fatal): {e}")

    # 启动全局队列调度器：paused=0 的 created 批次按 priority DESC, created_at ASC 拉起
    from app.repositories.batch_repo import BatchRepo
    from app.repositories.file_repo import FileRepo
    from app.repositories.setting_repo import SettingRepo
    from app.services.queue_scheduler import QueueScheduler

    scheduler = QueueScheduler(BatchRepo(db), FileRepo(db), SettingRepo(db))
    await scheduler.start()
    app.state.queue_scheduler = scheduler

    yield
    logger.info("Stopping queue scheduler...")
    await scheduler.stop()
    logger.info("Closing database...")
    await close_db()
    logger.info("Database closed")


app = FastAPI(
    title="Docling Serve WebUI API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 反向代理子路径前缀（例如 /docling）。为空则保持根路径，向后兼容。
_raw = os.getenv("APP_ROOT_PATH", "").strip().strip("/")
ROOT_PATH = ("/" + _raw) if _raw else ""

# Register routers
app.include_router(batches.router, prefix=ROOT_PATH)
app.include_router(files.router, prefix=ROOT_PATH)
app.include_router(config_router.router, prefix=ROOT_PATH)


@app.get(ROOT_PATH + "/api/v1/health")
async def health_check():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# 静态前端（原生网页，多页面，由本服务同源托管）
# 目录：与 src/app 同级（已合并到本仓库 src/ 目录下）
#   /                -> 上传并解析（默认首页）
#   /tasks           -> 任务列表
#   /task?batch_id=  -> 任务详情
#   /settings        -> 设置
# ---------------------------------------------------------------------------
FRONTEND_DIR = Path(__file__).resolve().parent.parent


def _serve_page(filename: str):
    async def _handler():
        return FileResponse(FRONTEND_DIR / filename, media_type="text/html; charset=utf-8")

    return _handler


app.get(ROOT_PATH + "/")(_serve_page("index.html"))
app.get(ROOT_PATH + "/tasks")(_serve_page("tasks.html"))
app.get(ROOT_PATH + "/task")(_serve_page("task.html"))
app.get(ROOT_PATH + "/settings")(_serve_page("settings.html"))

# 静态资源（CSS/JS）
app.mount(ROOT_PATH + "/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="frontend-assets")
