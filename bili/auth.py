"""Cookie based auth for Bilibili web APIs."""

from __future__ import annotations

from dataclasses import dataclass

from config import Settings
from util import AuthError

AT_URL = "https://api.bilibili.com/x/msgfeed/at"


@dataclass
class Auth:
    sessdata: str
    csrf_token: str
    dedeuserid: str
    user_agent: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "Auth":
        return cls(
            sessdata=settings.sessdata,
            csrf_token=settings.bili_jct,
            dedeuserid=settings.dedeuserid,
            user_agent=settings.user_agent,
        )

    @property
    def bili_jct(self) -> str:
        """The csrf token, under the name Bilibili uses in its cookies."""
        return self.csrf_token

    @property
    def uid(self) -> int:
        try:
            return int(self.dedeuserid)
        except (TypeError, ValueError):
            return 0

    @property
    def cookie_header(self) -> str:
        def pair(name: str, value: str) -> str:
            return f"{name}={value}"

        parts = []
        if self.sessdata:
            parts.append(pair("SESSDATA", self.sessdata))
        if self.bili_jct:
            parts.append(pair("bili_jct", self.bili_jct))
        if self.dedeuserid:
            parts.append(pair("DedeUserID", self.dedeuserid))
        return "; ".join(parts)

    @property
    def csrf(self) -> str:
        return self.bili_jct

    def headers(self, referer: str = "https://www.bilibili.com/") -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Referer": referer,
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Cookie": self.cookie_header,
        }

    def require_cookie(self) -> None:
        if not self.sessdata:
            raise AuthError(
                "缺少登录凭据 SESSDATA，无法调用 B 站接口。",
                hint=(
                    "把 .env.example 复制成 .env 并填入 SESSDATA（浏览器登录 B 站后，"
                    "开发者工具 → Application → Cookies → bilibili.com）。"
                ),
            )

    def require_sender(self) -> None:
        missing = [
            name
            for name, value in (
                ("SESSDATA", self.sessdata),
                ("BILI_JCT", self.bili_jct),
                ("DEDEUSERID", self.dedeuserid),
            )
            if not value
        ]
        if missing:
            raise AuthError(
                "发送私信缺少凭据：" + ", ".join(missing),
                hint="请在 .env 中同时填好 SESSDATA / BILI_JCT / DEDEUSERID（BILI_JCT 即 csrf）。",
            )
