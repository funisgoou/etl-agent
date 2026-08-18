"""敏感字段掩码（SPEC 2.5）：API 响应与探查样本统一走这里。"""

import re


def mask_value(value: str, kind: str) -> str:
    """按类型掩码：email 保留首字符与域名；phone 保留前 3 后 4；secret 保留前 2。

    Args:
        value: 原始值。
        kind: email / phone / secret。

    Returns:
        掩码后的字符串；空值原样返回。
    """
    if not value:
        return value
    if kind == "email":
        return re.sub(r"^(.).*(@.*)$", r"\1***\2", value)
    if kind == "phone":
        return re.sub(r"^(.{3}).*(.{4})$", r"\1****\2", value)
    # secret / 其他
    return value[:2] + "***"


# 列名 → 掩码类型（探查样本入库前按列名模式识别敏感列）
SENSITIVE_COLUMN_PATTERNS: dict[str, str] = {
    "email": "email",
    "phone": "phone",
    "mobile": "phone",
    "id_card": "secret",
    "password": "secret",
    "secret": "secret",
    "token": "secret",
    "api_key": "secret",
    "access_key": "secret",
}


def mask_cell(column: str, value) -> object:
    """探查样本单格脱敏：命中敏感列名模式的字符串值做掩码，其余原样。"""
    if not isinstance(value, str):
        return value
    for pattern, kind in SENSITIVE_COLUMN_PATTERNS.items():
        if pattern in column.lower():
            return mask_value(value, kind)
    return value


if __name__ == "__main__":
    assert mask_value("zhangsan@163.com", "email") == "z***@163.com"
    assert mask_value("13812346672", "phone") == "138****6672"
    assert mask_value("abcd1234", "secret") == "ab***"
    assert mask_cell("user_email", "a@b.com") == "a***@b.com"
    print("masking self-check ok")
