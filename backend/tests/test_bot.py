from __future__ import annotations

import unittest
from types import SimpleNamespace

from bot import build_document_context


class FakeBot:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.downloaded = []

    async def download(self, file, destination) -> None:
        self.downloaded.append(file)
        destination.write(self.payload)


def make_message(payload: bytes, file_size: int | None = None) -> SimpleNamespace:
    document = SimpleNamespace(
        file_name="notes.txt",
        file_unique_id="abc",
        file_size=len(payload) if file_size is None else file_size,
        mime_type="text/plain",
    )
    return SimpleNamespace(document=document, bot=FakeBot(payload))


class BuildDocumentContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = SimpleNamespace(telegram_file_max_size=1024, attachment_text_limit=15000)

    async def test_downloads_document_through_message_bot(self) -> None:
        message = make_message(b"hello from a document")

        context = await build_document_context(message, self.settings)

        self.assertEqual(message.bot.downloaded, [message.document])
        self.assertIn("Filename: notes.txt", context)
        self.assertIn("hello from a document", context)

    async def test_skips_download_of_oversized_document(self) -> None:
        message = make_message(b"ignored", file_size=4096)

        context = await build_document_context(message, self.settings)

        self.assertEqual(message.bot.downloaded, [])
        self.assertIn("exceeds the limit of 1024 bytes", context)


if __name__ == "__main__":
    unittest.main()
