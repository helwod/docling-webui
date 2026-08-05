import json
import re
from openai import AsyncOpenAI
from app.repositories.setting_repo import SettingRepo

SYSTEM_PROMPT = """You are a table data extraction assistant.
Your task is to analyze OCR-processed markdown content and extract
structured table data into JSON format.

Rules:
1. Only extract table data, ignore non-table content.
2. Use meaningful Chinese business field names as headers (e.g. 合同编号, 签订日期, 甲方, 金额), NOT generic "col1/col2".
3. Each row becomes a JSON object in an array.
4. CRITICAL — copy cell values EXACTLY as written in the source OCR text. Do NOT reformat, normalize, or "correct" them:
   - Keep dates, numbers, amounts, and codes exactly as written
     (e.g. write "2024.1.5" NOT "2024-01-05"; "HT-2024-001" NOT "HT2024001"; "12,500.00" NOT "12500").
   - Keep Chinese numerals as written (e.g. "壹万圆整" stays "壹万圆整").
   - Only compute/derive a value when the source explicitly states a calculation or total; otherwise keep the literal source text.
5. If no table is found, return empty array.
6. Return ONLY valid JSON, no explanations.

Output format:
{
  "tables": [
    {
      "table_index": 0,
      "headers": ["字段1", "字段2", ...],
      "rows": [
        {"字段1": "原文值1", "字段2": "原文值2", ...},
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
   capture the shared business fields across documents, and use meaningful
   Chinese business field names (e.g. 合同编号, 签订日期, 甲方, 金额).
   Do NOT use generic "col1/col2".
4. CRITICAL — copy each cell value EXACTLY as written in that document's
   source OCR text. Do NOT reformat, normalize, or "correct" values:
   - Keep dates, numbers, amounts, and codes exactly as written
     (e.g. write "2024.1.5" NOT "2024-01-05"; "HT-2024-001" NOT "HT2024001").
   - Keep Chinese numerals as written (e.g. "壹万圆整" stays "壹万圆整").
   - Only compute/derive a value when the source explicitly states a
     calculation or total; otherwise keep the literal source text.
5. Do not invent data. If a document lacks a field, leave that cell empty ("").
6. Return ONLY valid JSON, no explanations, in this format:
{
  "tables": [
    {
      "title": "批次汇总",
      "headers": ["字段1", "字段2", ...],
      "rows": [ {"字段1": "原文值1", "字段2": "原文值2"}, ... ]
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

    async def _chat_json(self, client, model, messages, timeout=60):
        """容错调用 LLM 取 JSON 文本。

        部分私有/本地 OpenAI 兼容端点（如自建 vLLM、部分国产模型网关）不支持
        response_format={"type":"json_object"}，直接传该参数会让调用报错/返回空，
        导致「接受 LLM 返回数据失败」。
        这里先尝试 json_object 模式；若抛异常则自动降级为普通模式（只靠 prompt
        约束 + _extract_json 解析），最大化对各类端点的兼容性。
        返回 (content, error)：error 为 None 表示已拿到响应（content 可能为空，由调用方判断）。
        """
        last_err = None
        for rf in ({"type": "json_object"}, None):
            try:
                content = await self._stream_chat(
                    client, model, messages=messages, timeout=timeout, response_format=rf
                )
                return content, None
            except Exception as e:
                last_err = str(e)
        return None, last_err

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
            frag = text[start : end + 1]
            # 修复常见 LLM 输出瑕疵：尾随逗号、对象/数组尾部的多余逗号、注释
            frag = re.sub(r",(\s*[}\]])", r"\1", frag)
            frag = re.sub(r"//[^\n]*", "", frag)
            try:
                return json.loads(frag)
            except Exception:
                pass
        raise ValueError("LLM 返回内容中未找到合法 JSON")

    async def extract_tables(self, ocr_md_content: str, model_override: str = None) -> dict:
        if not ocr_md_content or not ocr_md_content.strip():
            return {"success": True, "skipped": True, "result": {"tables": []}}

        # Format arbitrary OCR content into a structured table (no markdown-table gate).
        api_key, base_url, model = await self._get_credentials(model_override)
        if not api_key or api_key == "your-api-key-here":
            return {"success": False, "error": "LLM API key not configured"}

        client = self._build_client(api_key, base_url)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
                ocr_md_content=ocr_md_content
            )},
        ]
        content, llm_err = await self._chat_json(client, model, messages=messages, timeout=60)
        if llm_err:
            return {"success": False, "error": f"LLM call failed: {llm_err}"}
        if not content:
            return {"success": False, "error": "Empty LLM response"}

        try:
            result = self._extract_json(content)
            return {
                "success": True,
                "skipped": False,
                "result": result,
                "model": model,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"LLM 返回无法解析为 JSON：{str(e)}",
                "raw_reply": content,
            }

    async def chat(self, messages: list[dict], model_override: str = None, timeout: int = 90) -> str:
        """多轮对话：messages 为 [{role, content}] 列表（含 system/user/assistant）。

        复用统一流式调用；返回拼接后的助手回复文本。
        """
        api_key, base_url, model = await self._get_credentials(model_override)
        if not api_key or api_key == "your-api-key-here":
            raise ValueError("LLM API key 未配置")
        client = self._build_client(api_key, base_url)
        return await self._stream_chat(client, model, messages=messages, timeout=timeout)

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
        # 记录「发起的」提示词（system + user 合并为可读文本），供审计/回溯
        prompt_text = f"[SYSTEM]\n{BATCH_SYSTEM_PROMPT}\n\n[USER]\n{user_prompt}"

        api_key, base_url, model = await self._get_credentials()
        if not api_key or api_key == "your-api-key-here":
            return {
                "success": False,
                "error": "LLM API key not configured",
                "prompt": prompt_text,
                "raw_reply": None,
                "file_order": file_order,
            }

        client = self._build_client(api_key, base_url)
        messages = [
            {"role": "system", "content": BATCH_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        content, llm_err = await self._chat_json(client, model, messages=messages, timeout=120)
        raw_reply = content  # 记录「回复」的原始响应（未解析 JSON 前）
        if llm_err:
            return {
                "success": False,
                "error": f"LLM call failed: {llm_err}",
                "prompt": prompt_text,
                "raw_reply": None,
                "file_order": file_order,
            }
        if not content:
            return {
                "success": False,
                "error": "Empty LLM response",
                "prompt": prompt_text,
                "raw_reply": raw_reply,
                "file_order": file_order,
            }
        try:
            result = self._extract_json(content)
            result["file_order"] = file_order
            return {
                "success": True,
                "skipped": False,
                "result": result,
                "model": model,
                "prompt": prompt_text,
                "raw_reply": raw_reply,
                "file_order": file_order,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"LLM 返回无法解析为 JSON：{str(e)}",
                "prompt": prompt_text,
                "raw_reply": content,
                "file_order": file_order,
            }
