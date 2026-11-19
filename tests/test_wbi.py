from __future__ import annotations

import hashlib
import unittest
import urllib.parse

from bili.wbi import MIXIN_KEY_ENC_TAB, get_mixin_key, sign_params


class MixinKeyTests(unittest.TestCase):
    def test_table_is_a_permutation_of_0_63(self) -> None:
        self.assertEqual(len(MIXIN_KEY_ENC_TAB), 64)
        self.assertEqual(sorted(MIXIN_KEY_ENC_TAB), list(range(64)))

    def test_mixin_key_is_32_chars(self) -> None:
        orig = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        key = get_mixin_key(orig)
        self.assertEqual(len(key), 32)
        self.assertEqual(key, "".join(orig[i] for i in MIXIN_KEY_ENC_TAB)[:32])

    def test_sign_params_deterministic(self) -> None:
        params = {"w_sender_uid": 1, "w_receiver_id": 2, "w_dev_id": "abc"}
        a = sign_params(params, "imgkey", "subkey", wts=1700000000)
        b = sign_params(params, "imgkey", "subkey", wts=1700000000)
        self.assertEqual(a, b)
        self.assertEqual(a["wts"], 1700000000)
        self.assertEqual(len(a["w_rid"]), 32)

    def test_signature_matches_manual_md5(self) -> None:
        params = {"w_sender_uid": 1, "wts": 1700000000}
        signed = sign_params({"w_sender_uid": 1}, "imgkey", "subkey", wts=1700000000)
        query = urllib.parse.urlencode({"w_sender_uid": "1", "wts": "1700000000"})
        expected = hashlib.md5((query + get_mixin_key("imgkeysubkey")).encode()).hexdigest()
        self.assertEqual(signed["w_rid"], expected)
        self.assertEqual(params["wts"], signed["wts"])

    def test_input_not_mutated(self) -> None:
        params = {"w_sender_uid": 1}
        sign_params(params, "a", "b", wts=1)
        self.assertEqual(params, {"w_sender_uid": 1})


if __name__ == "__main__":
    unittest.main()
