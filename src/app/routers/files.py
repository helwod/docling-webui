import os
import json
from pathlib import Path

import fitz  # PyMuPDF：把 PDF 每页渲染成预览图片
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from typing import Optional

from app.db.database import get_db
from app.repositories.file_repo import FileRepo
from app.repositories.setting_repo import SettingRepo
from app.models.schemas import (
    ApiResponse,
    FileDetailResponse,
    FileDetailWrap,
    LLMRerunRequest,
    LLMResultData,
    LLMResultResponse,
)
from app.services.llm_service import LLMService
from app.services.docling_service import DoclingService
from app.services.export_service import ExportService
from app.config import settings as config_settings

router = APIRouter(prefix="/api/v1/files", tags=["files"])


def get_export_service() -> ExportService:
    return ExportService(config_settings.upload_dir)


async def get_repos(db=Depends(get_db)):
    return {
        "file_repo": FileRepo(db),
        "setting_repo": SettingRepo(db),
    }


@router.post("/{file_id}/llm", status_code=202)
async def rerun_llm(
    file_id: str,
    req: Optional[LLMRerunRequest] = None,
    repos=Depends(get_repos),
):
    file_data = await repos["file_repo"].get_by_id(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})

    if file_data["ocr_status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail={"code": 409, "message": "OCR not completed yet"},
        )

    model_override = req.model if req else None
    llm_service = LLMService(repos["setting_repo"])
    md_content = file_data.get("ocr_md_content") or ""

    await repos["file_repo"].update_llm_status(file_id, "processing")
    result = await llm_service.extract_tables(md_content, model_override)

    if result.get("skipped"):
        await repos["file_repo"].update_llm_status(
            file_id, "skipped",
            llm_result='{"tables": []}',
        )
    elif result["success"]:
        await repos["file_repo"].update_llm_status(
            file_id, "completed",
            llm_result=json.dumps(result["result"], ensure_ascii=False),
            llm_model=result.get("model", ""),
        )
    else:
        await repos["file_repo"].update_llm_status(
            file_id, "failed",
            llm_error=result.get("error", "Unknown error"),
        )

    updated = await repos["file_repo"].get_by_id(file_id)
    return FileDetailWrap(data=FileDetailResponse.from_db_row(updated))


@router.get("/{file_id}/llm")
async def get_llm_result(file_id: str, repos=Depends(get_repos)):
    file_data = await repos["file_repo"].get_by_id(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})

    llm_result = None
    if file_data.get("llm_result"):
        try:
            llm_result = json.loads(file_data["llm_result"])
        except (json.JSONDecodeError, TypeError):
            llm_result = file_data["llm_result"]

    return LLMResultResponse(data=LLMResultData(
        file_id=file_id,
        llm_status=file_data["llm_status"],
        llm_result=llm_result,
        llm_model=file_data.get("llm_model"),
        llm_error=file_data.get("llm_error"),
    ))


@router.get("/{file_id}/ocr-segments")
async def get_ocr_segments(file_id: str, repos=Depends(get_repos)):
    """返回带坐标的 OCR 文字片段（来自 Docling 结构化 JSON）。

    前端点击某个识别字段时，用 bbox 在对应页面图片上画高亮框。
    坐标已归一化到 0..1（相对所属页面），多页 PDF 返回所有页片段，
    每个片段带 page_no，与其预览页一一对应；total_pages 为文档总页数。
    """
    file_data = await repos["file_repo"].get_by_id(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})

    raw = file_data.get("ocr_json_content")
    segments, total_pages = _extract_segments(raw)
    return ApiResponse(data={"segments": segments, "total_pages": total_pages})


