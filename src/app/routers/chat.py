import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.database import get_db
from app.repositories.file_repo import FileRepo
from app.repositories.setting_repo import SettingRepo
from app.repositories.chat_repo import ChatRepo
from app.services.llm_service import LLMService

router = APIRouter(prefix="/api/v1/files", tags=["chat"])

CHAT_SYSTEM_PROMPT = """你是一个文档智能助手。下面提供了当前文件的 OCR 识别原文（markdown）。
请基于该文档内容回答用户问题；若原文中没有相关信息，请明确说明「文档中未找到相关内容」，
不要编造。回答尽量简洁、使用中文，必要时可用要点或表格呈现。"""

# OCR 原文塞进 system 的安全上限，避免超长上下文
_MAX_OCR_CHARS = 16000


class ChatSend(BaseModel):
    message: Optional[str] = ""        # 用户消息；regenerate/edit_index 模式下可为空
    edit_index: Optional[int] = None   # 指定要编辑的用户消息 seq（编辑后重新生成后续）
    regenerate: Optional[bool] = False  # 仅重新生成最后一条助手回复


def _get_repos(db=Depends(get_db)):
    return {
        "file_repo": FileRepo(db),
        "setting_repo": SettingRepo(db),
        "chat_repo": ChatRepo(db),
    }


@router.get("/{file_id}/chat")
async def get_chat(file_id: str, repos=Depends(_get_repos)):
    """返回该文件已有的对话历史（按 seq 升序）。"""
    if not await repos["file_repo"].get_by_id(file_id):
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})
    history = await repos["chat_repo"].get_history(file_id)
    return {"code": 0, "data": {"file_id": file_id, "history": history}}


@router.post("/{file_id}/chat")
async def send_chat(file_id: str, body: ChatSend, repos=Depends(_get_repos)):
    """发送一条用户消息并获取助手回复。

    - 普通发送：追加 user + assistant。
    - edit_index：把该 seq 的用户消息内容替换为 message，并丢弃其后所有消息再生成。
    - regenerate：丢弃末尾的助手回复，用最后一条用户消息重新生成。
    所有模式都会把「完整历史 + 文档 OCR 原文」作为上下文发送给 LLM，实现多轮连续会话。
    """
    file_data = await repos["file_repo"].get_by_id(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})

    chat_repo = repos["chat_repo"]
    history = await chat_repo.get_history(file_id)
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
        await chat_repo.truncate_after(file_id, last_user["seq"])
        history = [m for m in history if m["seq"] <= last_user["seq"]]

    elif body.edit_index is not None:
        target = next((m for m in history if m["seq"] == body.edit_index), None)
        if not target or target["role"] != "user":
            raise HTTPException(
                status_code=400,
                detail={"code": 400, "message": "edit_index 必须指向一条用户消息"},
            )
        # 丢弃该消息及其后所有内容，再用编辑后的内容作为新的 user 消息
        await chat_repo.truncate_after(file_id, body.edit_index - 1)
        history = [m for m in history if m["seq"] < body.edit_index]
        user_row = await chat_repo.add_message(file_id, "user", user_msg)
        history.append(user_row)
    else:
        user_row = await chat_repo.add_message(file_id, "user", user_msg)
        history.append(user_row)

    # 组装发给 LLM 的 messages：system（含文档上下文）+ 完整历史
    ocr_text = (file_data.get("ocr_md_content") or "").strip()
    if len(ocr_text) > _MAX_OCR_CHARS:
        ocr_text = ocr_text[:_MAX_OCR_CHARS] + "\n…（原文已截断）"
    system_content = CHAT_SYSTEM_PROMPT + (
        f"\n\n===== 当前文件 OCR 原文（{file_data.get('original_filename', '')}）=====\n{ocr_text}"
        if ocr_text else "\n\n（该文件暂无 OCR 原文，请基于常识回答。）"
    )
    llm_messages = [{"role": "system", "content": system_content}]
    llm_messages += [{"role": m["role"], "content": m["content"]} for m in history]

    llm_service = LLMService(repos["setting_repo"])
    try:
        reply = await llm_service.chat(llm_messages)
    except ValueError as e:
        # 配置缺失（如未设置 key）：回滚刚写入的用户消息，保证历史干净
        await chat_repo.truncate_after(file_id, history[0]["seq"] - 1 if history else 0)
        raise HTTPException(status_code=409, detail={"code": 409, "message": str(e)})
    except Exception as e:
        await chat_repo.truncate_after(file_id, history[0]["seq"] - 1 if history else 0)
        raise HTTPException(status_code=502, detail={"code": 502, "message": f"LLM 调用失败：{e}"})

    if not reply or not reply.strip():
        reply = "（模型未返回内容）"
    assistant_row = await chat_repo.add_message(file_id, "assistant", reply)
    history.append(assistant_row)

    return {"code": 0, "data": {"file_id": file_id, "history": history}}


@router.delete("/{file_id}/chat")
async def clear_chat(file_id: str, repos=Depends(_get_repos)):
    """清空该文件的对话历史。"""
    if not await repos["file_repo"].get_by_id(file_id):
        raise HTTPException(status_code=404, detail={"code": 404, "message": "File not found"})
    await repos["chat_repo"].clear(file_id)
    return {"code": 0, "data": {"file_id": file_id, "cleared": True}}
