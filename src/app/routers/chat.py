import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.database import get_db
from app.repositories.batch_repo import BatchRepo
from app.repositories.file_repo import FileRepo
from app.repositories.setting_repo import SettingRepo
from app.repositories.chat_repo import ChatRepo
from app.services.llm_service import LLMService, DEFAULT_LLM_ROLE, _is_legacy_role

router = APIRouter(prefix="/api/v1/batches", tags=["chat"])

CHAT_SYSTEM_PROMPT = """你是一个「文档批次」智能分析助手。

下面提供了当前【批次汇总表】的数据。本批次以「每行 = 一个文件」组织，每个文件的内容都用固定的开始 / 结束标记包裹，格式定义如下：

  ▦ 文件内容开始（行号 N / 文件名：<文件名>）
  <该文件的各字段，每行一条，格式为「字段名: 字段值」>
  ▦ 文件内容结束（行号 N）

阅读与作答规则：
1. 行号与文件名一一对应，每个「文件内容」块都标明了它属于哪个文件（见块首的「文件名」）。
2. 回答前先判断问题涉及哪个（或哪些）文件，只引用对应「文件内容」块内的字段作答；不要跨文件块拼凑，也不要编造不存在的字段或文件。
3. 若汇总表中没有相关信息，请明确说明「汇总表中未找到相关内容」，不要编造。
4. 回答尽量简洁、使用中文，必要时可用要点或表格呈现。
5. 关于坐标与定位：汇总表只含结构化字段值，不含图像坐标；如需定位某字段在原始文件中的位置，请提示用户到页面右侧「识别的字段」中点击对应字段查看。
6. 关于「汇总表生成记录」：本会话的 system 上下文中还会附上当初生成该汇总表时【实际发送给模型的提示词】与【模型的原始回复】（若有，见文末「汇总表生成记录」段）。当用户要求调整 / 修正 / 补全汇总表时，请结合其中的字段口径、单位、是否照抄 OCR 原文、空值处理等约束，保持与原始生成一致，不擅自引入新的字段口径或改写规则。"""

def _resolve_role(raw) -> str:
    """解析生效的「LLM 角色定义」。

    为空或仍是历史遗留的一句话旧角色时回退到 DEFAULT_LLM_ROLE，
    与 LLMService._system_with_role 的口径保持一致。
    """
    role = (raw or "").strip()
    return DEFAULT_LLM_ROLE if (not role or _is_legacy_role(role)) else role


# 汇总表 JSON 塞进 system 的安全上限，避免超长上下文
_MAX_TABLE_CHARS = 24000
# 生成记录（提示词 / 原始回复）各自的安全上限，避免把原始 OCR 也整段塞进会话上下文
_GEN_PROMPT_CAP = 8000
_GEN_REPLY_CAP = 4000


class ChatSend(BaseModel):
    message: Optional[str] = ""        # 用户消息；regenerate/edit_index 模式下可为空
    edit_index: Optional[int] = None   # 指定要编辑的用户消息 seq（编辑后重新生成后续）
    regenerate: Optional[bool] = False  # 仅重新生成最后一条助手回复（纯问答）
    regenerate_table: Optional[bool] = False  # 依据用户指令重新生成汇总表并写回批次


def _get_repos(db=Depends(get_db)):
    return {
        "batch_repo": BatchRepo(db),
        "file_repo": FileRepo(db),
        "setting_repo": SettingRepo(db),
        "chat_repo": ChatRepo(db),
    }


def _build_table_context(batch: dict, file_repo: FileRepo) -> str:
    """构造发给 LLM 的批次汇总表上下文。

    每个文件（汇总表每行）的内容都用固定的「开始 / 结束」标记包裹，并在开头给出格式说明，
    让 LLM 能清晰区分每份文件内容的边界。
    """
    raw = batch.get("batch_table")
    data = _parse_json(raw)
    if not isinstance(data, dict):
        return "（该批次尚未生成汇总表）"

    tables = data.get("tables") or []
    if not tables:
        return "（该批次尚未生成汇总表）"

    table = tables[0]
    headers = table.get("headers") or []
    rows = table.get("rows") or []
    file_order = data.get("file_order") or []

    # 文件名映射：file_order 中的文件 id -> 原始文件名
    fmap = {}
    if file_order:
        try:
            files = file_repo.list_by_ids(file_order)
            fmap = {f["id"]: f.get("original_filename", "") for f in files}
        except Exception:
            pass

    parts = []
    parts.append(
        "===== 批次汇总表（每行 = 一个文件，内容已用开始/结束标记分块）=====\n"
        "格式定义：每个文件的内容块以「▦ 文件内容开始（行号 N / 文件名：xxx）」开头，"
        "以「▦ 文件内容结束（行号 N）」结尾；块内每行一条「字段名: 字段值」。"
        "请根据块首标明的「文件名 / 行号」定位内容，并在作答时仅引用对应文件块内的字段。"
    )

    if not rows:
        parts.append("（汇总表暂无数据行）")
    else:
        for i, row in enumerate(rows, 1):
            fname = (
                fmap.get(file_order[i - 1], "(未知文件)")
                if (i - 1) < len(file_order)
                else "(未知文件)"
            )
            kv_lines = _row_to_kv(headers, row)
            kv_text = "\n".join(f"  {line}" for line in kv_lines)
            parts.append(
                f"▦ 文件内容开始（行号 {i} / 文件名：{fname}）\n"
                f"{kv_text}\n"
                f"▦ 文件内容结束（行号 {i}）"
            )

    text = "\n\n".join(parts)
    if len(text) > _MAX_TABLE_CHARS:
        text = text[:_MAX_TABLE_CHARS] + "\n…（汇总表内容已截断）"
    return text


