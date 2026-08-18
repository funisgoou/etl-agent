"""配置模块：集中读取 .env，全项目唯一配置入口（SPEC 2.1）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置：所有可变参数集中于此，代码不散落硬编码。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 控制面存储
    database_url: str = "postgresql+asyncpg://etl:etl@localhost:5432/etlagent"
    redis_url: str = "redis://localhost:6379/0"

    # 本地 Secret Vault（AES-256-GCM 信封加密，接口按 Vault KV v2 抽象，D1）
    secret_master_key: str = ""

    # LLM（OpenAI 兼容协议，全配置化 D6）
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model_id: str = ""
    llm_timeout_seconds: int = 120

    # 数据面
    seatunnel_url: str = "http://localhost:5801"
    doris_host: str = "localhost"
    doris_port: int = 19030
    doris_user: str = "root"
    doris_password: str = ""
    doris_database: str = "ods"
    doris_dryrun_database: str = "tmp_dry_run"

    # MinIO（CSV 文件资产，C3）
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin123"
    minio_bucket: str = "etl-assets"
    minio_secure: bool = False

    # 治理参数
    capability_ttl_seconds: int = 300
    dry_run_sample_limit: int = 1000
    gate_max_repair_rounds: int = 3
    preparation_ttl_hours: int = 72


@lru_cache
def get_settings() -> Settings:
    """配置单例。"""
    return Settings()
