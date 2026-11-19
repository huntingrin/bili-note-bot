"""Legacy API-delivery error handling must stay intact (DELIVERY=api fallback)."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from bili import send
from bili.send import (
    CODE_NEEDS_MANUAL,
    CODE_RATE_LIMITED,
    CODE_REFUSED,
    ERROR_HINTS,
    SendResult,
)


class ErrorHintTests(unittest.TestCase):
    def test_21047_means_manual_comment_reply(self) -> None:
        result = SendResult(False, CODE_NEEDS_MANUAL, "限制")
        self.assertTrue(result.needs_manual)
        self.assertIn("评论区", result.hint)

    def test_21046_is_rate_limit_only(self) -> None:
        result = SendResult(False, CODE_RATE_LIMITED, "频控")
        self.assertFalse(result.needs_manual)
        self.assertIn("稍后", result.hint)

    def test_25003_is_refusal(self) -> None:
        self.assertTrue(SendResult(False, CODE_REFUSED, "拒收").needs_manual)
        self.assertEqual(set(ERROR_HINTS), {21047, 21046, 25003})


class ImageContentTests(unittest.TestCase):
    def test_image_content_is_json_string(self) -> None:
        sent = {}

        def fake_post(url, data=None, headers=None, timeout=None):
            sent["data"] = data
            return mock.Mock(status_code=200, json=lambda: {"code": 0, "message": "ok"})

        auth = mock.Mock(uid=1, csrf="csrf-token", headers=lambda *a: {})
        auth.require_sender = lambda: None
        signer = mock.Mock()
        signer.sign = lambda params: {**params, "wts": 1, "w_rid": "x"}
        image = {"url": "https://i0.hdslb.com/a.png", "width": 1080, "height": 1440, "size": 10}

        with mock.patch.object(send.requests, "post", side_effect=fake_post):
            result = send.send_image(auth, signer, 42, image, "dev-uuid")

        self.assertTrue(result.ok)
        content = json.loads(sent["data"]["msg[content]"])
        self.assertEqual(content["url"], image["url"])
        self.assertEqual(content["original"], 1)
        self.assertEqual(content["width"], 1080)
        self.assertEqual(sent["data"]["msg[msg_type]"], 2)
        self.assertEqual(sent["data"]["w_receiver_id"], 42)


if __name__ == "__main__":
    unittest.main()
