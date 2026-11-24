"""Private pagination cursor contracts; no network or database."""
import base64
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from rag_tech_retriever.platform.community_pagination import (
    decode_cursor,
    encode_cursor,
    page_result,
)


class PaginationContract(unittest.TestCase):
    def setUp(self):
        self.row = {"id": uuid4(), "created_at": datetime.now(timezone.utc), "title": "private"}

    def test_roundtrip_preserves_key_and_endpoint(self):
        token = encode_cursor("mine", self.row)
        self.assertLess(len(token), 256)
        self.assertEqual(decode_cursor(token, "mine"), (self.row["created_at"], str(self.row["id"])))
        with self.assertRaises(ValueError):
            decode_cursor(token, "reviews")
        self.assertIsNone(decode_cursor(None, "mine"))

    def test_invalid_shapes_versions_and_dates(self):
        payloads = [None, {}, [], [1, "mine", "x", str(uuid4())],
                    [True, "mine", "2026-01-01T00:00:00+00:00", str(uuid4())],
                    [1, "mine", "2026-01-01T00:00:00", str(uuid4())],
                    [1, "mine", "2026-01-01T00:00:00+00:00", "not-uuid"]]
        for payload in payloads:
            token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
            with self.assertRaises(ValueError, msg=repr(payload)):
                decode_cursor(token, "mine")
        for token in ("", "!invalid", "a"*257):
            with self.assertRaises(ValueError):
                decode_cursor(token, "mine")

    def test_lookahead_and_last_boundary(self):
        self.assertEqual(page_result([], 30, "mine"), {"items": [], "next": None})
        self.assertIsNone(page_result([self.row], 1, "mine")["next"])
        page = page_result([self.row, {**self.row, "id": uuid4()}], 1, "mine")
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(decode_cursor(page["next"], "mine")[1], str(self.row["id"]))


if __name__ == "__main__":
    unittest.main()
