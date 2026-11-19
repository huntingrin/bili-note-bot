from __future__ import annotations

import unittest

from bili.at import extract_bv, parse_at_items


class ExtractBvTests(unittest.TestCase):
    def test_plain_bv(self) -> None:
        self.assertEqual(extract_bv("BV1xx411c7mD"), "BV1xx411c7mD")

    def test_from_scheme_uri(self) -> None:
        self.assertEqual(
            extract_bv("bilibili://video/BV1xx411c7mD?spm_id_from=333"), "BV1xx411c7mD"
        )

    def test_none(self) -> None:
        self.assertIsNone(extract_bv("", None, "cv12345"))


PAYLOAD = {
    "code": 0,
    "data": {
        "items": [
            {
                "item": {
                    "id": 1001,
                    "uri": "bilibili://video/BV1xx411c7mD",
                    "title": "被 @ 的视频",
                },
                "user": {"mid": 9527, "nickname": "小明"},
                "at_time": 1700000000,
            },
            {
                "item": {"id": 1002, "title": "纯文字动态"},
                "user": {"mid": 42, "nickname": "abc"},
                "at_time": 1700000100,
            },
        ]
    },
}


class ParseAtTests(unittest.TestCase):
    def test_parses_items(self) -> None:
        items = parse_at_items(PAYLOAD)
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.bv, "BV1xx411c7mD")
        self.assertEqual(first.mid, 9527)
        self.assertEqual(first.uname, "小明")
        self.assertEqual(first.item_id, "1001")
        self.assertEqual(first.at_time, 1700000000)

    def test_item_without_bv_is_kept_but_bv_none(self) -> None:
        items = parse_at_items(PAYLOAD)
        self.assertIsNone(items[1].bv)
        self.assertEqual(items[1].mid, 42)

    def test_empty_payload(self) -> None:
        self.assertEqual(parse_at_items({"code": 0, "data": {}}), [])


if __name__ == "__main__":
    unittest.main()
