from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    docling_base_url: str = "http://localhost:5001"
    llm_api_key: str = "your-api-key-here"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    database_path: str = "./data/docling_webui.db"
    upload_dir: str = "./uploads"
    max_file_size_mb: int = 50
    max_zip_size_mb: int = 200
    max_files_per_batch: int = 500
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
