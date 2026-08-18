"""密码散列底层实现：pbkdf2_sha256（标准库，无外部依赖）。

与 passlib 兼容的摘要格式 `$pbkdf2-sha256$<iters>$<salt_b64>$<dk_b64>`，
后续切换 bcrypt 只需替换本文件。
"""

import base64
import hashlib
import hmac
import os

_ITERATIONS = 240_000


def hash_password_raw(plain: str) -> str:
    """生成带盐散列。"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, _ITERATIONS)
    return "$pbkdf2-sha256${}${}${}".format(
        _ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password_hash(plain: str, hashed: str) -> bool:
    """恒定时间比对校验。"""
    try:
        _, scheme, iters, salt_b64, dk_b64 = hashed.split("$")
        if scheme != "pbkdf2-sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        actual = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, int(iters))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


if __name__ == "__main__":
    h = hash_password_raw("S3cure!pwd")
    assert verify_password_hash("S3cure!pwd", h)
    assert not verify_password_hash("wrong", h)
    print("security_util self-check ok")
