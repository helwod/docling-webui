import json
from openai import AsyncOpenAI
from app.repositories.setting_repo import SettingRepo

SYSTEM_PROMPT = """You are a table data extraction assistant.
Your task is to analyze OCR-processed markdown content and extract
structured table data into JSON format.

Rules:
1. Only extract table data, ignore non-table content
2. Preserve original column headers
3. Each row becomes a JSON object in an array
4. If no table is found, return empty array
5. Return ONLY valid JSON, no explanations

Output format:
{
  "tables": [
    {
      "table_index": 0,
      "headers": ["column1", "column2", ...],
      "rows": [
        {"column1": "value1", "column2": "value2", ...},
        ...
      ]
    }
  ]
}"""

USER_PROMPT_TEMPLATE = """Here is the OCR markdown content:

{ocr_md_content}

Extract all tables from the above content into structured JSON format."""

BATCH_SYSTEM_PROMPT = """You are a table data extraction assistant.
You will be given multiple documents (their OCR text). Your task is to
organize ALL documents into ONE structured table.

Rules:
1. Produce exactly ONE table.
2. Each row corresponds to ONE input document, in the SAME order as given
   (DOCUMENT 1 -> row 1, DOCUMENT 2 -> row 2, ...).
3. Use CONSISTENT column headers across all rows. Choose headers that best
   capture the shared fields across documents. If a document lacks a field,
   leave that cell empty.
4. Preserve original values faithfully; do not invent data.
5. Return ONLY valid JSON, no explanations, in this format:
{
  "tables": [
    {
      "title": "批次汇总",
      "headers": ["col1", "col2", ...],
      "rows": [ {"col1": "v1", "col2": "v2"}, ... ]
    }
  ]
}"""

BATCH_USER_TEMPLATE = """Below are {n} documents, each delimited by "===== DOCUMENT {{i}} =====".

{documents}

Organize all {n} documents into ONE table, one row per document, preserving order.
If a document has no extractable fields, still produce its row with the file name
and empty cells."""