def _build_generation_record(batch: dict) -> str:
    """构造「汇总表生成时的 LLM 调用记录」上下文：发起的提示词 + 原始回复。

    用于会话调整时让 LLM 同时看到：当初生成汇总表的指令约束，以及模型原始回复，
    从而保证『继续会话调整』与原始生成口径一致。两个字段都为空时返回空串（不污染上下文）。
    """
    prompt = (batch.get("table_prompt") or "").strip()
    reply = (batch.get("table_reply") or "").strip()
    if not prompt and not reply:
        return ""

    parts = [
        "===== 汇总表生成记录（以下为当初生成本汇总表时 LLM 实际调用的提示词与原始回复）====="
    ]
    if prompt:
        if len(prompt) > _GEN_PROMPT_CAP:
            prompt = prompt[:_GEN_PROMPT_CAP] + "\n…（发起提示词已截断）"
        parts.append("【发起的提示词】\n" + prompt)
    if reply:
        if len(reply) > _GEN_REPLY_CAP:
            reply = reply[:_GEN_REPLY_CAP] + "\n…（原始回复已截断）"
        parts.append("【原始回复】\n" + reply)
    parts.append(
        "说明：上方为当初生成汇总表的真实提示词与模型原始回复。当用户要求调整 / 修正 / 补全"
        "汇总表时，请结合此处约束（字段名、单位、照抄 OCR 原文、空值处理等）与原始回复口径，"
        "保持与原始生成一致，不要引入新的字段口径或改写规则。"
    )
    return "\n\n".join(parts)


def _parse_json(raw):
    """安全解析 batch_table：支持 dict / list / JSON 字符串。"""
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


def _row_to_kv(headers, row):
    """把一行（dict 或 list）转成 ['字段名: 字段值', ...] 列表。"""
    if isinstance(row, dict):
        return [f"{k}: {v}" for k, v in row.items()]
    if isinstance(row, (list, tuple)):
        if headers and len(headers) == len(row):
            return [f"{h}: {v}" for h, v in zip(headers, row)]
        return [str(x) for x in row]
    return [str(row)]


@router.get("/{batch_id}/chat")
async def get_chat(batch_id: str, repos=Depends(_get_repos)):
    """返回该批次已有的对话历史（按 seq 升序）与生效的系统角色定义。"""
    if not await repos["batch_repo"].get_by_id(batch_id):
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Batch not found"})
    history = await repos["chat_repo"].get_history(batch_id)
    role = _resolve_role(await repos["setting_repo"].get("llm_role"))
    return {"code": 0, "data": {"batch_id": batch_id, "history": history, "effective_role": role}}


