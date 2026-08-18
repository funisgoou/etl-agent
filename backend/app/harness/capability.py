"""Capability 签发与验签（SPEC 4.3 / D2）：Ed25519 + nonce 存证表。

不变式：明文令牌不落库（仅存 token_digest 与 nonce，双 UNIQUE）；
消费 = 单事务原子置位 consumed_at，影响行数 0 即拒绝（重放/过期）。
"""

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.secret_provider import _decrypt, _encrypt
from app.db_model import CapabilityToken, Keyring

logger = structlog.get_logger(__name__)

# 活跃密钥（进程内缓存；首次签发/验签时从 keyring 表加载或生成）
_priv: Ed25519PrivateKey | None = None
_key_id: str = ""


def _serialize_priv(key: Ed25519PrivateKey) -> bytes:
    """Ed25519 私钥 → PKCS8 PEM → bytes。"""
    from cryptography.hazmat.primitives import serialization

    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _load_priv(pem: bytes) -> Ed25519PrivateKey:
    """PEM bytes → Ed25519 私钥。"""
    from cryptography.hazmat.primitives import serialization

    return serialization.load_pem_private_key(pem, password=None)  # type: ignore[return-value]


async def ensure_keypair(session: AsyncSession) -> None:
    """加载或生成签名密钥对：私钥加密存 keyring 表（每进程首次调用时执行）。"""
    global _priv, _key_id
    if _priv is not None:
        return
    row = (await session.execute(select(Keyring).order_by(Keyring.id.desc()).limit(1))).scalar_one_or_none()
    if row is None:
        # 1. 生成并加密入库（密文以 base64 文本存 BYTEA）
        _priv = Ed25519PrivateKey.generate()
        _key_id = f"cap-{secrets.token_hex(4)}"
        session.add(
            Keyring(
                key_id=_key_id,
                public_key_b64=base64.b64encode(
                    _priv.public_key().public_bytes_raw()
                ).decode(),
                encrypted_private_key=_encrypt(_serialize_priv(_priv).decode()).encode(),
            )
        )
        await session.flush()
        logger.info("capability_keypair_generated", key_id=_key_id)
    else:
        # 2. 加载既有密钥
        _key_id = row.key_id
        _priv = _load_priv(_decrypt(row.encrypted_private_key.decode()).encode())


@dataclass(frozen=True, slots=True)
class CapabilityClaims:
    """验签通过的令牌声明。"""

    tool: str
    subject_id: int
    artifact_digest: str
    nonce: str
    token_digest: str


def _sign(payload: bytes) -> bytes:
    """Ed25519 签名。"""
    return _priv.sign(payload)


def _verify(pub_b64: str, payload: bytes, sig: bytes) -> bool:
    """Ed25519 验签（公钥来自 keyring，不信任令牌内嵌公钥）。"""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64)).verify(sig, payload)
        return True
    except Exception:
        return False


async def issue(
    session: AsyncSession,
    tool: str,
    subject_id: int,
    artifact_digest: str,
) -> str:
    """签发短时单次令牌，返回明文令牌（仅此一次）。

    令牌结构：base64url(payload).base64url(sig)；
    payload = {"tool","subject","digest","nonce","exp","kid"}。
    """
    await ensure_keypair(session)
    # 1. 构造声明
    exp = datetime.now(UTC) + timedelta(seconds=get_settings().capability_ttl_seconds)
    nonce = secrets.token_hex(16)
    payload = {
        "tool": tool,
        "subject": subject_id,
        "digest": artifact_digest,
        "nonce": nonce,
        "exp": int(exp.timestamp()),
        "kid": _key_id,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = _sign(body)
    token = (
        base64.urlsafe_b64encode(body).decode().rstrip("=")
        + "."
        + base64.urlsafe_b64encode(sig).decode().rstrip("=")
    )
    # 2. 存证（token_digest + nonce 双 UNIQUE）
    session.add(
        CapabilityToken(
            token_digest=hashlib.sha256(token.encode()).hexdigest(),
            subject_id=subject_id,
            tool_intent=tool,
            artifact_digest=artifact_digest,
            nonce=nonce,
            expires_at=exp,
        )
    )
    await session.flush()
    return token


def decode_token(token: str) -> tuple[dict, bytes] | None:
    """解析令牌为 (payload, signature)；结构非法返回 None。"""
    try:
        body_b64, sig_b64 = token.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        body = base64.urlsafe_b64decode(pad(body_b64))
        sig = base64.urlsafe_b64decode(pad(sig_b64))
        return json.loads(body), sig
    except Exception:
        return None


async def verify_and_consume(
    session: AsyncSession,
    token: str,
    expected_tool: str,
    expected_digest: str | None = None,
) -> CapabilityClaims:
    """验签 + 原子消费（Replay Guard）。

    流程：结构解析 → 验签（keyring 公钥）→ 声明比对 → 单事务置位 consumed_at。
    Raises:
        ApiError: E_TOKEN_INVALID / E_TOKEN_EXPIRED / E_TOKEN_REPLAYED / E_TOKEN_SCOPE。
    """
    from app.core.errors import ApiError

    # 1. 结构与签名
    parsed = decode_token(token)
    if parsed is None:
        raise ApiError("E_TOKEN_INVALID", "令牌结构非法")
    payload, sig = parsed
    kid = payload.get("kid", "")
    key_row = (await session.execute(select(Keyring).where(Keyring.key_id == kid))).scalar_one_or_none()
    if key_row is None or not _verify(key_row.public_key_b64, json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), sig):
        raise ApiError("E_TOKEN_INVALID", "令牌验签失败")

    # 2. 绑定校验
    if payload["tool"] != expected_tool:
        raise ApiError("E_TOKEN_SCOPE", f"令牌工具不匹配: {payload['tool']} != {expected_tool}")
    if expected_digest and payload["digest"] != expected_digest:
        raise ApiError("E_TOKEN_SCOPE", "令牌制品指纹不匹配")
    if int(payload["exp"]) < int(datetime.now(UTC).timestamp()):
        raise ApiError("E_TOKEN_EXPIRED", "令牌已过期")

    # 3. 单事务原子消费（行数 0 = 重放或已过期）
    digest = hashlib.sha256(token.encode()).hexdigest()
    result = await session.execute(
        update(CapabilityToken)
        .where(
            CapabilityToken.token_digest == digest,
            CapabilityToken.consumed_at.is_(None),
            CapabilityToken.expires_at > datetime.now(UTC),
        )
        .values(consumed_at=datetime.now(UTC))
    )
    if result.rowcount == 0:
        raise ApiError("E_TOKEN_REPLAYED", "令牌已被消费或已过期（Replay Guard 拦截）")
    return CapabilityClaims(
        tool=payload["tool"],
        subject_id=int(payload["subject"]),
        artifact_digest=payload["digest"],
        nonce=payload["nonce"],
        token_digest=digest,
    )


async def purge_expired(session: AsyncSession) -> int:
    """清理过期且未消费令牌（保留存证 7 天后物理清理，周期任务调用）。"""
    cutoff = datetime.now(UTC) - timedelta(days=7)
    res = await session.execute(
        delete(CapabilityToken).where(CapabilityToken.expires_at < cutoff)
    )
    return res.rowcount or 0
