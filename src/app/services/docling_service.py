import asyncio
import httpx
import json
import mimetypes
from typing import Optional
from app.repositories.setting_repo import SettingRepo


DOCLING_POLL_INTERVAL = 2
DOCLING_POLL_TIMEOUT = 600
SEMAPHORE_LIMIT = 5

# 真实 API (Docling Serve 1.27.0) 返回的状态枚举
# 见 GET /v1/status/poll/{task_id} -> task_status
TERMINAL_SUCCESS = {"success", "partial_success"}
TERMINAL_FAILURE = {"failure", "skipped"}


class DoclingService:
    def __init__(self, setting_repo: SettingRepo):
        self.setting_repo = setting_repo
        self._semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)

    async def get_base_url(self) -> str:
        return (await self.setting_repo.get("docling_base_url")) or "http://localhost:5001"

    async def convert_file(self, file_path: str, filename: str) -> dict:
        base_url = await self.get_base_url()
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        table_mode = (await self.setting_repo.get("docling_table_mode")) or "accurate"

        async with self._semaphore:
            async with httpx.AsyncClient(timeout=120.0) as client:
                    # httpx AsyncClient 不能接收同步 open() 的文件对象，必须先读为 bytes
                    with open(file_path, "rb") as f:
                        file_bytes = f.read()
                    # 关键：表单字段名必须为 files (复数)，与 OpenAPI Body 一致
                    files = {"files": (filename, file_bytes, content_type)}
                    # to_formats 用列表值，httpx 会编码为重复表单字段；
                    # 注意：JSON 字符串会被后端拒绝，data 也不能用 list[tuple]（会触发同步路径）
                    data = {
                        "to_formats": ["md", "json", "html"],
                        "do_ocr": "true",
                        "force_ocr": "false",
                        "table_mode": table_mode,
                        "image_export_mode": "placeholder",
                    }

                    resp = await client.post(
                        f"{base_url}/v1/convert/file/async",
                        files=files,
                        data=data,
                    )
                    if resp.status_code != 200:
                        return {"success": False, "error": f"Docling submit failed: {resp.text}"}

                    result = resp.json()
                    # 异步提交返回顶层 task_id
                    task_id = result.get("task_id") or result.get("id")
                    if not task_id:
                        return {"success": False, "error": "No task_id in response"}

                    # 轮询直到完成
                    poll_result = await self._poll_task(client, base_url, task_id)
                    if not poll_result["success"]:
                        return poll_result

                    # 取结果
                    return await self._get_result(client, base_url, task_id)

    async def _poll_task(self, client: httpx.AsyncClient, base_url: str, task_id: str) -> dict:
        start = asyncio.get_event_loop().time()
        poll_interval = await self._get_poll_interval()

        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > DOCLING_POLL_TIMEOUT:
                return {"success": False, "error": "Docling polling timeout"}

            try:
                resp = await client.get(f"{base_url}/v1/status/poll/{task_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    # 真实字段是 task_status（不是 status）
                    status = data.get("task_status", "")
                    if status in TERMINAL_SUCCESS:
                        return {"success": True}
                    elif status in TERMINAL_FAILURE:
                        error_msg = data.get("error_message") or data.get("failure") or "Unknown error"
                        return {"success": False, "error": f"Docling processing failed: {error_msg}"}
            except httpx.RequestError as e:
                return {"success": False, "error": f"Docling poll error: {str(e)}"}

            await asyncio.sleep(poll_interval)

    async def _get_result(self, client: httpx.AsyncClient, base_url: str, task_id: str) -> dict:
        try:
            resp = await client.get(f"{base_url}/v1/result/{task_id}")
            if resp.status_code != 200:
                return {"success": False, "error": f"Docling get result failed: {resp.text}"}

            data = resp.json()
            # 真实结构：内容嵌套在 document 对象下
            document = data.get("document") or {}
            md_content = document.get("md_content") or ""
            json_content = document.get("json_content")
            html_content = document.get("html_content") or ""

            # json_content 是 DoclingDocument 对象，存库前序列化为字符串
            if isinstance(json_content, (dict, list)):
                json_content = json.dumps(json_content, ensure_ascii=False)

            return {
                "success": True,
                "task_id": task_id,
                "md_content": md_content,
                "json_content": json_content or "",
                "html_content": html_content,
                "raw": data,
            }
        except httpx.RequestError as e:
            return {"success": False, "error": f"Docling get result error: {str(e)}"}

    async def health_check(self) -> bool:
        base_url = await self.get_base_url()
        try:
            # 真实端点为 /health（不是 /v1/health）
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/health", timeout=10.0)
                return resp.status_code == 200
        except httpx.RequestError:
            return False

    async def test_connection(self, base_url_override: str | None = None) -> dict:
        """验证 Docling Serve 地址可达（支持传入未保存的覆盖值）。

        健康端点固定为 /health（Docling Serve 唯一的健康路径）。
        同时尝试根路径 / 作为兜底，只要任一返回 <400 即视为正常。
        """
        import time

        base_url = (base_url_override or "").strip() or (await self.get_base_url())
        # 去掉末尾斜杠，避免路径重复
        base_url = base_url.rstrip("/")
        candidate_paths = ["/health", "/"]
        last_status = None
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                for path in candidate_paths:
                    try:
                        resp = await client.get(f"{base_url}{path}", timeout=10.0)
                    except httpx.RequestError as e:
                        # 连接级错误（拒绝/超时/DNS 失败）—— 服务不可达，停止尝试
                        latency_ms = int((time.monotonic() - start) * 1000)
                        return {
                            "ok": False,
                            "status_code": None,
                            "latency_ms": latency_ms,
                            "error": str(e),
                        }
                    last_status = resp.status_code
                    if resp.status_code < 400:
                        latency_ms = int((time.monotonic() - start) * 1000)
                        return {
                            "ok": True,
                            "status_code": resp.status_code,
                            "latency_ms": latency_ms,
                            "path": path,
                        }
            latency_ms = int((time.monotonic() - start) * 1000)
            return {
                "ok": False,
                "status_code": last_status,
                "latency_ms": latency_ms,
                "error": f"HTTP {last_status}（已尝试 /health、/）",
            }
        except Exception as e:  # noqa: BLE001
            latency_ms = int((time.monotonic() - start) * 1000)
            return {"ok": False, "status_code": None, "latency_ms": latency_ms, "error": str(e)}

    async def _get_poll_interval(self) -> int:
        val = await self.setting_repo.get("poll_interval_seconds")
        return int(val) if val else DOCLING_POLL_INTERVAL
