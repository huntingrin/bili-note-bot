from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from storage import Store


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self._tmp.name) / "test.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_dedupe_by_bv(self) -> None:
        self.store.upsert_video("BV1a", title="t1")
        self.store.upsert_video("BV1a", title="t2")
        row = self.store.get_video("BV1a")
        assert row is not None
        self.assertEqual(row["title"], "t2")

    def test_has_card_requires_existing_file(self) -> None:
        missing = Path(self._tmp.name) / "nope.png"
        self.store.upsert_video("BV1b", card_path=str(missing), status="carded")
        self.assertFalse(self.store.has_card("BV1b"))

        real = Path(self._tmp.name) / "card.png"
        real.write_bytes(b"png")
        self.store.upsert_video("BV1b", card_path=str(real))
        self.assertTrue(self.store.has_card("BV1b"))

    def test_at_item_seen(self) -> None:
        self.assertFalse(self.store.seen_at_item("x1"))
        self.store.mark_at_item("x1", "BV1a", 1)
        self.store.mark_at_item("x1", "BV1a", 1)
        self.assertTrue(self.store.seen_at_item("x1"))

    def test_quota(self) -> None:
        self.assertEqual(self.store.sent_today(), 0)
        self.assertEqual(self.store.incr_sent_today(), 1)
        self.assertEqual(self.store.incr_sent_today(), 2)
        self.assertEqual(self.store.sent_today(), 2)

    def test_failure_log(self) -> None:
        self.store.add_failure("BV1a", 5, "send_msg", "21047: 限制", 21047)
        rows = self.store.recent_failures()
        self.assertEqual(rows[0]["code"], 21047)
        self.assertEqual(rows[0]["stage"], "send_msg")


if __name__ == "__main__":
    unittest.main()
