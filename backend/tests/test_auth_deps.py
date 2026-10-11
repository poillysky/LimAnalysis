"""统一鉴权依赖的隔离单测。

覆盖 app/api/deps.py 的关键分支：
- 缺凭证 / 凭证格式错误 → 401
- 令牌无效 / 过期 → 401
- 账号不存在 / 已停用 → 401
- 普通用户走 require_admin → 403
- 管理员放行

全部桩掉 parse_token 与 get_user，不碰数据库、不依赖 meta 初始化。
"""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi.security import HTTPAuthorizationCredentials

from app.api import deps


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class ExtractTokenTest(unittest.TestCase):
    def test_missing_credentials_raises(self) -> None:
        with self.assertRaises(deps.AuthError) as ctx:
            deps._extract_token(None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_blank_credentials_raises(self) -> None:
        with self.assertRaises(deps.AuthError):
            deps._extract_token(_creds("   "))

    def test_valid_credentials_returned(self) -> None:
        self.assertEqual(deps._extract_token(_creds("abc.def")), "abc.def")


class CurrentUserTest(unittest.TestCase):
    def test_invalid_token_maps_to_401(self) -> None:
        with mock.patch.object(
            deps, "parse_token", side_effect=PermissionError("登录已失效")
        ), self.assertRaises(deps.AuthError) as ctx:
            deps.current_user(_creds("bad"))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_unknown_user_maps_to_401(self) -> None:
        with (
            mock.patch.object(deps, "parse_token", return_value="ghost"),
            mock.patch.object(deps, "get_user", return_value=None),self.assertRaises(deps.AuthError)
        ):
            deps.current_user(_creds("ok"))

    def test_disabled_user_maps_to_401(self) -> None:
        with (
            mock.patch.object(deps, "parse_token", return_value="bob"),
            mock.patch.object(
                deps, "get_user", return_value={"username": "bob", "enabled": False}
            ),self.assertRaises(deps.AuthError)
        ):
            deps.current_user(_creds("ok"))

    def test_enabled_user_returned(self) -> None:
        user = {"username": "bob", "role": "common", "enabled": True}
        with (
            mock.patch.object(deps, "parse_token", return_value="bob"),
            mock.patch.object(deps, "get_user", return_value=user),
        ):
            self.assertEqual(deps.current_user(_creds("ok")), user)


class RequireAdminTest(unittest.TestCase):
    def test_common_role_forbidden(self) -> None:
        with self.assertRaises(deps.AuthError) as ctx:
            deps.require_admin({"username": "bob", "role": "common"})
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_allowed(self) -> None:
        admin = {"username": "root", "role": "admin"}
        self.assertEqual(deps.require_admin(admin), admin)


class AuthErrorResponseTest(unittest.TestCase):
    def test_response_shape_matches_frontend_contract(self) -> None:
        resp = deps.auth_error_response(deps.AuthError("缺少登录凭证", 401))
        self.assertEqual(resp.status_code, 401)
        body = resp.body.decode("utf-8")
        self.assertIn('"success":false', body.replace(" ", ""))
        self.assertIn("缺少登录凭证", body)


if __name__ == "__main__":
    unittest.main()
