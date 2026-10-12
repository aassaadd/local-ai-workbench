"""访问认证：基于配置密码的令牌校验。

设计：密码来自环境变量 ``WORKBENCH_PASSWORD``（空表示不校验，开箱即用）。
- REST 请求：通过请求头 ``X-Auth-Token`` 或查询参数 ``?token=`` 携带令牌；
- 文件直链下载：``<a>`` 标签无法自定义请求头，只能用 ``?token=``；
- WebSocket：握手阶段用查询参数 ``?token=``。

所有比较均使用 ``secrets.compare_digest`` 做常量时间比较，避免时序攻击。
"""
import secrets

from fastapi import Header, HTTPException, Query

from . import config


def verify_token(token: str | None) -> bool:
    """校验令牌是否有效。

    功能：未配置密码时恒返回 True（不校验）；否则与配置密码做常量时间比较。
    参数：token —— 客户端携带的令牌，可能为 None/空串。
    返回值：校验通过返回 True，否则返回 False。
    """
    if not config.ACCESS_PASSWORD:
        return True
    if not token:
        return False
    return secrets.compare_digest(str(token), str(config.ACCESS_PASSWORD))


async def require_auth(
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    """FastAPI 依赖：校验请求令牌。

    功能：优先读取请求头 ``X-Auth-Token``，其次读取查询参数 ``token``；
          校验失败抛出 401 未授权。
    参数：x_auth_token —— 请求头令牌；token —— 查询参数令牌（供文件直链使用）。
    返回值：无（校验通过时正常返回，失败时抛 HTTPException）。
    """
    if not verify_token(x_auth_token or token):
        raise HTTPException(status_code=401, detail="未授权")


def ws_token_ok(token: str | None) -> bool:
    """校验 WebSocket 连接令牌。

    功能：WebSocket 无法自定义请求头，只能用查询参数携带令牌，此处统一校验。
    参数：token —— WebSocket 握手时 ``?token=`` 传入的令牌。
    返回值：校验通过返回 True，否则返回 False。
    """
    return verify_token(token)