def _extract_bbox(item: dict, page_w, page_h):
    """从单条 text 项里提取归一化(0..1) bbox {l,t,r,b}（top-left 原点）。

    兼容两种情况：
    - 像素坐标（值较大）：用 page_w/page_h 归一化；
    - 已归一化坐标（值 <=1.5）：直接当作 0..1。
    Docling 默认 coord_origin=BOTTOMLEFT，需要把 y 轴翻转成 top-left。
    取不到合法坐标返回 None。
    """
    if not page_w or not page_h:
        return None
    prov = item.get("prov") or item.get("provenance") or []
    candidates = []
    if isinstance(prov, list):
        for p in prov:
            if isinstance(p, dict):
                candidates.append(p.get("bbox") or p.get("rect"))
    if not candidates:
        candidates = [item.get("bbox") or item.get("rect")]
    for c in candidates:
        if not (isinstance(c, dict) and all(k in c for k in ("l", "t", "r", "b"))):
            continue
        try:
            l, t, r, b = float(c["l"]), float(c["t"]), float(c["r"]), float(c["b"])
        except (TypeError, ValueError):
            continue
        origin = (c.get("coord_origin") or "TOPLEFT").upper()
        # 归一化坐标（值 <= 1.5）视为 0..1，否则按像素用页面尺寸归一化
        if max(abs(l), abs(t), abs(r), abs(b)) <= 1.5:
            w, h = 1.0, 1.0
        else:
            w, h = float(page_w), float(page_h)
        if w <= 0 or h <= 0:
            return None
        nl = l / w
        nr = r / w
        if origin == "BOTTOMLEFT":
            nt = 1 - t / h
            nb = 1 - b / h
        else:
            nt = t / h
            nb = b / h
        nl, nr = min(nl, nr), max(nl, nr)
        nt, nb = min(nt, nb), max(nt, nb)
        # 裁剪到 0..1，异常值跳过
        if not (0 <= nl <= 1 and 0 <= nr <= 1 and 0 <= nt <= 1 and 0 <= nb <= 1):
            continue
        return {"l": round(nl, 5), "t": round(nt, 5), "r": round(nr, 5), "b": round(nb, 5)}
    return None


def _build_page_sizes(doc: dict):
    """从 DoclingDocument 提取 {str(page_no): (width, height)}。"""
    sizes = {}
    pages = doc.get("pages")
    if isinstance(pages, dict):
        for k, v in pages.items():
            if isinstance(v, dict):
                sz = v.get("size") or v.get("dimensions")
                if isinstance(sz, dict):
                    sizes[str(k)] = (sz.get("width"), sz.get("height"))
    elif isinstance(pages, list):
        for p in pages:
            if isinstance(p, dict):
                pn = p.get("page_no") or p.get("id")
                sz = p.get("size") or p.get("dimensions")
                if isinstance(sz, dict) and pn is not None:
                    sizes[str(pn)] = (sz.get("width"), sz.get("height"))
    return sizes


def _extract_segments(raw_json):
    """从 DoclingDocument JSON 提取文字片段（含归一化坐标）。容错解析。

    返回 (segments, total_pages)：segments 含各页带坐标的字段；
    total_pages 为该文档页数（多页 PDF 全部返回，不再只取首页）。
    """
    if not raw_json:
        return [], 1
    try:
        if isinstance(raw_json, str):
            doc = json.loads(raw_json)
        elif isinstance(raw_json, dict):
            doc = raw_json
        else:
            return [], 1
    except (json.JSONDecodeError, TypeError):
        return [], 1

    texts = None
    if isinstance(doc, dict):
        data = doc.get("data")
        if isinstance(data, dict) and data.get("texts"):
            texts = data["texts"]
        elif doc.get("texts"):
            texts = doc["texts"]
    if not texts or not isinstance(texts, list):
        return [], 1

    page_sizes = _build_page_sizes(doc)
    segments = []
    for i, t in enumerate(texts):
        if not isinstance(t, dict):
            continue
        text = (t.get("text") or "").strip()
        if not text:
            continue
        prov = t.get("prov") or t.get("provenance") or []
        page_no = 1
        if isinstance(prov, list) and prov and isinstance(prov[0], dict):
            page_no = prov[0].get("page_no", 1) or 1
        w, h = page_sizes.get(str(page_no), (None, None))
        bbox = _extract_bbox(t, w, h)
        if not bbox:
            continue
        segments.append({
            "idx": i,
            "text": text,
            "page_no": page_no,
            "bbox": bbox,
        })
        if len(segments) >= 1500:
            break
    page_nums = [int(k) for k in page_sizes.keys()] + [s["page_no"] for s in segments]
    total_pages = max(page_nums + [1])
    return segments, total_pages


@router.get("/{file_id}/export")
async def export_single_file(
    file_id: str,
    format: str = "both",
    repos=Depends(get_repos),
):
    file_data = await repos["file_repo"].get_by_id(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})

    export_service = get_export_service()
    return export_service.export_single_file(file_data, format)


@router.get("/{file_id}/image")
async def get_file_image(file_id: str, repos=Depends(get_repos)):
    file_data = await repos["file_repo"].get_by_id(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})

    stored_path = file_data.get("stored_path")
    if not stored_path or not os.path.isfile(stored_path):
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Image file not found on disk"})

    return FileResponse(
        path=stored_path,
        media_type=file_data.get("file_type", "image/png"),
        filename=file_data["original_filename"],
    )


def _pdf_cache_dir(file_id: str) -> Path:
    return Path(config_settings.upload_dir) / ".pdf_pages" / file_id


