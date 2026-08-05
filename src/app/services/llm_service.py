import json
import re
from openai import AsyncOpenAI
from app.repositories.setting_repo import SettingRepo


def _clean_json_text(s: str) -> str:
    """修复 LLM 常见 JSON 瑕疵：尾随逗号、// 行注释、/* */ 块注释。"""
    s = re.sub(r",(\s*[}\]])", r"\1", s)          # 对象/数组尾部的尾随逗号
    s = re.sub(r"//[^\n]*", "", s)                # 行注释
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)  # 块注释
    return s.strip()


def _clean_ocr_md(text: str) -> str:
    """清理注入 LLM 提示词的 OCR Markdown：去掉空行与 Markdown 格式标记，保留可读文本与表格数据。

    处理规则：
    - 丢弃空行/纯空白行
    - 丢弃表格分隔行（如 |---|---|，仅由 |、-、:、空格构成）
    - 去掉标题 # 标记、加粗/斜体 ** *、行内代码 `、引用 >、列表符号 - * + 等语法标记，保留其文字
    - 链接 [text](url) / 图片 ![alt](url) 仅保留文字，丢弃 url
    - 保留表格数据行中的 | 列分隔（用于区分列），不破坏数据结构
    """
    if not text:
        return ""
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue  # 空行/纯空白行
        # 表格分隔行：仅含 |、-、:、空格
        if "-" in s and re.match(r"^\|?[\s:|-]+\|?$", s):
            continue
        # 去掉行首标题 # 号
        s = re.sub(r"^#{1,6}\s*", "", s)
        # 去掉行首列表符号 - * + （后接空白）
        s = re.sub(r"^([-*+])\s+", "", s)
        # 去掉引用 >
        s = re.sub(r"^>\s*", "", s)
        # 去掉加粗/斜体/行内代码标记
        s = s.replace("**", "").replace("__", "").replace("`", "")
        s = re.sub(r"(?<!\*)\*(?!\*)", "", s)
        # 图片/链接：![alt](url) 或 [text](url) -> 保留文字
        s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)
        s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
        out.append(s)
    return "\n".join(out)

SYSTEM_PROMPT = """你是一个表格数据提取助手。
你的任务是分析经过 OCR 处理的 Markdown 内容，并将其中的结构化表格数据提取为 JSON 格式。

规则：
1. 只提取表格数据，忽略非表格内容。
2. 使用有意义的中文业务字段名作为表头（例如：合同编号、签订日期、甲方、金额），不要使用 "col1/col2" 这类通用名称。
3. 每一行对应一个 JSON 对象，放入数组中。
4. 关键要求——单元格的值必须严格按照源 OCR 文本中的写法照搬，不要重新格式化、归一化或"修正"：
   - 日期、数字、金额、编号等保持原文写法
     （例如写 "2024.1.5" 不要写 "2024-01-05"；写 "HT-2024-001" 不要写 "HT2024001"；写 "12,500.00" 不要写 "12500"）。
   - 中文大写数字保持原文（例如 "壹万圆整" 保持 "壹万圆整"）。
   - 仅当来源明确给出计算或合计时才计算/推导数值，否则保留原文照抄。
5. 若未找到任何表格，返回空数组。
6. 只返回合法的 JSON，不要附带任何解释说明。

输出格式：
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

USER_PROMPT_TEMPLATE = """以下是 OCR 处理后的 Markdown 内容：

{ocr_md_content}

请将上述内容中的所有表格提取为结构化 JSON 格式。"""

BATCH_SYSTEM_PROMPT = """你是一个表格数据提取助手。
下面会给你多份文档（它们的 OCR 文本）。你的任务是把【所有文档】整理成【一张】结构化表格。

规则：
1. 只输出【一张】表格。
2. 每一行对应【一份】输入文档，且顺序与给出的顺序一致
   （DOCUMENT 1 → 第 1 行，DOCUMENT 2 → 第 2 行，……）。
3. 所有行使用【一致】的列名；选择能最好地概括各文档共有业务字段的列名，并使用有意义的中文业务字段名
   （例如：合同编号、签订日期、甲方、金额）。不要使用 "col1/col2" 这类通用名称。
4. 关键要求——每个单元格的值必须严格按照该文档源 OCR 文本中的写法照搬，不要重新格式化、归一化或"修正"：
   - 日期、数字、金额、编号等保持原文写法
     （例如写 "2024.1.5" 不要写 "2024-01-05"；写 "HT-2024-001" 不要写 "HT2024001"）。
   - 中文大写数字保持原文（例如 "壹万圆整" 保持 "壹万圆整"）。
   - 仅当来源明确给出计算或合计时才计算/推导数值，否则保留原文照抄。
5. 不得编造数据。若某份文档缺少某个字段，该单元格留空（""）。
6. 只返回合法的 JSON，不要附带任何解释说明，格式如下：
{
  "tables": [
    {
      "title": "批次汇总",
      "headers": ["字段1", "字段2", ...],
      "rows": [ {"字段1": "原文值1", "字段2": "原文值2"}, ... ]
    }
  ]
}"""

BATCH_USER_TEMPLATE = """下面是 {n} 份文档，每份以 "===== DOCUMENT {{i}} =====" 分隔。

{documents}

请将这 {n} 份文档整理成一张表格，每份文档一行，保持原有顺序。
若某份文档没有可提取的字段，仍要为它生成一行（含文件名），其余单元格留空。"""


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
        """从 LLM 返回文本中提取 JSON，容错策略（依次尝试）：

        1. 直接 json.loads（模型已返回纯净 JSON）；
        2. 剥离 markdown 代码围栏 ```json ... ``` / ``` ... ```（围栏可在文本任意位置）
           —— 用非贪婪匹配只取围栏内内容，避免尾注里的花括号污染；
        3. 在围栏内容 / 全文里截取第一个 `{`→最后一个 `}`（或 `[`→`]`）；
        4. 对截取片段做常见瑕疵修复（尾随逗号、`//` 行注释、`/* */` 块注释）后再次解析。
        """
        text = (text or "").strip()

        def _try_parse(s):
            s = s.strip()
            if not s:
                return None
            try:
                return json.loads(s)
            except Exception:
                pass
            try:
                return json.loads(_clean_json_text(s))
            except Exception:
                return None

        # 1) 直接解析
        r = _try_parse(text)
        if r is not None:
            return r

        # 2) 剥离 markdown 围栏（语言名可有可无；内容任意字符，非贪婪）
        m = re.search(r"```[ \t]*[a-zA-Z]*[ \t]*\n?(.*?)\n?[ \t]*```", text, re.DOTALL)
        if m:
            fenced = m.group(1).strip()
            r = _try_parse(fenced)
            if r is not None:
                return r

        # 3) 兜底：截取第一个 { 到最后一个 }（优先对象）；否则 [ 到 ]
        for open_c, close_c in (("{", "}"), ("[", "]")):
            start = text.find(open_c)
            end = text.rfind(close_c)
            if start != -1 and end != -1 and end > start:
                frag = text[start : end + 1]
                r = _try_parse(frag)
                if r is not None:
                    return r

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
                ocr_md_content=_clean_ocr_md(ocr_md_content)
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
            else:
                # 过滤空行与 Markdown 格式标记，降低提示词噪声与 token 占用
                content = _clean_ocr_md(content)
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
