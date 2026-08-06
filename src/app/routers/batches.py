from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import List, Optional
import os
import io
import base64
import mimetypes
import tempfile
import zipfile
from urllib.parse import quote
import csv
import json

from app.db.database import get_db
from app.repositories.batch_repo import BatchRepo
from app.repositories.file_repo import FileRepo
from app.repositories.setting_repo import SettingRepo
from app.models.schemas import (
    ApiResponse,
    BatchResponse,
    BatchListData,
    FileListData,
    FileListItem,
    FileDetailResponse,
    ProcessRequest,
    ProcessStatusData,
    ProcessStatusResponse,
)
from app.services.upload_service import UploadService
from app.services.export_service import ExportService
from app.services.llm_service import LLMService, persist_batch_table
from app.config import settings as config_settings

router = APIRouter(prefix="/api/v1/batches", tags=["batches"])


def get_upload_service() -> UploadService:
    return UploadService()


def get_export_service() -> ExportService:
    return ExportService(config_settings.upload_dir)


async def get_repos(db=Depends(get_db)):
    return {
        "batch_repo": BatchRepo(db),
        "file_repo": FileRepo(db),
        "setting_repo": SettingRepo(db),
    }


@router.post("", status_code=201)
async def create_batch(
    files: List[UploadFile] = File(...),
    name: Optional[str] = Form(None),
    enable_llm: bool = Form(True),
    repos=Depends(get_repos),
):
    upload_service = get_upload_service()
    file_infos, rejected = await upload_service.handle_upload(files)

    batch_name = name or (files[0].filename if files[0].filename else "Batch")
    batch_name = os.path.splitext(batch_name)[0] if batch_name else "Batch"

    is_zip = (
        len(files) == 1
        and files[0].filename
        and files[0].filename.lower().endswith(".zip")
    )
    source_type = "zip" if is_zip else "files"
    batch = await repos["batch_repo"].create(
        batch_name, source_type, enable_llm=1 if enable_llm else 0
    )

    for fi in file_infos:
        await repos["file_repo"].create(
            batch_id=batch["id"],
            original_filename=fi["original_filename"],
            stored_path=fi["stored_path"],
            file_size=fi["file_size"],
            file_type=fi["file_type"],
        )

    total = await repos["file_repo"].count_by_batch(batch["id"])
    db = await get_db()
    await db.execute(
        "UPDATE batches SET total_files = ? WHERE id = ?", (total, batch["id"])
    )
    await db.commit()
    batch_data = await repos["batch_repo"].get_by_id(batch["id"])

    return ApiResponse(data=BatchResponse(**batch_data, rejected_files=rejected))


@router.get("")
async def list_batches(
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
    repos=Depends(get_repos),
):
    batches_list, total = await repos["batch_repo"].list(page, limit, status)
    items = [BatchResponse(**b) for b in batches_list]
    has_more = (page * limit) < total
    return ApiResponse(
        data=BatchListData(
            items=items, total=total, page=page, limit=limit, has_more=has_more
        )
    )


@router.get("/{batch_id}")
async def get_batch(batch_id: str, repos=Depends(get_repos)):
    batch = await repos["batch_repo"].get_by_id(batch_id)
    if not batch:
        raise HTTPException(
            status_code=404, detail={"code": 404, "message": "Batch not found"}
        )
    return ApiResponse(data=BatchResponse(**batch))


async def _purge_batch_files(batch_id: str) -> None:
    """删除批次下所有文件的物理存储（在 soft_delete 之后调用）。"""
    db = await get_db()
    cursor = await db.execute(
        "SELECT stored_path FROM files WHERE batch_id = ?", (batch_id,)
    )
    rows = await cursor.fetchall()
    paths = [r[0] for r in rows if r[0]]
    for path in paths:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


@router.delete("/{batch_id}")
async def delete_batch(batch_id: str, repos=Depends(get_repos)):
    batch = await repos["batch_repo"].get_by_id(batch_id)
    if not batch:
        raise HTTPException(
            status_code=404, detail={"code": 404, "message": "Batch not found"}
        )

    await repos["batch_repo"].soft_delete(batch_id)
    await _purge_batch_files(batch_id)

    return ApiResponse(data={"success": True})


@router.post("/batch-delete")
async def batch_delete(ids: List[str], repos=Depends(get_repos)):
    """批量删除批次。"""
    for bid in ids:
        batch = await repos["batch_repo"].get_by_id(bid)
        if not batch:
            continue
        await repos["batch_repo"].soft_delete(bid)
        await _purge_batch_files(bid)
    return ApiResponse(data={"success": True, "deleted": len(ids)})


