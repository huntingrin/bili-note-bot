from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bili import ego
from util import BiliNoteError


class ParseOutputTests(unittest.TestCase):
    def test_reads_last_json_line(self) -> None:
        out = 'log line\n{"ok": true, "count": 2}\n'
        self.assertEqual(ego.parse_output(out)["count"], 2)

    def test_ignores_non_json_noise(self) -> None:
        out = '[p1 "消息中心"]\nnoise\n{"items": []}\n'
        self.assertEqual(ego.parse_output(out)["items"], [])

    def test_falls_back_to_stderr(self) -> None:
        # ego writes console.log output to its stderr stream in practice.
        self.assertEqual(ego.parse_output("", '{"ok": true}')["ok"], True)

    def test_raises_without_json(self) -> None:
        with self.assertRaises(BiliNoteError):
            ego.parse_output("totally broken", "still broken")


class ScriptTests(unittest.TestCase):
    def test_run_script_executes_ego_with_stdin(self) -> None:
        proc = mock.Mock(returncode=0, stdout='{"ok": 1}', stderr="")
        with mock.patch.object(ego.subprocess, "run", return_value=proc) as run:
            result = ego.run_script("console.log(1)", settings=None)
        self.assertEqual(result["ok"], 1)
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[1], "nodejs")
        self.assertTrue(cmd[0].endswith("ego-browser"))
        self.assertEqual(run.call_args.kwargs["input"], "console.log(1)")
        self.assertTrue(run.call_args.kwargs["text"])

    def test_nonzero_exit_surfaces_hint(self) -> None:
        proc = mock.Mock(returncode=1, stdout="", stderr="boom: not logged in")
        with mock.patch.object(ego.subprocess, "run", return_value=proc):
            with self.assertRaises(BiliNoteError) as ctx:
                ego.run_script("x")
        self.assertIn("boom", ctx.exception.hint)

    def test_send_dm_requires_existing_file(self) -> None:
        with self.assertRaises(BiliNoteError):
            ego.send_dm(123, Path("/nonexistent/card.png"))

    def test_send_dm_requires_mid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "c.png"
            img.write_bytes(b"png")
            with self.assertRaises(BiliNoteError):
                ego.send_dm(0, img)

    def test_send_dm_embeds_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "c.png"
            img.write_bytes(b"png")
            captured = {}

            def fake_run(cmd, input=None, text=None, capture_output=None, timeout=None):
                captured["js"] = input
                return mock.Mock(returncode=0, stdout='{"ok": true, "before": 0, "after": 1}',
                                 stderr="")

            with mock.patch.object(ego.subprocess, "run", side_effect=fake_run):
                ego.send_dm(42, img)
            self.assertIn(str(img.resolve()), captured["js"])
            self.assertIn("#/whisper/mid42", captured["js"])
            self.assertIn("sic-BDC-image_line", captured["js"])
            self.assertIn("message.bilibili.com", captured["js"])
            # The send path must be the image tool + file chooser, never typing.
            self.assertNotIn("page.fill(", captured["js"])
            self.assertNotIn("page.press(", captured["js"])

    def test_send_failure_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "c.png"
            img.write_bytes(b"png")
            proc = mock.Mock(returncode=0,
                             stdout=json.dumps({"ok": False, "tip": "对方拒收"}),
                             stderr="")
            with mock.patch.object(ego.subprocess, "run", return_value=proc):
                with self.assertRaises(BiliNoteError) as ctx:
                    ego.send_dm(42, img)
            self.assertIn("对方拒收", ctx.exception.hint)


class FetchAtTests(unittest.TestCase):
    def test_rows_are_returned(self) -> None:
        proc = mock.Mock(returncode=0, stderr=json.dumps(
            {"ok": True, "count": 1,
             "items": [{"mid": 7, "uname": "u", "bv": "BV1xx411c7mD",
                        "title": "t", "time": "今天 12:00"}]}), stdout="")
        with mock.patch.object(ego.subprocess, "run", return_value=proc) as run:
            rows = ego.fetch_at(limit=5)
        self.assertEqual(rows[0]["mid"], 7)
        self.assertIn("limit: 5", run.call_args.kwargs["input"])

    def test_not_logged_in_raises_with_hint(self) -> None:
        proc = mock.Mock(returncode=0, stderr='{"error": "not_logged_in"}', stdout="")
        with mock.patch.object(ego.subprocess, "run", return_value=proc):
            with self.assertRaises(BiliNoteError) as ctx:
                ego.fetch_at()
        self.assertIn("登录", ctx.exception.hint)

    def test_browser_check_reads_login_state(self) -> None:
        proc = mock.Mock(returncode=0, stdout=json.dumps(
            {"loggedIn": True, "uid": 1234567, "atCount": 0, "first": None}), stderr="")
        with mock.patch.object(ego.subprocess, "run", return_value=proc):
            result = ego.browser_check()
        self.assertTrue(result["loggedIn"])
        self.assertEqual(result["atCount"], 0)


class BinResolutionTests(unittest.TestCase):
    def test_settings_bin_wins(self) -> None:
        class S:
            ego_bin = "/custom/ego-browser"

        self.assertEqual(ego.ego_bin(S()), "/custom/ego-browser")


if __name__ == "__main__":
    unittest.main()
