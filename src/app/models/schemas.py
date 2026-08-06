from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


# --- Wrappers ---

class ApiResponse(BaseModel):
    code: int = 0
    data: Optional[Any] = None

    model_config = {"extra": "ignore"}


class ErrorResponse(BaseModel):
    code: int
    message: str
    details: Optional[dict] = None


# --- Batch ---

class BatchCreate(BaseModel):
    name: Optional[str] = None


class BatchResponse(BaseModel):
    id: str
    name: str
    source_type: str
    status: str
    total_files: int
    processed_files: int
    created_at: str
    updated_at: str
    rejected_files: list[dict] = []
    batch_table: Optional[Any] = None
    paused: int = 0
    priority: int = 0
    enable_llm: int = 1
    table_prompt: Optional[str] = None
    table_reply: Optional[str] = None

    model_config = {"from_attributes": True}


class BatchListData(BaseModel):
    items: list[BatchResponse]
    total: int
    page: int
    limit: int
    has_more: bool


class BatchListResponse(BaseModel):
    code: int = 0
    data: BatchListData


# --- File ---

class FileListItem(BaseModel):
    id: str
    original_filename: str
    file_size: int
    file_type: str
    ocr_status: str
    llm_status: str
    created_at: str

    model_config = {"from_attributes": True}


class FileListData(BaseModel):
    items: list[FileListItem]
    total: int
    page: int
    limit: int
    has_more: bool


class FileListResponse(BaseModel):
    code: int = 0
    data: FileListData


class FileDetailResponse(BaseModel):
    id: str
    batch_id: str
    original_filename: str
    file_size: int
    file_type: str
    ocr_status: str
    ocr_md_content: Optional[str] = None
    ocr_html_content: Optional[str] = None
    ocr_processing_time: Optional[float] = None
    ocr_error: Optional[str] = None
    llm_status: str
    llm_result: Optional[Any] = None
    llm_model: Optional[str] = None
    llm_error: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_db_row(cls, row: dict) -> "FileDetailResponse":
        llm_result = None
        if row.get("llm_result"):
            import json
            try:
                llm_result = json.loads(row["llm_result"])
            except (json.JSONDecodeError, TypeError):
                llm_result = row["llm_result"]
        return cls(
            id=row["id"],
            batch_id=row["batch_id"],
            original_filename=row["original_filename"],
            file_size=row["file_size"],
            file_type=row["file_type"],
            ocr_status=row["ocr_status"],
            ocr_md_content=row.get("ocr_md_content"),
            ocr_html_content=row.get("ocr_html_content"),
            ocr_processing_time=row.get("ocr_processing_time"),
            ocr_error=row.get("ocr_error"),
            llm_status=row["llm_status"],
            llm_result=llm_result,
            llm_model=row.get("llm_model"),
            llm_error=row.get("llm_error"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class FileDetailWrap(BaseModel):
    code: int = 0
    data: FileDetailResponse


# --- Process ---

class ProcessRequest(BaseModel):
    enable_llm: bool = True
    ocr_engine: Optional[str] = None
    table_mode: Optional[str] = None


class ProcessStatusData(BaseModel):
    batch_id: str
    batch_status: str
    total_files: int
    ocr_completed: int = 0
    ocr_failed: int = 0
    ocr_pending: int = 0
    llm_completed: int = 0
    llm_failed: int = 0
    llm_pending: int = 0
    progress_percent: float = 0.0


class ProcessStatusResponse(BaseModel):
    code: int = 0
    data: ProcessStatusData


# --- LLM ---

class LLMRerunRequest(BaseModel):
    model: Optional[str] = None


class LLMTestRequest(BaseModel):
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None


class LLMResultData(BaseModel):
    file_id: str
    llm_status: str
    llm_result: Optional[Any] = None
    llm_model: Optional[str] = None
    llm_error: Optional[str] = None


class LLMResultResponse(BaseModel):
    code: int = 0
    data: LLMResultData


# --- Config ---

class ConfigResponseData(BaseModel):
    docling_base_url: str
    llm_base_url: str
    llm_model: str
    llm_api_key_set: bool
    llm_role: str = ""
    docling_ocr_engine: str
    docling_table_mode: str
    docling_image_export_mode: str
    max_concurrent_conversions: int
    poll_interval_seconds: int


class ConfigResponse(BaseModel):
    code: int = 0
    data: ConfigResponseData


class ConfigUpdate(BaseModel):
    docling_base_url: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_role: Optional[str] = None
    docling_ocr_engine: Optional[str] = None
    docling_table_mode: Optional[str] = None
    docling_image_export_mode: Optional[str] = None
    max_concurrent_conversions: Optional[int] = None
    poll_interval_seconds: Optional[int] = None