@router.post("/{batch_id}/pause")
async def pause_batch(batch_id: str, repos=Depends(get_repos)):
    """暂停/恢复批次（仅对 created 状态有效）。"""
    batch = await repos["batch_repo"].get_by_id(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Batch not found"})
    if batch["status"] != "created":
        raise HTTPException(status_code=409, detail={"code": 409, "message": "只能暂停未开始的批次"})

    db = await get_db()
    paused = batch.get("paused", 0) or 0
    new_paused = 0 if paused else 1
    await db.execute("UPDATE batches SET paused = ? WHERE id = ?", (new_paused, batch_id))
    await db.commit()
    return ApiResponse(data={"success": True, "paused": bool(new_paused)})


@router.post("/{batch_id}/pin")
async def pin_batch(batch_id: str, repos=Depends(get_repos)):
    """置顶批次（设置最高优先级）。"""
    batch = await repos["batch_repo"].get_by_id(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Batch not found"})

    db = await get_db()
    max_pri = await db.execute(
        "SELECT COALESCE(MAX(priority), 0) + 1 FROM batches "
        "WHERE status = 'created' AND deleted_at IS NULL"
    )
    row = await max_pri.fetchone()
    next_pri = row[0] if row else 1
    await db.execute("UPDATE batches SET priority = ? WHERE id = ?", (next_pri, batch_id))
    await db.commit()
    return ApiResponse(data={"success": True, "priority": next_pri})


@router.get("/{batch_id}/files")
async def list_batch_files(
    batch_id: str,
    page: int = 1,
    limit: int = 20,
    repos=Depends(get_repos),
):
    batch = await repos["batch_repo"].get_by_id(batch_id)
    if not batch:
        raise HTTPException(
            status_code=404, detail={"code": 404, "message": "Batch not found"}
        )

    files_list, total = await repos["file_repo"].list_by_batch(
        batch_id, page, limit
    )
    items = [FileListItem(**f) for f in files_list]
    has_more = (page * limit) < total
    return ApiResponse(
        data=FileListData(
            items=items, total=total, page=page, limit=limit, has_more=has_more
        )
    )


@router.get("/{batch_id}/files/{file_id}")
async def get_file_detail(batch_id: str, file_id: str, repos=Depends(get_repos)):
    batch = await repos["batch_repo"].get_by_id(batch_id)
    if not batch:
        raise HTTPException(
            status_code=404, detail={"code": 404, "message": "Batch not found"}
        )

    file_data = await repos["file_repo"].get_by_id(file_id)
    if not file_data:
        raise HTTPException(
            status_code=404, detail={"code": 404, "message": "File not found"}
        )

    return ApiResponse(data=FileDetailResponse.from_db_row(file_data))


@router.post("/{batch_id}/process", status_code=202)
async def process_batch(
    batch_id: str,
    req: Optional[ProcessRequest] = None,
    repos=Depends(get_repos),
):
    """将批次加入处理队列（由 QueueScheduler 按优先级/FIFO 拉起执行）。

    - 重跑 completed/failed 批次时先重置文件状态并清空汇总表；
    - 显式开始处理会解除暂停（paused=0）；
    - enable_llm 随批次落库，调度器执行时读取。
    """
    batch = await repos["batch_repo"].get_by_id(batch_id)
    if not batch:
        raise HTTPException(
            status_code=404, detail={"code": 404, "message": "Batch not found"}
        )

    if batch["status"] == "processing":
        raise HTTPException(
            status_code=409,
            detail={"code": 409, "message": "Batch is already processing"},
        )

    enable_llm = req.enable_llm if req else True
    db = await get_db()

    # 重新处理（已 completed 或 failed）：
    # 仅重置「OCR 未处理(pending) 或 失败(failed)」的文件，已完成的 OCR 不重复消耗；
    # 批次级 LLM 汇总表在开启 LLM 时清空以便重建（覆盖「仅 LLM 未生成/失败」的重跑）。
    if batch["status"] in ("completed", "failed"):
        await db.execute(
            "UPDATE files SET ocr_status = 'pending', ocr_error = NULL "
            "WHERE batch_id = ? AND ocr_status IN ('pending', 'failed')",
            (batch_id,),
        )
        if enable_llm:
            await repos["batch_repo"].update_batch_table(batch_id, None)

    # 入队：状态归 created、解除暂停、记录 LLM 开关，等待调度器拉起
    await db.execute(
        "UPDATE batches SET status = 'created', paused = 0, enable_llm = ? WHERE id = ?",
        (1 if enable_llm else 0, batch_id),
    )
    await db.commit()

    return ProcessStatusResponse(
        data=ProcessStatusData(
            batch_id=batch_id,
            batch_status="created",
            total_files=batch["total_files"],
        )
    )


@router.get("/{batch_id}/status")
async def get_batch_status(batch_id: str, repos=Depends(get_repos)):
    batch = await repos["batch_repo"].get_by_id(batch_id)
    if not batch:
        raise HTTPException(
            status_code=404, detail={"code": 404, "message": "Batch not found"}
        )

    counts = await repos["file_repo"].get_status_counts(batch_id)
    total_raw = counts.get("total", 0)
    total = total_raw or 1
    ocr_completed = counts.get("ocr_completed", 0)
    ocr_failed = counts.get("ocr_failed", 0)
    progress = ((ocr_completed + ocr_failed) / total) * 100 if total_raw > 0 else 0.0

    return ProcessStatusResponse(
        data=ProcessStatusData(
            batch_id=batch_id,
            batch_status=batch["status"],
            total_files=total_raw,
            ocr_completed=ocr_completed,
            ocr_failed=ocr_failed,
            ocr_pending=counts.get("ocr_pending", 0),
            llm_completed=counts.get("llm_completed", 0),
            llm_failed=counts.get("llm_failed", 0),
            llm_pending=counts.get("llm_pending", 0),
            progress_percent=round(progress, 1),
        )
    )


@router.get("/{batch_id}/export")
async def export_batch(
    batch_id: str,
    format: str = "both",
    repos=Depends(get_repos),
):
    batch = await repos["batch_repo"].get_by_id(batch_id)
    if not batch:
        raise HTTPException(
            status_code=404, detail={"code": 404, "message": "Batch not found"}
        )

    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM files WHERE batch_id = ? ORDER BY created_at ASC",
        (batch_id,),
    )
    rows = await cursor.fetchall()
    files_data = [dict(r) for r in rows]

    export_service = get_export_service()
    return export_service.export_batch(batch, files_data, format)


def _render_batch_table_html(
    batch: dict,
    seq_headers: list,
    rows: list,
    file_order: list,
    files_map: dict,
) -> StreamingResponse:
    """渲染带缩略图的 HTML 汇总表，浏览器打开即可直观查看。"""
    html_parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        f"<title>{batch['name']} - 汇总表</title>",
        "<style>",
        "body{font-family:-apple-system,sans-serif;margin:20px;background:#f5f5f5}",
        "h1{font-size:18px;color:#333}",
        "table{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 4px #ddd}",
        "th,td{border:1px solid #ddd;padding:8px 12px;text-align:left;font-size:13px;vertical-align:middle}",
        "th{background:#f0f0f0;font-weight:600;white-space:nowrap}",
        "tr:nth-child(even){background:#fafafa}",
        ".thumb{width:160px;height:auto;max-height:160px;object-fit:contain;border-radius:4px;border:1px solid #eee}",
        ".filename{font-size:12px;color:#666;word-break:break-all}",
        "</style></head><body>",
        f"<h1>{batch['name']} - 批次汇总表</h1>",
        f"<p>共 {len(rows)} 条记录</p>",
        '<table><thead><tr>',
        '<th>图片</th>',
    ]
    for h in seq_headers:
        html_parts.append(f"<th>{h}</th>")
    html_parts.append('</tr></thead><tbody>')

    for i, row in enumerate(rows):
        file_id = file_order[i] if i < len(file_order) else None
        file_info = files_map.get(file_id, {}) if file_id else {}
        stored_path = file_info.get("stored_path", "") or ""
        filename = file_info.get("filename", "") or ""

        html_parts.append("<tr>")
        # 图片列：图片文件以 base64 嵌入缩略图，其他显示文件名
        _img_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
        ext = os.path.splitext(filename)[1].lower() if filename else ""
        if stored_path and ext in _img_exts and os.path.isfile(stored_path):
            file_size = os.path.getsize(stored_path)
            if file_size > 5 * 1024 * 1024:  # >5MB 跳过嵌入，防止 HTML 过大
                html_parts.append(
                    f'<td><span class="filename">{filename}({file_size//1024}KB，未嵌入)</span></td>'
                )
            else:
                try:
                    with open(stored_path, "rb") as fimg:
                        b64 = base64.b64encode(fimg.read()).decode("ascii")
                    mime = mimetypes.guess_type(filename)[0] or "image/jpeg"
                    html_parts.append(
                        f'<td><img class="thumb" src="data:{mime};base64,{b64}" '
                        f'alt="{filename}" /></td>'
                    )
                except (OSError, IOError):
                    html_parts.append(f'<td><span class="filename">{filename}(读取失败)</span></td>')
        else:
            html_parts.append(f'<td><span class="filename">{filename}</span></td>')

        # 数据列（按序号+文件名+其他字段顺序）
        html_parts.append(f"<td>{i + 1}</td>")
        if isinstance(row, dict):
            for h in seq_headers[1:]:
                val = str(row.get(h, ""))
                html_parts.append(f"<td>{val}</td>")
        elif isinstance(row, (list, tuple)):
            for v in row:
                html_parts.append(f"<td>{v}</td>")
        else:
            html_parts.append(f"<td>{row}</td>")
        html_parts.append("</tr>")

    html_parts.append("</tbody></table></body></html>")
    html_content = "".join(html_parts).encode("utf-8")

    filename = f"{batch['name']}_汇总表.html"
    encoded_filename = quote(filename)
    return StreamingResponse(
        io.BytesIO(html_content),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


@router.get("/{batch_id}/table")
async def get_batch_table(
    batch_id: str,
    format: str = "csv",
    repos=Depends(get_repos),
):
    """获取批次汇总表：一张表，每行=一个文件。

    format=csv → CSV（含源文件路径列）
    format=json → 原始 JSON
    format=html → 带缩略图的 HTML 页面（浏览器直观查看）
    """
    batch = await repos["batch_repo"].get_by_id(batch_id)
    if not batch:
        raise HTTPException(
            status_code=404, detail={"code": 404, "message": "Batch not found"}
        )

    raw = batch.get("batch_table")
    if not raw:
        raise HTTPException(
            status_code=404,
            detail={"code": 404, "message": "汇总表尚未生成（请先处理批次）"},
        )
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(
            status_code=500, detail={"code": 500, "message": "汇总表数据损坏"}
        )

    tables = data.get("tables") if isinstance(data, dict) else None
    if not tables:
        raise HTTPException(
            status_code=404, detail={"code": 404, "message": "汇总表为空"}
        )
    table = tables[0]
    headers = table.get("headers", []) or []
    rows = table.get("rows", []) or []
    file_order = data.get("file_order", []) or []

    # 重排表头：序号 + 文件名 + 其余字段
    other_headers = [h for h in headers if h != "文件名"]
    seq_headers = ["序号", "文件名"] + other_headers

    # 获取文件 stored_path 映射（用于图片路径列 + HTML 缩略图）
    files_map = {}
    if file_order:
        db = await get_db()
        cursor = await db.execute(
            "SELECT id, original_filename, stored_path FROM files WHERE batch_id = ?",
            (batch_id,),
        )
        all_files = await cursor.fetchall()
        for f in all_files:
            files_map[f[0]] = {"filename": f[1], "stored_path": f[2]}

    if format == "json":
        return ApiResponse(data=data)

    if format == "html":
        return _render_batch_table_html(
            batch, seq_headers, rows, file_order, files_map
        )

    # CSV（含 BOM）
    csv_headers = list(seq_headers) if seq_headers else []
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    if csv_headers:
        writer.writerow(csv_headers)

    for i, row in enumerate(rows):
        if isinstance(row, dict):
            vals = [str(i + 1)]
            for h in csv_headers[1:]:
                vals.append(str(row.get(h, "")))
            writer.writerow(vals)
        elif isinstance(row, (list, tuple)):
            writer.writerow([str(i + 1)] + list(row))
        else:
            writer.writerow([str(i + 1), str(row)])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    filename = f"{batch['name']}_汇总表.csv"
    encoded_filename = quote(filename)
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


@router.post("/{batch_id}/table/rerun", status_code=202)
async def rerun_batch_table(
    batch_id: str,
    repos=Depends(get_repos),
):
    """用当前 LLM 配置重新生成批次汇总表。"""
    batch = await repos["batch_repo"].get_by_id(batch_id)
    if not batch:
        raise HTTPException(
            status_code=404, detail={"code": 404, "message": "Batch not found"}
        )

    llm_service = LLMService(repos["setting_repo"])
    files = await repos["file_repo"].get_all_for_consolidated(batch_id)
    if not files:
        return ApiResponse(data={"success": False, "error": "批次没有文件"})

    result = await llm_service.format_batch_table(files)
    out = await persist_batch_table(repos["batch_repo"], batch_id, result)
    if out["skipped"]:
        return ApiResponse(data={"success": True, "skipped": True})
    if out["success"]:
        return ApiResponse(data={"success": True, "model": result.get("model")})
    return ApiResponse(data={"success": False, "error": result.get("error")})
