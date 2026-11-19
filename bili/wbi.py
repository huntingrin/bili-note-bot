"""Bilibili wbi request signing."""

from __future__ import annotations

import hashlib
import time
import urllib.parse
from typing import Any

import requests

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

# Standard mixin key shuffle table (shared by all web endpoints).
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]


def get_mixin_key(orig: str) -> str:
    return "".join(orig[i] for i in MIXIN_KEY_ENC_TAB if i < len(orig))[:32]


def sign_params(params: dict[str, Any], img_key: str, sub_key: str,
                wts: int | None = None) -> dict[str, Any]:
    """Return params with `wts` and `w_rid` added (does not mutate the input)."""
    mixin_key = get_mixin_key(img_key + sub_key)
    signed = {k: v for k, v in params.items() if v is not None}
    signed["wts"] = int(wts if wts is not None else time.time())
    # Bilibili drops the characters !'()* from values before hashing.
    cleaned = {
        k: "".join(ch for ch in str(v) if ch not in "!'()*")
        for k, v in sorted(signed.items())
    }
    query = urllib.parse.urlencode(cleaned)
    signed["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return signed


class WbiSigner:
    """Fetches and caches the per-day img/sub keys from /x/web-interface/nav."""

    def __init__(self, session: requests.Session, ttl: int = 3600):
        self.session = session
        self.ttl = ttl
        self._keys: tuple[str, str] | None = None
        self._fetched_at = 0.0

    def _key_from_url(self, url: str) -> str:
        return urllib.parse.urlparse(url).path.rsplit("/", 1)[-1].split(".")[0]

    def keys(self, force: bool = False) -> tuple[str, str]:
        now = time.time()
        if not force and self._keys and now - self._fetched_at < self.ttl:
            return self._keys
        resp = self.session.get(NAV_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        wbi_img = data.get("wbi_img") or {}
        img_url = wbi_img.get("img_url", "")
        sub_url = wbi_img.get("sub_url", "")
        if not img_url or not sub_url:
            raise RuntimeError("无法获取 wbi 签名密钥（/x/web-interface/nav 未返回 wbi_img）")
        self._keys = (self._key_from_url(img_url), self._key_from_url(sub_url))
        self._fetched_at = now
        return self._keys

    def sign(self, params: dict[str, Any]) -> dict[str, Any]:
        img_key, sub_key = self.keys()
        return sign_params(params, img_key, sub_key)
