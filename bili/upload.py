"""Upload a rendered card to the Bilibili image host (needed for image DMs)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from bili.auth import Auth
from util import ApiError

UPLOAD_URL = "https://api.bilibili.com/x/dynamic/feed/draw/upload_bfs"


def upload_image(auth: Auth, image_path: Path, timeout: int = 60) -> dict[str, Any]:
    """Upload PNG, return {url, width, height}. Url is normalised to https://."""
    auth.require_sender()
    image_path = Path(image_path)
    if not image_path.is_file():
        raise ApiError(f"待上传图片不存在：{image_path}")

    with image_path.open("rb") as fh:
        files = {"file_up": (image_path.name, fh, "image/png")}
        data = {"category": "daily", "csrf": auth.csrf}
        resp = requests.post(
            UPLOAD_URL,
            files=files,
            data=data,
            headers=auth.headers("https://t.bilibili.com/"),
            timeout=timeout,
        )
    if resp.status_code != 200:
        raise ApiError(f"图床上传失败：HTTP {resp.status_code}")
    payload = resp.json()
    if payload.get("code") != 0:
        raise ApiError(
            f"图床上传失败：code={payload.get('code')} message={payload.get('message')}",
            code=payload.get("code"),
        )
    info = payload.get("data") or {}
    url = str(info.get("image_url") or "")
    if url.startswith("//"):
        url = "https:" + url
    if not url:
        raise ApiError("图床上传失败：响应缺少 image_url", code=0)
    return {
        "url": url,
        "width": int(info.get("image_width") or 1080),
        "height": int(info.get("image_height") or 1440),
        "size": int(info.get("img_size") or image_path.stat().st_size),
    }
