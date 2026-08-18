"""MinIO 客户端（SPEC 2.8）：CSV 文件资产存取（C3）。"""

from minio import Minio

from app.core.config import get_settings

# 模块级单例；Minio 客户端本身线程安全且无事件循环绑定，可惰性创建
_client: Minio | None = None


def minio_client() -> Minio:
    """取 MinIO 客户端（首次调用时创建并确保 bucket 存在）。"""
    global _client
    if _client is None:
        s = get_settings()
        _client = Minio(s.minio_endpoint, s.minio_access_key, s.minio_secret_key, secure=s.minio_secure)
        if not _client.bucket_exists(s.minio_bucket):
            _client.make_bucket(s.minio_bucket)
    return _client
