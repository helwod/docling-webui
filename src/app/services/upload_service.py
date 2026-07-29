import os
import zipfile
import io
import shutil
from fastapi import UploadFile, HTTPException
from typing import List
from app.config import settings
from app.utils.file_utils import is_allowed_file, generate_stored_path, ensure_dir


class UploadService:
    def __init__(self):
        self.upload_dir = settings.upload_dir
        ensure_dir(self.upload_dir)
        self.max_file_size = settings.max_file_size_mb * 1024 * 1024
        self.max_zip_size = settings.max_zip_size_mb * 1024 * 1024
        self.max_files = settings.max_files_per_batch

    async def handle_upload(self, files: List[UploadFile]) -> tuple[list[dict], list[dict]]:
        """返回 (已接受文件列表, 被拒绝文件列表)。被拒绝的文件带原因，绝不静默丢弃。"""
        if not files:
            raise HTTPException(status_code=400, detail={"code": 400, "message": "No files provided"})

        if len(files) == 1 and self._is_zip_filename(files[0].filename):
            return await self._process_zip(files[0])

        result = []
        rejected = []
        for file in files:
            if not file.filename:
                rejected.append({"filename": "<未知>", "reason": "文件名为空"})
                continue
            if not is_allowed_file(file.filename):
                rejected.append({
                    "filename": file.filename,
                    "reason": "不支持的文件类型",
                })
                continue
            content = await file.read()
            if len(content) > self.max_file_size:
                rejected.append({
                    "filename": file.filename,
                    "reason": f"超过单文件大小上限（{settings.max_file_size_mb}MB）",
                })
                continue
            stored_path = generate_stored_path(self.upload_dir, file.filename)
            async with self._open_write(stored_path) as f:
                await f.write(content)
            result.append({
                "original_filename": file.filename,
                "stored_path": stored_path,
                "file_size": len(content),
                "file_type": self._get_mime_type(file.filename),
            })

        if not result:
            if rejected:
                names = "、".join(r["filename"] for r in rejected)
                raise HTTPException(
                    status_code=400,
                    detail={"code": 400, "message": f"没有可处理的文件，已跳过：{names}"},
                )
            raise HTTPException(
                status_code=400,
                detail={"code": 400, "message": "No valid files found"},
            )
        return result, rejected

    async def _process_zip(self, zip_file: UploadFile) -> tuple[list[dict], list[dict]]:
        content = await zip_file.read()
        if len(content) > self.max_zip_size:
            raise HTTPException(
                status_code=413,
                detail={"code": 413, "message": "ZIP file exceeds max size"},
            )

        result = []
        rejected = []
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                all_info = zf.infolist()
                all_info = [i for i in all_info if not i.is_dir()]

                if len(all_info) > self.max_files:
                    raise HTTPException(
                        status_code=400,
                        detail={"code": 400, "message": f"ZIP contains more than {self.max_files} files"},
                    )

                total_estimated = sum(i.file_size for i in all_info)
                if total_estimated > self.max_zip_size:
                    raise HTTPException(
                        status_code=413,
                        detail={"code": 413, "message": "Estimated total size exceeds max size"},
                    )

                for info in all_info:
                    filename = info.filename
                    if self._is_path_traversal(filename):
                        rejected.append({"filename": filename, "reason": "路径穿越，已跳过"})
                        continue
                    basename = os.path.basename(filename)
                    if not basename:
                        rejected.append({"filename": filename, "reason": "无效文件名，已跳过"})
                        continue
                    if not is_allowed_file(basename):
                        rejected.append({
                            "filename": basename,
                            "reason": "不支持的文件类型，已跳过",
                        })
                        continue

                    # Zip bomb check
                    if info.compress_size > 0:
                        ratio = info.file_size / info.compress_size
                        if ratio > 100:
                            raise HTTPException(
                                status_code=400,
                                detail={"code": 400, "message": f"Zip bomb detected in {filename}"},
                            )

                    file_content = zf.read(info)
                    stored_path = generate_stored_path(self.upload_dir, basename)
                    async with self._open_write(stored_path) as f:
                        await f.write(file_content)

                    result.append({
                        "original_filename": basename,
                        "stored_path": stored_path,
                        "file_size": len(file_content),
                        "file_type": self._get_mime_type(basename),
                    })
        except zipfile.BadZipFile:
            raise HTTPException(
                status_code=400,
                detail={"code": 400, "message": "Invalid ZIP file"},
            )

        if not result:
            if rejected:
                names = "、".join(r["filename"] for r in rejected)
                raise HTTPException(
                    status_code=400,
                    detail={"code": 400, "message": f"压缩包内没有可处理的文件，已跳过：{names}"},
                )
            raise HTTPException(
                status_code=400,
                detail={"code": 400, "message": "No valid files found in ZIP"},
            )
        return result, rejected

    def _is_zip_filename(self, filename: str) -> bool:
        if not filename:
            return False
        return filename.lower().endswith(".zip")

    def _is_path_traversal(self, path: str) -> bool:
        normalized = os.path.normpath(path).replace("\\", "/")
        return normalized.startswith("..") or normalized.startswith("/") or (
            len(normalized) > 1 and normalized[1] == ":"
        )

    def _get_mime_type(self, filename: str) -> str:
        ext = os.path.splitext(filename)[1].lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
            ".bmp": "image/bmp",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".html": "text/html",
            ".htm": "text/html",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".csv": "text/csv",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xml": "application/xml",
            ".asciidoc": "text/plain",
        }
        return mime_map.get(ext, "application/octet-stream")

    def _open_write(self, path: str):
        import aiofiles
        return aiofiles.open(path, "wb")

    async def cleanup_files(self, stored_paths: list[str]) -> None:
        for path in stored_paths:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass

    def get_upload_dir(self) -> str:
        return self.upload_dir
