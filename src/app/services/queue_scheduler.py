"""全局批次队列调度器。

职责：
- 周期性扫描数据库，取出「待处理且未暂停」的批次（status='created' AND paused=0），
  按 priority DESC、created_at ASC 排序（置顶优先，其次先入队先处理 FIFO）。
- 并发上限由设置 max_concurrent_conversions 控制。
- 在 FastAPI lifespan 中 start() / stop()；启动恢复重置为 created 的批次会被
  本调度器自然接续处理，无需额外触发。
- pause_batch / pin_batch 写入的 paused / priority 字段在这里被真正消费。
"""

import asyncio
import logging

from app.repositories.batch_repo import BatchRepo
from app.repositories.file_repo import FileRepo
from app.repositories.setting_repo import SettingRepo
from app.services.docling_service import DoclingService
from app.services.llm_service import LLMService
from app.services.task_poller import TaskPoller

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CONCURRENT = 5
_DEFAULT_POLL_INTERVAL = 2


class QueueScheduler:
    def __init__(
        self,
        batch_repo: BatchRepo,
        file_repo: FileRepo,
        setting_repo: SettingRepo,
    ):
        self._batch_repo = batch_repo
        self._setting_repo = setting_repo
        self._poller = TaskPoller(
            batch_repo,
            file_repo,
            setting_repo,
            DoclingService(setting_repo),
            LLMService(setting_repo),
        )
        self._running: dict[str, asyncio.Task] = {}
        self._loop_task: asyncio.Task | None = None
        self._stopped = False

    async def start(self):
        if self._loop_task is None or self._loop_task.done():
            self._stopped = False
            self._loop_task = asyncio.create_task(self._loop())
            logger.info("QueueScheduler started")

    async def stop(self):
        self._stopped = True
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
        for task in self._running.values():
            task.cancel()
        self._running.clear()
        logger.info("QueueScheduler stopped")

    async def _loop(self):
        while not self._stopped:
            try:
                await self._tick()
            except Exception as e:
                logger.warning(f"QueueScheduler tick error (non-fatal): {e}")
            try:
                interval = int(
                    await self._setting_repo.get("poll_interval_seconds")
                    or _DEFAULT_POLL_INTERVAL
                )
            except Exception:
                interval = _DEFAULT_POLL_INTERVAL
            await asyncio.sleep(max(1, interval))

    async def _tick(self):
        # 清理已完成的运行记录
        done = [bid for bid, t in self._running.items() if t.done()]
        for bid in done:
            exc = self._running[bid].exception() if not self._running[bid].cancelled() else None
            if exc:
                logger.error(f"Batch {bid[:8]} processing task ended with error: {exc}")
            self._running.pop(bid, None)

        try:
            max_conc = int(
                await self._setting_repo.get("max_concurrent_conversions")
                or _DEFAULT_MAX_CONCURRENT
            )
        except Exception:
            max_conc = _DEFAULT_MAX_CONCURRENT

        capacity = max(0, max_conc - len(self._running))
        if capacity <= 0:
            return

        queued = await self._batch_repo.get_next_queued(capacity)
        for batch in queued:
            bid = batch["id"]
            if bid in self._running:
                continue
            enable_llm = bool(batch.get("enable_llm", 1))
            logger.info(f"QueueScheduler: starting batch {bid[:8]} (enable_llm={enable_llm})")
            self._running[bid] = asyncio.create_task(
                self._poller.process_batch(bid, enable_llm)
            )
