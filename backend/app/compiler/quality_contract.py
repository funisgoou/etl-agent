"""契约编译器（SPEC 第 6 章）：QualityContract JSON → Doris 方言分流 SQL。

纯函数、确定性、无 IO；输出仅白名单形态：
  INSERT INTO {t}__shadow SELECT <脱敏列> FROM {t}__raw WHERE <全部规则通过>
  INSERT INTO {t}__err    SELECT *, <run 元数据> FROM {t}__raw WHERE NOT (<全部规则通过>)
表名/列名经白名单字符校验（防注入）。

QualityContract 结构（etl_plan_json.quality_contract）：
{
  "table": "dwd_orders",
  "columns": ["id","order_no","amount"],          # 参与搬运的列（含脱敏后）
  "rules": [
    {"column":"order_no","operator":"not_null","error_code":"E_NOT_NULL"},
    {"column":"amount","operator":"positive","error_code":"E_NOT_POSITIVE"},
    {"column":"email","operator":"email_format","error_code":"E_BAD_EMAIL"}
  ],
  "masking": [{"column":"email","operator":"mask_email"}]
}
"""

import re
from dataclasses import dataclass

# 标识符白名单：字母数字下划线（拒绝任何注入形态）
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 算子 → SQL 谓词模板（? 为列名占位）
_OPERATOR_PREDICATES: dict[str, str] = {
    "not_null": "`{col}` IS NOT NULL",
    "positive": "`{col}` > 0",
    "not_empty": "`{col}` IS NOT NULL AND `{col}` != ''",
    "email_format": "`{col}` REGEXP '^[^@]+@[^@]+\\\\.[^@]+$'",
}

# 脱敏算子 → SELECT 表达式模板
_MASKING_EXPRS: dict[str, str] = {
    "mask_email": "regexp_replace(`{col}`, '^(.)[^@]*(@.*)$', '\\\\1***\\\\2')",
    "mask_phone": "regexp_replace(`{col}`, '^(.{3}).*(.{4})$', '\\\\1****\\\\2')",
}


class ContractCompileError(ValueError):
    """契约编译失败（门禁 blocking 项来源之一）。"""


def _check_ident(name: str) -> str:
    """标识符白名单校验。"""
    if not _IDENT.match(name):
        raise ContractCompileError(f"非法标识符: {name!r}")
    return name


@dataclass(frozen=True, slots=True)
class SplitSql:
    """编译产物。"""

    shadow_sql: str
    err_sql: str


def _all_pass_expr(rules: list[dict]) -> str:
    """全部规则通过的条件表达式。"""
    parts = []
    for r in rules:
        op, col = r.get("operator"), _check_ident(r.get("column", ""))
        tmpl = _OPERATOR_PREDICATES.get(op)
        if tmpl is None:
            raise ContractCompileError(f"未知算子: {op}")
        parts.append(tmpl.format(col=col))
    return " AND ".join(parts) if parts else "TRUE"


def _select_columns(columns: list[str], masking: list[dict]) -> str:
    """SELECT 列表：脱敏列替换为脱敏表达式。"""
    mask_map = {}
    for m in masking:
        col, op = _check_ident(m.get("column", "")), m.get("operator")
        if op not in _MASKING_EXPRS:
            raise ContractCompileError(f"未知脱敏算子: {op}")
        mask_map[col] = _MASKING_EXPRS[op].format(col=col)
    cols = []
    for c in columns:
        c = _check_ident(c)
        cols.append(mask_map.get(c, f"`{c}`"))
    return ", ".join(cols) if cols else "*"


def compile_split(contract: dict, table: str | None = None) -> SplitSql:
    """编译契约为 Doris 分流 SQL 对。

    Args:
        contract: QualityContract JSON。
        table: 目标表名（缺省取 contract.table）。

    Returns:
        SplitSql（shadow_sql / err_sql）。

    Raises:
        ContractCompileError: 契约非法（未知算子/非法标识符）。
    """
    t = _check_ident(table or contract.get("table", ""))
    rules = contract.get("rules", [])
    columns = contract.get("columns", [])
    masking = contract.get("masking", [])
    cond = _all_pass_expr(rules)
    sel = _select_columns(columns, masking)
    # 1. 合格行 → __shadow（SELECT 列表内完成脱敏，D5 硬约束 5）
    shadow_sql = f"INSERT INTO `{t}__shadow` ({', '.join(f'`{c}`' for c in columns)}) SELECT {sel} FROM `{t}__raw` WHERE {cond}"
    # 2. 违规行 → __err（追加错误码 CASE 与 run 元数据列）
    err_codes = " ".join(
        f"WHEN NOT ({_OPERATOR_PREDICATES[r['operator']].format(col=_check_ident(r['column']))}) THEN '{r.get('error_code', 'E_QUALITY')}'"
        for r in rules
    )
    err_sql = (
        f"INSERT INTO `{t}__err` SELECT *, CASE {err_codes} ELSE 'E_QUALITY' END AS `__error_code` "
        f"FROM `{t}__raw` WHERE NOT ({cond})"
    )
    return SplitSql(shadow_sql=shadow_sql, err_sql=err_sql)


def compile(contract_json: dict, dialect: str = "doris", table: str | None = None) -> SplitSql:
    """方言分发入口（扩展点：新方言加分支）。"""
    if dialect != "doris":
        raise ContractCompileError(f"不支持的方言: {dialect}")
    return compile_split(contract_json, table)


if __name__ == "__main__":
    contract = {
        "table": "dwd_orders",
        "columns": ["id", "order_no", "amount"],
        "rules": [
            {"column": "order_no", "operator": "not_null", "error_code": "E_NOT_NULL"},
            {"column": "amount", "operator": "positive", "error_code": "E_NOT_POSITIVE"},
        ],
    }
    sql = compile(contract)
    assert sql.shadow_sql.startswith("INSERT INTO `dwd_orders__shadow`")
    assert "`order_no` IS NOT NULL AND `amount` > 0" in sql.shadow_sql
    assert "E_NOT_POSITIVE" in sql.err_sql
    # 注入拦截
    try:
        compile({**contract, "table": "t; DROP TABLE x"})
        raise SystemExit("应当拦截非法表名")
    except ContractCompileError:
        pass
    # 脱敏
    c2 = {
        "table": "dwd_customers",
        "columns": ["id", "email"],
        "rules": [{"column": "email", "operator": "email_format", "error_code": "E_BAD_EMAIL"}],
        "masking": [{"column": "email", "operator": "mask_email"}],
    }
    s2 = compile(c2)
    assert "regexp_replace" in s2.shadow_sql
    print("compiler self-check ok")
