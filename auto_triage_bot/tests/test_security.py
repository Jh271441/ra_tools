from __future__ import annotations

import hashlib
import hmac
import os
import tempfile
import unittest
from pathlib import Path

from auto_triage_bot.security import SecretError, read_secret_file, verify_webhook


class WebhookSecurityTest(unittest.TestCase):
    def test_hmac_body_and_timestamp_modes(self) -> None:
        secret = b"secret"
        body = b'{"event_id":"1"}'
        signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
        self.assertTrue(
            verify_webhook(
                body=body, secret=secret, mode="hmac", signature=signature
            )
        )
        timestamp = "1000"
        timestamp_signature = hmac.new(
            secret, timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        self.assertTrue(
            verify_webhook(
                body=body,
                secret=secret,
                mode="hmac",
                signature="sha256=" + timestamp_signature,
                timestamp=timestamp,
                now=1001,
            )
        )
        self.assertFalse(
            verify_webhook(
                body=body,
                secret=secret,
                mode="hmac",
                signature=timestamp_signature,
                timestamp=timestamp,
                now=2000,
            )
        )

    def test_token_and_secret_file_permissions(self) -> None:
        self.assertTrue(
            verify_webhook(
                body=b"x", secret=b"token", mode="token", signature="token"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            path.write_bytes(b"value")
            path.chmod(0o600)
            self.assertEqual(read_secret_file(path), b"value")
            path.chmod(0o644)
            with self.assertRaises(SecretError):
                read_secret_file(path)


if __name__ == "__main__":
    unittest.main()
