from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.database import get_db
from app.repositories.batch_repo import BatchRepo
from app.repositories.file_repo import FileRepo
from app.repositories.setting_repo import SettingRepo
from app.repositories.chat_repo import ChatRepo
from app.services.llm_service import LLMService

router = APIRouter(prefix="/api/v1/batches", tags=["chat"])

CHAT_SYSTEM_PROMPT = """你是一个「文档批次」智能分析助手。
下面提供了当前【批次汇总表】的数据（JSON 格式），其中每一行对应一个文件，列是各文件的提取字段。
请基于这张汇总表回答用户问题；若表中没有相关信息，请明确说明「汇总表中未找到相关内容」，不要编造。
回答尽量简洁、使用中文，必要时可用要点或表格呈现。

关于坐标与定位：汇总表只含结构化字段值，不含图像坐标；如需定位某字段在原始文件中的位置，请提示用户到页面右侧「识别的字段」中点击对应字段查看。"""

# 汇总表 JSON 塞进 system 的安全上限，避免超长上下文
_MAX_TABLE_CHARS = 24000


class ChatSend(BaseModel):
    message: Optional[str] = ""        # 用户消息；regenerate/edit_index 模式下可为空
    edit_index: Optional[int] = None   # 指定要编辑的用户消息 seq（编辑后重新生成后续）
    regenerate: Optional[bool] = False  # 仅重新生成最后一条助手回复


def _get_repos(db=Depends(get_db)):
    return {
        "batch_repo": BatchRepo(db),
        "file_repo": FileRepo(db),
        "setting_repo": SettingRepo(db),
        "chat_repo": ChatRepo(db),
    }


def _build_table_context(batch: dict, file_repo: FileRepo) -> str:
    """构造发给 LLM 的汇总表上下文（含文件名映射）。"""
    raw = batch.get("batch_table")
    table_json = None
    if isinstance(raw, (dict, list)):
        table_json = raw
    elif isinstance(raw, str) and raw.strip():
        import json as _json
        try:
            table_json = _json.loads(raw)
        except Exception:
            table_json = None

    parts = []
    if table_json:
        text = _json.dumps(table_json, ensure_ascii=False)
        if len(text) > _MAX_TABLE_CHARS:
            text = text[:_MAX_TABLE_CHARS] + "\n…（汇总表已截断）"
        parts.append("===== 批次汇总表（JSON，每行 = 一个文件）=====\n" + text)
    else:
        parts.append("（该批次尚未生成汇总表）")

    # 文件名映射：file_order 中的文件 id -> 原始文件名
    file_order = (table_json or {}).get("file_order") if isinstance(table_json, dict) else None
    if file_order:
        try:
            files = file_repo.list_by_ids(file_order)
            fmap = {f["id"]: f.get("original_filename", "") for f in files}
            lines = [f"{i + 1}. {fmap.get(fid, '(未知文件)')}" for i, fid in enumerate(file_order)]
            if lines:
                parts.append("===== 行序号 → 文件名 =====\n" + "\n".join(lines))
        except Exception:
            pass

    return "\n\n".join(parts)


@router.get("/{batch_id}/chat")
async def get_chat(batch_id: str, repos=Depends(_get_repos)):
    """返回该批次已有的对话历史（按 seq 升序）。"""
    if not await repos["batch_repo"].get_by_id(batch_id):
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Batch not found"})
    history = await repos["chat_repo"].get_history(batch_id)
    return {"code": 0, "data": {"batch_id": batch_id, "history": history}}


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

    # 组装发给 LLM 的 messages：system（含批次汇总表上下文）+ 完整历史
    table_ctx = _build_table_context(batch, repos["file_repo"])
    system_content = CHAT_SYSTEM_PROMPT + "\n\n" + table_ctx
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

    return {"code": 0, "data": {"batch_id": batch_id, "history": history}}


@router.delete("/{batch_id}/chat")
async def clear_chat(batch_id: str, repos=Depends(_get_repos)):
    """清空该批次的对话历史。"""
    if not await repos["batch_repo"].get_by_id(batch_id):
        raise HTTPException(status_code=404, detail={"code": 404, "message": "Batch not found"})
    await repos["chat_repo"].clear(batch_id)
    return {"code": 0, "data": {"batch_id": batch_id, "cleared": True}}
