import os
import json
import tempfile
import zipfile
import csv
import io
from typing import List
from urllib.parse import quote
from fastapi.responses import StreamingResponse
from fastapi import BackgroundTasks


class ExportService:
    def __init__(self, upload_dir: str):
        self.upload_dir = upload_dir

    def export_batch(
        self,
        batch: dict,
        files: List[dict],
        format: str = "both",
    ) -> StreamingResponse:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        tmp_path = tmp.name
        tmp.close()

        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, f in enumerate(files):
                prefix = f"{idx + 1:04d}_{os.path.splitext(f['original_filename'])[0]}"

                # original image
                stored_path = f.get("stored_path", "")
                if stored_path and os.path.isfile(stored_path):
                    zf.write(stored_path, f"original_images/{prefix}{os.path.splitext(f['original_filename'])[1]}")

                # OCR results
                md_content = f.get("ocr_md_content")
                if md_content:
                    zf.writestr(f"ocr_results/{prefix}.md", md_content)

                json_content = f.get("ocr_json_content")
                if json_content:
                    zf.writestr(f"ocr_results/{prefix}.json", json_content)

                # LLM results
                llm_result = f.get("llm_result")
                if llm_result and f.get("llm_status") == "completed":
                    try:
                        llm_data = json.loads(llm_result) if isinstance(llm_result, str) else llm_result
                        zf.writestr(
                            f"llm_tables/{prefix}_tables.json",
                            json.dumps(llm_data, ensure_ascii=False, indent=2),
                        )
                        if format in ("csv", "both"):
                            self._write_csv(zf, f"llm_tables/{prefix}_tables.csv", llm_data)
                    except (json.JSONDecodeError, TypeError):
                        zf.writestr(f"llm_tables/{prefix}_tables.json", str(llm_result))

            # summary.json
            summary = {
                "batch_id": batch["id"],
                "batch_name": batch["name"],
                "status": batch["status"],
                "total_files": batch["total_files"],
                "processed_files": batch["processed_files"],
                "created_at": batch["created_at"],
                "updated_at": batch["updated_at"],
                "files": [
                    {
                        "id": f["id"],
                        "filename": f["original_filename"],
                        "ocr_status": f["ocr_status"],
                        "llm_status": f["llm_status"],
                    }
                    for f in files
                ],
            }
            zf.writestr("summary.json", json.dumps(summary, ensure_ascii=False, indent=2))

        # Streaming response
        def iterfile():
            with open(tmp_path, "rb") as f:
                yield from f

        background_tasks = BackgroundTasks()
        background_tasks.add_task(self._cleanup, tmp_path)

        filename_safe = batch["name"].replace(" ", "_").replace("/", "_")
        encoded_filename = quote(f"{filename_safe}.zip")
        return StreamingResponse(
            iterfile(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
                "Content-Type": "application/zip",
            },
            background=background_tasks,
        )

    def export_single_file(
        self,
        file_data: dict,
        format: str = "both",
    ) -> StreamingResponse:
        batch = {"id": file_data.get("batch_id", ""), "name": file_data.get("original_filename", "file"),
                 "status": file_data.get("ocr_status", ""), "total_files": 1,
                 "processed_files": 0, "created_at": file_data.get("created_at", ""),
                 "updated_at": file_data.get("updated_at", "")}
        return self.export_batch(batch, [file_data], format)

    def _write_csv(self, zf: zipfile.ZipFile, path: str, llm_data: dict):
        tables = llm_data.get("tables", [])
        if not tables:
            return
        for table in tables:
            headers = table.get("headers", [])
            rows = table.get("rows", [])
            if not headers and not rows:
                continue

            output = io.StringIO()
            # Write BOM for Excel compatibility
            output.write("\ufeff")
            writer = csv.writer(output)
            if headers:
                writer.writerow(headers)
            for row in rows:
                writer.writerow([row.get(h, "") for h in headers])
            zf.writestr(path, output.getvalue())
            break  # Only write first table to CSV

    def _cleanup(self, path: str):
        try:
            os.unlink(path)
        except OSError:
            pass
