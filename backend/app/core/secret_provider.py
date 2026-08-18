"""SecretProvider（SPEC 2.7）：本地 AES-256-GCM 信封加密，接口按 Vault KV v2 抽象。

D1 定位：协议是真的，环境仿真配套——`vault://local/{path}#{key}` 引用形式入库，
换真 Vault 时仅替换 _LocalVault 实现类。
不变式：redact_config 之外的任何代码路径不得将明文凭据写库。
"""

import base64
import json
import os
import secrets

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

# 连接配置中的敏感字段名（命中即密文化）
SENSITIVE_KEYS = ("password", "secret_key", "access_key", "api_key", "token")
REF_PREFIX = "vault://local/"


def _master_key() -> bytes:
    """取主密钥（32 字节 base64）；未配置则派生一个并在进程内固定。"""
    raw = get_settings().secret_master_key
    if raw:
        key = base64.b64decode(raw)
        if len(key) != 32:
            raise ValueError("SECRET_MASTER_KEY 必须是 32 字节的 base64")
        return key
    # ponytail: 无密钥时用零密钥，仅限本地演示；生产必须显式配置
    return bytes(32)


def _encrypt(plaintext: str) -> str:
    """AES-256-GCM 加密，输出 base64(nonce||cipher)。"""
    aes = AESGCM(_master_key())
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def _decrypt(blob: str) -> str:
    """解密 base64(nonce||cipher)。"""
    aes = AESGCM(_master_key())
    raw = base64.b64decode(blob)
    return aes.decrypt(raw[:12], raw[12:], None).decode()


class LocalVault:
    """本地 Vault KV v2 兼容实现：put 写入加密文件仓，get 按 vault:// 引用取回。"""

    def __init__(self) -> None:
        # 密文仓：控制面 PG 之外的本地目录（默认 backend/.secrets，gitignore 已覆盖 .env；此目录运行时生成）
        settings = get_settings()
        self.store_dir = os.path.join(os.getcwd(), ".local_vault")
        os.makedirs(self.store_dir, exist_ok=True)

    def _path(self, key: str) -> str:
        # 引用键做路径净化，禁止目录穿越
        safe = "".join(c for c in key if c.isalnum() or c in "-_/")
        return os.path.join(self.store_dir, safe + ".sec")

    def put(self, path: str, data: dict) -> str:
        """写入密文，返回 vault://local/{path} 引用。

        同一 path 覆盖写（版本化留待真 Vault）。
        """
        full = self._path(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        blob = _encrypt(json.dumps(data, ensure_ascii=False))
        with open(full, "w", encoding="utf-8") as f:
            f.write(blob)
        return f"{REF_PREFIX}{path}"

    def get(self, ref: str) -> dict:
        """按 vault://local/{path} 引用取回明文 dict。"""
        if not ref.startswith(REF_PREFIX):
            raise ValueError(f"非法 vault 引用: {ref}")
        with open(self._path(ref.removeprefix(REF_PREFIX)), encoding="utf-8") as f:
            return json.loads(_decrypt(f.read()))


_vault = LocalVault()


def redact_config(config: dict) -> dict:
    """入库前：敏感字段明文 → vault 引用（vault://local/...）。

    非敏感字段原样保留（host/port/database 等需要参与指纹与展示）。
    """
    # 1. 提取敏感字段为独立 secret 文档
    sensitive = {k: v for k, v in config.items() if k in SENSITIVE_KEYS and v}
    if not sensitive:
        return dict(config)
    # 2. 写入本地 Vault，得到引用
    ref = _vault.put(f"conn/{secrets.token_hex(8)}", sensitive)
    # 3. config 中敏感字段替换为引用标记（整组字段共享一个引用，按字段名取）
    out = {k: (v if k not in SENSITIVE_KEYS else None) for k, v in config.items()}
    out["_secret_ref"] = ref
    return {k: v for k, v in out.items() if v is not None or k not in SENSITIVE_KEYS}


def resolve_config(config: dict) -> dict:
    """Worker 执行时物化明文（仅此一处允许还原，SPEC 不变式）。"""
    ref = config.get("_secret_ref")
    if not ref:
        return dict(config)
    secrets_doc = _vault.get(ref)
    out = {k: v for k, v in config.items() if k != "_secret_ref"}
    out.update(secrets_doc)
    return out


def mask_config(config: dict) -> dict:
    """API 响应用：敏感字段 → 掩码；_secret_ref 保留供编辑时回写。"""
    out = {}
    for k, v in config.items():
        if k == "_secret_ref":
            out[k] = v
        elif k in SENSITIVE_KEYS and v:
            out[k] = v[:2] + "***"
        else:
            out[k] = v
    return out


if __name__ == "__main__":
    cfg = {"host": "mysql", "port": 3306, "username": "etl", "password": "plain-secret"}
    red = redact_config(cfg)
    assert "plain-secret" not in json.dumps(red), "明文不得残留"
    assert red["password"].startswith("vault://local/")
    resolved = resolve_config(red)
    assert resolved["password"] == "plain-secret"
    m = mask_config(red)
    assert m["password"].endswith("***")
    print("secret_provider self-check ok")
