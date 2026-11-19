from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config import Settings
from pipeline import summarize as sm

PAYLOAD = {
    "title": "测试视频",
    "up_name": "UP",
    "duration": 600,
    "chapters": [
        {"heading": "开头", "points": ["要点一", "要点二"], "timestamp": 0},
        {"heading": "中段", "points": ["要点三", "要点四"], "timestamp": 200},
        {"heading": "结尾", "points": ["要点五", "要点六"], "timestamp": 500},
    ],
    "frames": [{"ts": 25, "reason": "第一帧"}],
}


class FakeResponse:
    def __init__(self, status_code: int, body: dict, text: str = ""):
        self.status_code = status_code
        self._body = body
        self.text = text or json.dumps(body)

    def json(self) -> dict:
        return self._body


def ok_response(payload: dict) -> FakeResponse:
    return FakeResponse(200, {"choices": [{"message": {"content": json.dumps(payload)}}]})


class NormalizeTests(unittest.TestCase):
    def test_pads_chapters_and_keeps_sampled_frames(self) -> None:
        sampled = list(range(0, 600, 50))
        out = sm.normalize({"chapters": [], "frames": []}, 600, sampled_ts=sampled)
        self.assertEqual([f["ts"] for f in out["frames"]], sampled)
        self.assertGreaterEqual(len(out["chapters"]), 3)

    def test_clamps_and_trims(self) -> None:
        raw = {
            "chapters": [
                {"heading": f"h{i}", "points": ["a", "b", "c", "d"], "timestamp": 9999}
                for i in range(8)
            ],
            "frames": [{"ts": 10000, "reason": "x"} for _ in range(20)],
        }
        out = sm.normalize(raw, duration=300, sampled_ts=[10, 60, 120])
        self.assertLessEqual(len(out["chapters"]), 5)
        self.assertTrue(all(len(ch["points"]) <= 3 for ch in out["chapters"]))
        self.assertEqual([f["ts"] for f in out["frames"]], [10, 60, 120])
        self.assertTrue(all(ch["timestamp"] <= 299 for ch in out["chapters"]))

    def test_mmss_timestamps_are_parsed(self) -> None:
        out = sm.normalize(
            {"chapters": [{"heading": "h", "points": ["p"], "timestamp": "02:05"}]},
            duration=600, sampled_ts=[100],
        )
        self.assertEqual(out["chapters"][0]["timestamp"], 125)

    def test_model_reason_snaps_to_nearest_sampled_ts(self) -> None:
        out = sm.normalize({"frames": [{"ts": 58, "reason": "近 60"}]}, 600,
                           sampled_ts=[10, 60, 120])
        reasons = {f["ts"]: f["reason"] for f in out["frames"]}
        self.assertEqual(reasons[60], "近 60")
        self.assertEqual(reasons[10], "")

    def test_title_fallback(self) -> None:
        out = sm.normalize({}, 100, sampled_ts=[10], fallback_title="原标题", fallback_up="UP主")
        self.assertEqual(out["title"], "原标题")
        self.assertEqual(out["up_name"], "UP主")


class VisionFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.frame = Path(self.tmp.name) / "f.png"
        from PIL import Image

        Image.new("RGB", (320, 180), (30, 40, 50)).save(self.frame)
        self.settings = Settings(llm_api_key="test-key", llm_model="deepseek-flash")
        self.frames = [{"path": self.frame, "ts": 25, "label": "00:25"}]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_uses_image_url_payload(self) -> None:
        with mock.patch.object(sm.requests, "post", return_value=ok_response(PAYLOAD)) as post:
            sm.summarize(self.settings, self.frames, 600, "t", "u")
        payload = post.call_args.kwargs["json"]
        content = payload["messages"][1]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(payload["model"], "deepseek-flash")

    def test_vision_rejection_retries_text_only(self) -> None:
        bad = FakeResponse(400, {"error": {"message": "this model does not support image input"}})
        with mock.patch.object(sm.requests, "post", side_effect=[bad, ok_response(PAYLOAD)]) as post:
            with self.assertLogs("bili_note", level="WARNING") as logs:
                out = sm.summarize(
                    self.settings, self.frames, 600, "t", "u",
                    logger=logging.getLogger("bili_note"),
                )
        self.assertEqual(post.call_count, 2)
        second = post.call_args_list[1].kwargs["json"]["messages"][1]["content"]
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["type"], "text")
        self.assertIn("vision_fallback", "\n".join(logs.output))
        self.assertEqual(out["title"], PAYLOAD["title"])

    def test_other_4xx_does_not_retry(self) -> None:
        bad = FakeResponse(401, {"error": {"message": "invalid api key"}})
        with mock.patch.object(sm.requests, "post", side_effect=[bad]) as post:
            with self.assertRaises(sm.SummarizeError):
                sm.summarize(self.settings, self.frames, 600, "t", "u")
        self.assertEqual(post.call_count, 1)

    def test_missing_api_key(self) -> None:
        with self.assertRaises(sm.SummarizeError):
            sm.summarize(Settings(llm_api_key=""), self.frames, 600, "t", "u")


class JsonExtractionTests(unittest.TestCase):
    def test_fenced_json(self) -> None:
        text = '```json\n{"a": 1}\n```'
        self.assertEqual(sm._extract_json(text), {"a": 1})

    def test_json_with_prose(self) -> None:
        self.assertEqual(sm._extract_json('好的：{"a": 2} 完成'), {"a": 2})

    def test_invalid_raises(self) -> None:
        with self.assertRaises(sm.SummarizeError):
            sm._extract_json("not json at all")


if __name__ == "__main__":
    unittest.main()