@router.post("/{batch_id}/chat")
async def send_chat(batch_id: str, body: ChatSend, repos=Depends(_get_repos)):
    """发送一条用户消息并获取助手回复（基于批次汇总表上下文）。

    - 普通发送：追加 user + assistant。
    - edit_index：把该 seq 的用户消息内容替换为 message，并丢弃其后所有消息再生成。
    - regenerate：丢弃末尾的助手回复，用最后一条用户消息重新生成。
    所有模式都会把「完整历史 + 批次汇总表」作为上下文发送给 LLM，实现多轮连续会话。
    """
    batch = await repos["batch_repo"].get_by_id(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Batch not found"})

    chat_repo = repos["chat_repo"]
    history = await chat_repo.get_history(batch_id)
    # 生效的系统角色定义（空则用内置默认），供所有返回路径透出，便于前端在会话内容中展示
    role = _resolve_role(await repos["setting_repo"].get("llm_role"))
    is_edit = body.edit_index is not None
    is_regen = bool(body.regenerate)
    user_msg = (body.message or "").strip()
    if not is_edit and not is_regen and not user_msg:
        raise HTTPException(status_code=400, detail={"code": 400, "message": "消息内容不能为空"})

    if body.regenerate:
        # 找到最后一条 user 消息的 seq，丢弃其后所有消息（含旧的 assistant 回复）
        last_user = next((m for m in reversed(history) if m["role"] == "user"), None)
        if not last_user:
            raise HTTPException(status_code=400, detail={"code": 400, "message": "没有可重新生成的对话"})
        await chat_repo.truncate_after(batch_id, last_user["seq"])
        history = [m for m in history if m["seq"] <= last_user["seq"]]

    elif body.edit_index is not None:
        target = next((m for m in history if m["seq"] == body.edit_index), None)
        if not target or target["role"] != "user":
            raise HTTPException(
                status_code=400,
                detail={"code": 400, "message": "edit_index 必须指向一条用户消息"},
            )
        # 丢弃该消息及其后所有内容，再用编辑后的内容作为新的 user 消息
        await chat_repo.truncate_after(batch_id, body.edit_index - 1)
        history = [m for m in history if m["seq"] < body.edit_index]
        user_row = await chat_repo.add_message(batch_id, "user", user_msg)
        history.append(user_row)
    else:
        user_row = await chat_repo.add_message(batch_id, "user", user_msg)
        history.append(user_row)

    # ===== 模式 A：依据用户指令重新生成汇总表并写回批次 =====
    if body.regenerate_table:
        existing = _parse_json(batch.get("batch_table"))
        if not isinstance(existing, dict) or not (existing.get("tables")):
            assistant_text = "该批次尚未生成汇总表，无法根据指令重新生成。请先生成汇总表。"
            assistant_row = await chat_repo.add_message(batch_id, "assistant", assistant_text)
            history.append(assistant_row)
            return {
                "code": 0,
                "data": {"batch_id": batch_id, "history": history, "table_updated": False, "effective_role": role},
            }

        files = await repos["file_repo"].get_all_for_consolidated(batch_id)
        llm_service = LLMService(repos["setting_repo"])
        regen = await llm_service.regenerate_batch_table(existing, files, user_msg)
        if regen.get("success"):
            await repos["batch_repo"].update_batch_table(
                batch_id,
                json.dumps(regen["result"], ensure_ascii=False),
                prompt=regen.get("prompt"),
                reply=regen.get("raw_reply"),
            )
            new_table = regen["result"]
            first = (new_table.get("tables") or [{}])[0]
            n_rows = len(first.get("rows") or [])
            n_cols = len(first.get("headers") or [])
            assistant_text = (
                f"已根据指令重新生成汇总表：共 {n_rows} 行、{n_cols} 列，"
                "已更新到本批次汇总表，可在左侧表格查看。"
            )
        else:
            assistant_text = f"重新生成汇总表失败：{regen.get('error')}"

        assistant_row = await chat_repo.add_message(batch_id, "assistant", assistant_text)
        history.append(assistant_row)
        return {
            "code": 0,
            "data": {
                "batch_id": batch_id,
                "history": history,
                "table_updated": bool(regen.get("success")),
                "table": regen.get("result") if regen.get("success") else None,
                "effective_role": role,
            },
        }

    # ===== 模式 B：普通多轮问答（基于汇总表上下文）=====
    # 组装发给 LLM 的 messages：system（含 LLM 角色定义 + 批次汇总表上下文 + 当初生成表的提示词/原始回复）+ 完整历史
    table_ctx = _build_table_context(batch, repos["file_repo"])
    system_content = f"{role}\n\n{CHAT_SYSTEM_PROMPT}\n\n{table_ctx}"
    gen_rec = _build_generation_record(batch)
    if gen_rec:
        system_content += "\n\n" + gen_rec
    llm_messages = [{"role": "system", "content": system_content}]
    llm_messages += [{"role": m["role"], "content": m["content"]} for m in history]

    llm_service = LLMService(repos["setting_repo"])
    try:
        reply = await llm_service.chat(llm_messages)
    except ValueError as e:
        # 配置缺失（如未设置 key）：回滚刚写入的用户消息，保证历史干净
        await chat_repo.truncate_after(batch_id, history[0]["seq"] - 1 if history else 0)
        raise HTTPException(status_code=409, detail={"code": 409, "message": str(e)})
    except Exception as e:
        await chat_repo.truncate_after(batch_id, history[0]["seq"] - 1 if history else 0)
        raise HTTPException(status_code=502, detail={"code": 502, "message": f"LLM 调用失败：{e}"})

    if not reply or not reply.strip():
        reply = "（模型未返回内容）"
    assistant_row = await chat_repo.add_message(batch_id, "assistant", reply)
    history.append(assistant_row)

    return {"code": 0, "data": {"batch_id": batch_id, "history": history, "effective_role": role}}


@router.delete("/{batch_id}/chat")
async def clear_chat(batch_id: str, repos=Depends(_get_repos)):
    """清空该批次的对话历史。"""
    if not await repos["batch_repo"].get_by_id(batch_id):
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Batch not found"})
    await repos["chat_repo"].clear(batch_id)
    return {"code": 0, "data": {"batch_id": batch_id, "cleared": True}}
