import os
import uuid
from pathlib import Path

# 允许的类型：图片 + Docling Serve 支持的常见文档格式。
# 之前只放行图片，导致用户传 PDF/Office 等合法文件被静默丢弃。
ALLOWED_EXTENSIONS = {
    # 图片
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".webp",
    # 文档 / 表格（Docling 支持）
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".html", ".htm",
    ".txt", ".md", ".csv", ".xlsx", ".xml", ".asciidoc",
}


def get_file_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def is_allowed_file(filename: str) -> bool:
    """判断文件是否为可处理的类型（图片或 Docling 支持的文档格式）。"""
    ext = get_file_extension(filename)
    return ext in ALLOWED_EXTENSIONS


def generate_stored_path(upload_dir: str, original_filename: str) -> str:
    ext = get_file_extension(original_filename)
    unique_name = f"{uuid.uuid4().hex}{ext}"
    return os.path.join(upload_dir, unique_name)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def format_size(bytes_size: int) -> str:
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.1f} MB"
    return f"{bytes_size / (1024 * 1024 * 1024):.1f} GB"
