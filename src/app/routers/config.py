from fastapi import APIRouter, Depends, HTTPException

from app.db.database import get_db
from app.repositories.setting_repo import SettingRepo
from app.services.llm_service import LLMService, DEFAULT_LLM_ROLE, resolve_llm_role
from app.models.schemas import (
    ApiResponse,
    ConfigResponse,
    ConfigResponseData,
    ConfigUpdate,
    LLMTestRequest,
)

def _build_config_payload(config: dict) -> ConfigResponseData:
    """根据配置字典构造返回给前端的 ConfigResponseData（GET/PUT 两处共用，消除重复）。"""
    llm_api_key = config.get("llm_api_key", "")
    llm_api_key_set = bool(llm_api_key) and llm_api_key != "your-api-key-here"
    return ConfigResponseData(
        docling_base_url=config.get("docling_base_url", ""),
        llm_base_url=config.get("llm_base_url", ""),
        llm_model=config.get("llm_model", ""),
        llm_api_key_set=llm_api_key_set,
        llm_role=resolve_llm_role(config.get("llm_role")),
        default_llm_role=DEFAULT_LLM_ROLE,
        docling_ocr_engine=config.get("docling_ocr_engine", "rapidocr"),
        docling_table_mode=config.get("docling_table_mode", "accurate"),
        docling_image_export_mode=config.get("docling_image_export_mode", "referenced"),
        max_concurrent_conversions=int(config.get("max_concurrent_conversions", 5)),
        poll_interval_seconds=int(config.get("poll_interval_seconds", 2)),
    )


router = APIRouter(prefix="/api/v1/config", tags=["config"])


async def get_repo(db=Depends(get_db)):
    return SettingRepo(db)


@router.get("")
async def get_config(repo: SettingRepo = Depends(get_repo)):
    config = await repo.get_all()
    return ConfigResponse(data=_build_config_payload(config))


@router.put("")
async def update_config(
    update: ConfigUpdate,
    repo: SettingRepo = Depends(get_repo),
):
    update_dict = update.model_dump(exclude_none=True)
    for key, value in update_dict.items():
        await repo.set(key, str(value))

    config = await repo.get_all()
    return ConfigResponse(data=_build_config_payload(config))


@router.get("/llm-models")
async def list_llm_models(
    base_url: str | None = None,
    api_key: str | None = None,
    repo: SettingRepo = Depends(get_repo),
):
    """拉取 OpenAI 兼容服务商的模型列表（支持传入未保存的覆盖值）。"""
    svc = LLMService(repo)
    try:
        models = await svc.list_models(base_url_override=base_url, api_key_override=api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(data={"models": models})


@router.post("/test-llm")
async def test_llm(
    body: LLMTestRequest,
    repo: SettingRepo = Depends(get_repo),
):
    """用最小 chat 请求验证 LLM 配置（支持传入未保存的覆盖值）。"""
    svc = LLMService(repo)
    res = await svc.test_connection(
        model_override=body.model,
        base_url_override=body.base_url,
        api_key_override=body.api_key,
    )
    return ApiResponse(data=res)


@router.post("/test-docling")
async def test_docling(
    body: dict | None = None,
    repo: SettingRepo = Depends(get_repo),
):
    """用 /health 端点验证 Docling Serve 地址可达（支持传入未保存的覆盖值）。"""
    from app.services.docling_service import DoclingService

    base_url = (body or {}).get("docling_base_url") if body else None
    svc = DoclingService(repo)
    res = await svc.test_connection(base_url_override=base_url)
    return ApiResponse(data=res)
