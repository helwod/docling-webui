import asyncio
import json
import logging
from typing import Optional

from app.repositories.batch_repo import BatchRepo
from app.repositories.file_repo import FileRepo
from app.repositories.setting_repo import SettingRepo
from app.services.docling_service import DoclingService
from app.services.llm_service import LLMService, persist_batch_table

logger = logging.getLogger(__name__)


class TaskPoller:
    def __init__(
        self,
        batch_repo: BatchRepo,
        file_repo: FileRepo,
        setting_repo: SettingRepo,
        docling_service: DoclingService,
        llm_service: LLMService,
    ):
        self.batch_repo = batch_repo
        self.file_repo = file_repo
        self.setting_repo = setting_repo
        self.docling_service = docling_service
        self.llm_service = llm_service
        self._tasks: dict[str, asyncio.Task] = {}
        self._enable_llm = True

    def set_enable_llm(self, value: bool):
        self._enable_llm = value

    async def start_processing(self, batch_id: str, enable_llm: bool = True):
        if batch_id in self._tasks and not self._tasks[batch_id].done():
            return
        self._enable_llm = enable_llm
        task = asyncio.create_task(self._process_batch(batch_id, enable_llm))
        self._tasks[batch_id] = task

    async def process_batch(self, batch_id: str, enable_llm: bool = True):
        """公开入口：处理单个批次（由 QueueScheduler 调用并自行跟踪任务）。"""
        await self._process_batch(batch_id, enable_llm)

    async def _process_batch(self, batch_id: str, enable_llm: bool = True):
        try:
            batch = await self.batch_repo.get_by_id(batch_id)
            if not batch:
                logger.error(f"Batch {batch_id} not found")
                return

            await self.batch_repo.update_status(batch_id, "processing")

            # 仅挑出需要 OCR 的文件：未处理(pending) 或 失败(failed)；已完成的不重复消耗
            ocr_targets = await self.file_repo.get_pending_ocr_files(batch_id)
            if not ocr_targets:
                ocr_targets = await self.file_repo.get_failed_ocr_files(batch_id)

            if ocr_targets:
                total = len(ocr_targets)
                completed_count = 0

                for file_record in ocr_targets:
                    file_id = file_record["id"]
                    stored_path = file_record["stored_path"]

                    # OCR phase
                    await self.file_repo.update_ocr_status(file_id, "processing")
                    ocr_result = await self.docling_service.convert_file(
                        stored_path, file_record["original_filename"]
                    )

                    if not ocr_result["success"]:
                        await self.file_repo.update_ocr_status(
                            file_id, "failed",
                            ocr_error=ocr_result.get("error", "Unknown error"),
                        )
                    else:
                        await self.file_repo.update_ocr_status(
                            file_id, "completed",
                            ocr_md_content=ocr_result.get("md_content", ""),
                            ocr_json_content=ocr_result.get("json_content"),
                            ocr_html_content=ocr_result.get("html_content"),
                            ocr_task_id=ocr_result.get("task_id", ""),
                            ocr_processing_time=0.0,
                        )

                        # 每文件不做单独 LLM；汇总表在最终阶段统一生成
                        await self.file_repo.update_llm_status(file_id, "skipped")

                    completed_count += 1
                    await self.batch_repo.update_processed_count(batch_id)

            # Check if all files are done（收尾批次状态 completed/failed）
            await self._finalize_batch(batch_id)

            # LLM 汇总表（批次级）：只要开启 LLM 且存在 OCR 已完成文件就重建，
            # 覆盖「重跑部分 OCR 文件」与「仅 LLM 未生成/失败」两种场景。
            if enable_llm:
                files = await self.file_repo.get_all_for_consolidated(batch_id)
                completed = [f for f in files if f.get("ocr_status") == "completed"]
                if completed:
                    await self._generate_batch_table(batch_id)

        except Exception as e:
            logger.exception(f"Error processing batch {batch_id}: {e}")
            try:
                await self.batch_repo.update_status(batch_id, "failed")
            except Exception:
                pass

    async def _finalize_batch(self, batch_id: str):
        counts = await self.file_repo.get_status_counts(batch_id)
        total = counts.get("total", 0)
        ocr_failed = counts.get("ocr_failed", 0)
        ocr_pending = counts.get("ocr_pending", 0)

        # 以绝对计数修正 processed_files（重跑时只重跑部分文件，避免累加超 100%）
        await self.batch_repo.update_processed_count(batch_id)

        if ocr_pending == 0:
            if ocr_failed == total:
                await self.batch_repo.update_status(batch_id, "failed")
            else:
                await self.batch_repo.update_status(batch_id, "completed")

    async def _generate_batch_table(self, batch_id: str):
        """批次 OCR 完成后，统一调用 LLM 生成『一张表，每行=一个文件』的汇总表。"""
        try:
            files = await self.file_repo.get_all_for_consolidated(batch_id)
            if not files:
                return
            completed = [f for f in files if f.get("ocr_status") == "completed"]
            if not completed:
                # 无可整理内容，清空汇总表
                await self.batch_repo.update_batch_table(batch_id, None)
                return

            result = await self.llm_service.format_batch_table(files)
            out = await persist_batch_table(self.batch_repo, batch_id, result)
            if out["skipped"]:
                return
            if out["success"]:
                logger.info(
                    f"Batch table generated for {batch_id} (model={result.get('model')}); "
                    f"prompt {len(result.get('prompt') or '')} chars, reply {len(result.get('raw_reply') or '')} chars recorded."
                )
            else:
                logger.warning(f"Batch table generation failed for {batch_id}: {result.get('error')}")
        except Exception as e:
            logger.exception(f"Batch table generation failed for {batch_id}: {e}")

    async def get_status(self, batch_id: str) -> Optional[dict]:
        batch = await self.batch_repo.get_by_id(batch_id)
        if not batch:
            return None

        counts = await self.file_repo.get_status_counts(batch_id)
        total = counts.get("total", 0) or 1
        ocr_completed = counts.get("ocr_completed", 0)
        ocr_failed = counts.get("ocr_failed", 0)
        ocr_pending = counts.get("ocr_pending", 0)
        llm_completed = counts.get("llm_completed", 0)
        llm_failed = counts.get("llm_failed", 0)
        llm_pending = counts.get("llm_pending", 0)

        total_done = ocr_completed + ocr_failed
        progress = (total_done / total) * 100 if total > 0 else 0

        return {
            "batch_id": batch_id,
            "batch_status": batch["status"],
            "total_files": total,
            "ocr_completed": ocr_completed,
            "ocr_failed": ocr_failed,
            "ocr_pending": ocr_pending,
            "llm_completed": llm_completed,
            "llm_failed": llm_failed,
            "llm_pending": llm_pending,
            "progress_percent": round(progress, 1),
        }
