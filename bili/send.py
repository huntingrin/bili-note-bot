"""Send a private message (text / image) via the web IM endpoint."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import requests

from bili.auth import Auth
from bili.wbi import WbiSigner
from util import ApiError

SEND_URL = "https://api.vc.bilibili.com/web_im/v1/web_im/send_msg"

# Documented failure modes that need a human to step in.
CODE_NEEDS_MANUAL = 21047   # 对方未回复 / 未关注：最多只能发 1 条
CODE_RATE_LIMITED = 21046   # 频控
CODE_REFUSED = 25003        # 对方拒收

ERROR_HINTS = {
    CODE_NEEDS_MANUAL: "对方未回复或未关注你，B 站限制只能发送 1 条。需人工在评论区回复他。",
    CODE_RATE_LIMITED: "触发 B 站私信频控，稍后再试（本次已记录为 failed）。",
    CODE_REFUSED: "对方设置了不接收陌生人私信（25003），需人工在评论区回复。",
}


@dataclass
class SendResult:
    ok: bool
    code: int
    message: str
    needs_manual: bool = False

    def __post_init__(self) -> None:
        # 21047 (未回复/未关注) and 25003 (拒收) always need a human.
        if self.code in (CODE_NEEDS_MANUAL, CODE_REFUSED):
            self.needs_manual = True

    @property
    def hint(self) -> str:
        return ERROR_HINTS.get(self.code, "")


def get_dev_id(path: Path) -> str:
    """Stable per-installation device id (uuid4), created on first use."""
    path = Path(path)
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    dev_id = str(uuid.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dev_id + "\n", encoding="utf-8")
    return dev_id


def _post(auth: Auth, signer: WbiSigner, receiver_id: int, msg_type: int,
          content: str, dev_id: str, timeout: int = 20) -> SendResult:
    w_params = {
        "w_sender_uid": auth.uid,
        "w_receiver_id": receiver_id,
        "w_dev_id": dev_id,
    }
    signed = signer.sign(w_params)
    ts = int(time.time() * 1000)
    body = {
        "msg[sender_uid]": auth.uid,
        "msg[receiver_id]": receiver_id,
        "msg[receiver_type]": 1,
        "msg[msg_type]": msg_type,
        "msg[content]": content,
        "msg[dev_id]": dev_id,
        "msg[timestamp]": ts,
        "csrf": auth.csrf,
        "csrf_token": auth.csrf,
        **signed,
    }
    resp = requests.post(
        SEND_URL,
        data=body,
        headers=auth.headers("https://message.bilibili.com/"),
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise ApiError(f"发送私信失败：HTTP {resp.status_code}")
    payload = resp.json()
    code = int(payload.get("code") or 0)
    if code == 0:
        return SendResult(True, 0, "ok")
    message = str(payload.get("message") or payload.get("msg") or "")
    return SendResult(
        ok=False,
        code=code,
        message=message,
        needs_manual=code in (CODE_NEEDS_MANUAL, CODE_REFUSED),
    )


def send_text(auth: Auth, signer: WbiSigner, receiver_id: int, text: str,
              dev_id: str) -> SendResult:
    auth.require_sender()
    return _post(auth, signer, receiver_id, 1, text, dev_id)


def send_image(auth: Auth, signer: WbiSigner, receiver_id: int, image: dict,
               dev_id: str) -> SendResult:
    """`image` is the dict returned by bili.upload.upload_image."""
    auth.require_sender()
    content = json.dumps(
        {
            "url": image["url"],
            "height": int(image.get("height") or 1440),
            "width": int(image.get("width") or 1080),
            "original": 1,
            "size": int(image.get("size") or 0),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return _post(auth, signer, receiver_id, 2, content, dev_id)