class LLMService:
    def __init__(self, setting_repo: SettingRepo):
        self.setting_repo = setting_repo

    async def _get_credentials(self, model_override=None, base_url_override=None, api_key_override=None):
        """解析当前生效的 key/base_url/model，支持调用方传入覆盖（用于『先测后存』）。"""
        api_key = api_key_override or (await self.setting_repo.get("llm_api_key")) or ""
        if not api_key:
            # Fall back to env variable
            from app.config import settings
            api_key = settings.llm_api_key
        base_url = base_url_override or (await self.setting_repo.get("llm_base_url")) or "https://api.openai.com/v1"
        model = model_override or (await self.setting_repo.get("llm_model")) or "gpt-4o-mini"
        return api_key, base_url, model

    def _build_client(self, api_key: str, base_url: str):
        return AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def _stream_chat(self, client, model, messages, timeout=60, response_format=None):
        """统一用流式调用。

        部分 OpenAI 兼容端点（如某些本地/私有化部署）即便未请求流式也会强制
        以 SSE(text/event-stream) 返回，标准 client 在非流式模式下会把响应体
        作为原始字符串返回，导致 response.choices 报
        "'str' object has no attribute 'choices'"。

        强制 stream=True 可让 SDK 正确解析 SSE 分块，再拼接 delta.content。
        这对普通非流式端点同样兼容。
        """
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "timeout": timeout,
            "stream": True,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        stream = await client.chat.completions.create(**kwargs)
        content = ""
        async for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                content += piece
        return content

    @staticmethod
    def _extract_json(text):
        """从 LLM 返回文本中提取 JSON，容忍 markdown 代码围栏与前后杂项文本。"""
        text = (text or "").strip()
        if text.startswith("```"):
            # 去掉开头的 ```json / ``` 围栏
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        # 先尝试直接解析
        try:
            return json.loads(text)
        except Exception:
            pass
        # 退而求其次：截取第一个 { 到最后一个 } 的片段
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError("LLM 返回内容中未找到合法 JSON")

    async def extract_tables(self, ocr_md_content: str, model_override: str = None) -> dict:
        if not ocr_md_content or not ocr_md_content.strip():
            return {"success": True, "skipped": True, "result": {"tables": []}}

        # Format arbitrary OCR content into a structured table (no markdown-table gate).
        api_key, base_url, model = await self._get_credentials(model_override)
        if not api_key or api_key == "your-api-key-here":
            return {"success": False, "error": "LLM API key not configured"}

        client = self._build_client(api_key, base_url)

        for attempt in range(2):  # Retry once
            try:
                content = await self._stream_chat(
                    client,
                    model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
                            ocr_md_content=ocr_md_content
                        )},
                    ],
                    timeout=60,
                    response_format={"type": "json_object"},
                )
                if not content:
                    if attempt == 0:
                        continue
                    return {"success": False, "error": "Empty LLM response"}

                result = self._extract_json(content)
                return {
                    "success": True,
                    "skipped": False,
                    "result": result,
                    "model": model,
                }
            except Exception as e:
                if attempt == 0:
                    continue
                return {"success": False, "error": f"LLM call failed: {str(e)}"}

        return {"success": False, "error": "LLM call failed after retry"}

    async def list_models(self, base_url_override=None, api_key_override=None) -> list[str]:
        """调用 OpenAI 兼容 /models 端点，返回模型 id 列表（升序）。"""
        api_key, base_url, _ = await self._get_credentials(
            base_url_override=base_url_override, api_key_override=api_key_override
        )
        if not api_key or api_key == "your-api-key-here":
            raise ValueError("LLM API key 未配置，无法获取模型列表")
        client = self._build_client(api_key, base_url)
        try:
            resp = await client.models.list()
            ids = [m.id for m in resp.data]
            return sorted(ids)
        except Exception as e:
            raise RuntimeError(f"获取模型列表失败：{e}")

    async def test_connection(self, model_override=None, base_url_override=None, api_key_override=None) -> dict:
        """发一个最小 chat 请求验证 key / base_url / model 是否可用。"""
        api_key, base_url, model = await self._get_credentials(
            model_override, base_url_override, api_key_override
        )
        if not api_key or api_key == "your-api-key-here":
            return {"ok": False, "error": "LLM API key 未配置"}
        client = self._build_client(api_key, base_url)
        import time
        start = time.monotonic()
        try:
            sample = await self._stream_chat(
                client,
                model,
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
                timeout=30,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            sample = (sample or "").strip()
            return {"ok": True, "model": model, "latency_ms": latency_ms, "sample": sample}
        except Exception as e:
            return {"ok": False, "error": f"LLM 连接测试失败：{e}"}

    async def format_batch_table(self, files: list[dict]) -> dict:
        """把所有文件的 OCR 内容整理成一张汇总表：每行对应一个文件。

        返回 {"success", "result": {"tables":[...], "file_order":[...]}, "model"}。
        file_order 与输入顺序一致，便于前端按 file_id 定位行。
        """
        if not files:
            return {"success": True, "skipped": True, "result": {"tables": []}, "file_order": []}

        docs = []
        file_order = []
        for i, f in enumerate(files, 1):
            content = (f.get("ocr_md_content") or "").strip()
            if not content or f.get("ocr_status") != "completed":
                content = f"[OCR 未完成或失败：{f.get('original_filename')}]"
            docs.append(
                f"===== DOCUMENT {i} (文件名: {f.get('original_filename')}) =====\n{content}"
            )
            file_order.append(f.get("id"))

        user_prompt = BATCH_USER_TEMPLATE.format(
            n=len(files), documents="\n\n".join(docs)
        )
        api_key, base_url, model = await self._get_credentials()
        if not api_key or api_key == "your-api-key-here":
            return {
                "success": False,
                "error": "LLM API key not configured",
                "file_order": file_order,
            }

        client = self._build_client(api_key, base_url)
        for attempt in range(2):
            try:
                content = await self._stream_chat(
                    client,
                    model,
                    messages=[
                        {"role": "system", "content": BATCH_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    timeout=120,
                    response_format={"type": "json_object"},
                )
                if not content:
                    if attempt == 0:
                        continue
                    return {
                        "success": False,
                        "error": "Empty LLM response",
                        "file_order": file_order,
                    }
                result = self._extract_json(content)
                result["file_order"] = file_order
                return {
                    "success": True,
                    "skipped": False,
                    "result": result,
                    "model": model,
                    "file_order": file_order,
                }
            except Exception as e:
                if attempt == 0:
                    continue
                return {
                    "success": False,
                    "error": f"LLM call failed: {e}",
                    "file_order": file_order,
                }
        return {
            "success": False,
            "error": "LLM call failed after retry",
            "file_order": file_order,
        }
