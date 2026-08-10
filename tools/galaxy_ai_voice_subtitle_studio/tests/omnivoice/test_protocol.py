from __future__ import annotations

import unittest

from app.omnivoice.protocol import ProtocolError, decode_message, encode_message


class OmniVoiceProtocolTests(unittest.TestCase):
    def test_message_round_trip_preserves_vietnamese_text(self) -> None:
        message = {
            "protocol_version": 1,
            "request_id": "job-1",
            "type": "generate",
            "payload": {"text": "Xin chào thế giới"},
        }

        self.assertEqual(decode_message(encode_message(message)), message)

    def test_non_object_message_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            decode_message("[]")

    def test_message_without_type_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            decode_message('{"request_id":"job-1"}')


if __name__ == "__main__":
    unittest.main()