def _render_pdf_pages(stored_path: str, file_id: str):
    """用 PyMuPDF 把 PDF 每页渲染成缓存 PNG，返回 (pages, total_pages)。

    缓存目录：<upload_dir>/.pdf_pages/<file_id>/p{n}.png
    用源文件 mtime 判断是否需重新渲染，避免文件更新后预览陈旧。
    """
    cache_dir = _pdf_cache_dir(file_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    meta_path = cache_dir / ".meta.json"
    try:
        src_mtime = os.path.getmtime(stored_path)
    except OSError:
        src_mtime = 0

    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
    if meta.get("mtime") == src_mtime and meta.get("rendered"):
        doc = fitz.open(stored_path)
        total = doc.page_count
        doc.close()
        pages = [
            {"page_no": n, "url": f"/api/v1/files/{file_id}/page/{n}"}
            for n in range(1, total + 1)
        ]
        return pages, total

    doc = fitz.open(stored_path)
    total = doc.page_count
    # 清掉旧缓存图，防止页码数变化后残留
    for old in cache_dir.glob("p*.png"):
        try:
            old.unlink()
        except OSError:
            pass
    pages = []
    matrix = fitz.Matrix(2, 2)  # 2x 清晰度
    for i in range(total):
        n = i + 1
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=matrix)
        png = cache_dir / f"p{n}.png"
        pix.save(str(png))
        pages.append({"page_no": n, "url": f"/api/v1/files/{file_id}/page/{n}"})
    doc.close()
    meta_path.write_text(
        json.dumps({"mtime": src_mtime, "rendered": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    return pages, total


@router.get("/{file_id}/pages")
async def get_file_pages(file_id: str, repos=Depends(get_repos)):
    """返回文件预览页列表。

    - 非 PDF：is_pdf=false，pages=[]（前端退回单图预览）。
    - PDF：is_pdf=true，pages=[{page_no, url}]，url 指向 /{id}/page/{n}。
    """
    file_data = await repos["file_repo"].get_by_id(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})
    stored_path = file_data.get("stored_path") or ""
    ftype = (file_data.get("file_type") or "").lower()
    is_pdf = stored_path.lower().endswith(".pdf") or ftype == "application/pdf"
    if not is_pdf or not os.path.isfile(stored_path):
        return ApiResponse(data={"is_pdf": False, "total_pages": 0, "pages": []})
    pages, total = _render_pdf_pages(stored_path, file_id)
    return ApiResponse(data={"is_pdf": True, "total_pages": total, "pages": pages})


@router.get("/{file_id}/page/{page_no}")
async def get_file_page(file_id: str, page_no: int, repos=Depends(get_repos)):
    """返回 PDF 某一页的渲染图（PNG）。"""
    file_data = await repos["file_repo"].get_by_id(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})
    stored_path = file_data.get("stored_path") or ""
    cache_dir = _pdf_cache_dir(file_id)
    png = cache_dir / f"p{page_no}.png"
    if not png.exists():
        # 尚未渲染（如直接访问），触发一次完整渲染
        if stored_path.lower().endswith(".pdf") and os.path.isfile(stored_path):
            _render_pdf_pages(stored_path, file_id)
    if not png.exists():
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Page image not found"})
    return FileResponse(png, media_type="image/png")


@router.post("/{file_id}/rerun-ocr", status_code=202)
async def rerun_ocr(
    file_id: str,
    repos=Depends(get_repos),
):
    """重新对单个文件执行 OCR。"""
    file_data = await repos["file_repo"].get_by_id(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})

    stored_path = file_data.get("stored_path", "")
    if not stored_path or not os.path.isfile(stored_path):
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found on disk"})

    # 重置状态并重新 OCR
    await repos["file_repo"].reset_ocr_status(file_id)
    await repos["file_repo"].update_ocr_status(file_id, "processing")

    docling = DoclingService(repos["setting_repo"])
    result = await docling.convert_file(stored_path, file_data["original_filename"])

    if not result["success"]:
        await repos["file_repo"].update_ocr_status(
            file_id, "failed",
            ocr_error=result.get("error", "Unknown OCR error"),
        )
        return ApiResponse(data={"success": False, "error": result.get("error")})

    await repos["file_repo"].update_ocr_status(
        file_id, "completed",
        ocr_md_content=result.get("md_content", ""),
        ocr_json_content=result.get("json_content"),
        ocr_html_content=result.get("html_content"),
        ocr_task_id=result.get("task_id", ""),
        ocr_processing_time=0.0,
    )
    return ApiResponse(data={"success": True})

