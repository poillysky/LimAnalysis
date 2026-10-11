"""图片短时签名票据：供 <img src> 在无 Authorization 头时自证身份。"""

from __future__ import annotations

import unittest
from datetime import timedelta
from unittest import mock

from app.core import tokens


class MediaTicketTest(unittest.TestCase):
    def setUp(self) -> None:
        tokens.clear_secret_cache()
        self._secret_patch = mock.patch.object(
            tokens, "_secret", return_value=b"unit-test-secret-key"
        )
        self._secret_patch.start()

    def tearDown(self) -> None:
        self._secret_patch.stop()
        tokens.clear_secret_cache()

    def test_roundtrip(self) -> None:
        ticket = tokens.issue_media_ticket("mold", "M01/20261011/A/OK/a.jpg")
        source, rel = tokens.parse_media_ticket(ticket)
        self.assertEqual(source, "mold")
        self.assertEqual(rel, "M01/20261011/A/OK/a.jpg")

    def test_normalizes_backslash(self) -> None:
        ticket = tokens.issue_media_ticket("appearance", r"p\cam\x.jpg")
        source, rel = tokens.parse_media_ticket(ticket)
        self.assertEqual(source, "appearance")
        self.assertEqual(rel, "p/cam/x.jpg")

    def test_tampered_sig_rejected(self) -> None:
        ticket = tokens.issue_media_ticket("mold", "a.jpg")
        body, _sig = ticket.split(".", 1)
        with self.assertRaises(PermissionError):
            tokens.parse_media_ticket(f"{body}.AAAA")

    def test_wrong_kind_rejected(self) -> None:
        access, _ = tokens.issue_token("bob", "access", timedelta(hours=1))
        with self.assertRaises(PermissionError):
            tokens.parse_media_ticket(access)

    def test_expired_rejected(self) -> None:
        ticket = tokens.issue_media_ticket(
            "mold", "a.jpg", lifetime=timedelta(seconds=-2)
        )
        with self.assertRaises(PermissionError) as ctx:
            tokens.parse_media_ticket(ticket)
        self.assertIn("过期", str(ctx.exception))

    def test_empty_ticket_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            tokens.parse_media_ticket("")

    def test_empty_rel_rejected_on_issue(self) -> None:
        with self.assertRaises(ValueError):
            tokens.issue_media_ticket("mold", "  ")


class ClientImageUrlTest(unittest.TestCase):
    def test_view_url_includes_ticket(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from app.core.inspection import _to_client_image

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root / "M01" / "x.jpg"
            photo.parent.mkdir(parents=True)
            photo.write_bytes(b"x")
            with mock.patch(
                "app.core.tokens.issue_media_ticket", return_value="TICKET.SIG"
            ):
                item = _to_client_image(
                    {
                        "path": str(photo),
                        "machine": "M01",
                        "cavity": "A",
                        "filename": "x.jpg",
                        "date_str": "20261011",
                    },
                    root,
                    "mold",
                )
        self.assertIsNotNone(item)
        assert item is not None
        self.assertIn("ticket=TICKET.SIG", item["view_url"])
        self.assertIn("/inspection/image?", item["view_url"])


if __name__ == "__main__":
    unittest.main()
