"""Poll the 「@我的」 notification feed."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import requests

from bili.auth import Auth
from util import ApiError

AT_URL = "https://api.bilibili.com/x/msgfeed/at"
BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")

# Fields that may carry the target bvid, in priority order.
_BV_FIELDS = ("uri", "native_uri", "source_content", "title", "desc", "jump_url")


@dataclass
class AtItem:
    item_id: str
    bv: str | None
    mid: int
    uname: str
    title: str
    at_time: int
    raw_uri: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "bv": self.bv,
            "mid": self.mid,
            "uname": self.uname,
            "title": self.title,
            "at_time": self.at_time,
        }


def extract_bv(*candidates: str | None) -> str | None:
    for value in candidates:
        if not value:
            continue
        match = BV_RE.search(str(value))
        if match:
            return match.group(1)
    return None


def _nested(*sources: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for src in sources:
        if isinstance(src, dict):
            merged.update(src)
    return merged


def parse_at_items(payload: dict[str, Any]) -> list[AtItem]:
    """Parse the /x/msgfeed/at response body into AtItem objects."""
    data = payload.get("data") or {}
    rows = data.get("items") or []
    items: list[AtItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        inner = row.get("item") if isinstance(row.get("item"), dict) else {}
        user = row.get("user") if isinstance(row.get("user"), dict) else {}
        merged = _nested(inner, row)

        bv = extract_bv(*(merged.get(f) for f in _BV_FIELDS))
        item_id = str(merged.get("id") or merged.get("item_id") or f"{merged.get('mid')}-{bv}")
        try:
            mid = int(user.get("mid") or merged.get("mid") or 0)
        except (TypeError, ValueError):
            mid = 0
        uname = str(
            user.get("nickname") or user.get("uname") or merged.get("uname") or "unknown"
        )
        title = str(merged.get("title") or "").strip()
        try:
            at_time = int(row.get("at_time") or merged.get("at_time") or 0)
        except (TypeError, ValueError):
            at_time = 0
        items.append(
            AtItem(
                item_id=item_id,
                bv=bv,
                mid=mid,
                uname=uname,
                title=title,
                at_time=at_time,
                raw_uri=str(merged.get("uri") or ""),
            )
        )
    return items


def fetch_at(auth: Auth, session: requests.Session, timeout: int = 15) -> list[AtItem]:
    auth.require_cookie()
    resp = session.get(
        AT_URL,
        params={"platform": "web", "build": 0, "mobi_app": "web"},
        headers=auth.headers("https://message.bilibili.com/"),
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise ApiError(f"拉取 @ 通知失败：HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ApiError("拉取 @ 通知失败：响应不是 JSON") from exc
    code = payload.get("code")
    if code == -101:
        raise ApiError("Cookie 已失效（code=-101），请重新获取 SESSDATA", code=-101,
                       hint="重新登录 B 站并更新 .env 里的 SESSDATA / BILI_JCT / DEDEUSERID。")
    if code != 0:
        raise ApiError(f"拉取 @ 通知失败：code={code} message={payload.get('message')}", code=code)
    return parse_at_items(payload)
