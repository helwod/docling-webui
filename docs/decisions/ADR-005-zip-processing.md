# ADR-005: ZIP 文件后端解压方案

## Status: Accepted (2026-07-22)

## Background

用户需要上传 ZIP 压缩包进行批量图片 OCR 处理。需要决定 ZIP 解压在 frontend 还是 backend 执行。

## Decision

选择 **后端解压** 方案。

实现方式：
1. 前端上传 ZIP 文件到 `POST /api/v1/batches`（multipart/form-data）
2. 后端 FastAPI 流式接收文件，写入临时磁盘文件
3. 使用 Python `zipfile` 模块解压，包含安全检查：
   - 文件数量限制：最大 500 个
   - 解压后总大小限制：最大 500MB
   - 压缩比检查：最大 100:1（防止 zip bomb）
   - 路径遍历检查：拒绝 `..` 和绝对路径
4. 逐个文件验证 MIME 类型（仅允许图片和 PDF）
5. 有效文件存入 `uploads/` 目录，创建数据库记录
6. 无效文件跳过并记录警告

```python
MAX_UNCOMPRESSED_SIZE = 500 * 1024 * 1024  # 500MB
MAX_FILE_COUNT = 500
MAX_COMPRESSION_RATIO = 100

def safe_extract_zip(zip_path: str, dest_dir: str) -> list[str]:
    with zipfile.ZipFile(zip_path, 'r') as zf:
        members = zf.infolist()
        if len(members) > MAX_FILE_COUNT:
            raise ValueError(f"Too many files: {len(members)}")
        total_uncompressed = sum(m.file_size for m in members)
        if total_uncompressed > MAX_UNCOMPRESSED_SIZE:
            raise ValueError(f"Archive too large: {total_uncompressed} bytes")
        # ... path traversal checks, MIME validation, extraction
```

## Consequences

### 正面后果
- 安全可控：可防止 zip bomb、路径遍历攻击
- 可校验文件类型和大小，过滤无效文件
- 前端实现简单，只需标准文件上传
- 支持大 ZIP 文件（流式处理）

### 负面后果
- 需要服务器磁盘空间存储临时文件
- 解压过程增加服务器 CPU 负载（内部工具可接受）
- 需要实现安全检查逻辑

## Related ADRs
- ADR-002 (后端框架)
