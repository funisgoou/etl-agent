"""统一错误码结构与全局异常处理（SPEC 2.4 / 第 9 章）。

用法：业务代码 raise ApiError("E_FORBIDDEN_DUTY", "...", details={...})，
由全局处理器统一渲染为 {"code", "message", "details", "trace_id"} 信封。
"""

import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)

# 错误码 → HTTP 状态码（未列出的码默认 400；E_INTERNAL 兜底 500）
_CODE_HTTP = {
    "E_AUTH_INVALID_CREDENTIALS": 401,
    "E_AUTH_UNAUTHORIZED": 401,
    "E_FORBIDDEN_PROJECT": 403,
    "E_FORBIDDEN_DUTY": 403,
    "E_TOKEN_INVALID": 401,
    "E_TOKEN_EXPIRED": 401,
    "E_TOKEN_REPLAYED": 401,
    "E_TOKEN_SCOPE": 403,
    "E_NOT_FOUND": 404,
    "E_VALID_USERNAME_TAKEN": 409,
    "E_INTERNAL": 500,
}


class ApiError(Exception):
    """业务错误：携带稳定错误码与可选明细。"""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def _envelope(code: str, message: str, details: dict | None) -> dict:
    return {"code": code, "message": message, "details": details, "trace_id": uuid.uuid4().hex}


def install_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器：ApiError → 4xx 信封；未知异常 → E_INTERNAL。"""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        # 1. 按码段映射 HTTP 状态
        status = _CODE_HTTP.get(exc.code, 400)
        # 2. 服务端留痕（5xx 记 error，其余 info）
        (logger.error if status >= 500 else logger.info)(
            "api_error", code=exc.code, message=exc.message, details=exc.details
        )
        return JSONResponse(status_code=status, content=_envelope(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _valid_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope("E_VALID_REQUEST", "请求参数校验失败", {"errors": exc.errors()[:10]}),
        )

    @app.exception_handler(Exception)
    async def _internal(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", error=str(exc))
        return JSONResponse(status_code=500, content=_envelope("E_INTERNAL", f"服务内部错误: {exc}"))
