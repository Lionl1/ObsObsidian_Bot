from __future__ import annotations

import io
import unittest
import zipfile

from types import SimpleNamespace

from services import (
    build_language_instruction,
    detect_message_language,
    extract_attachment_text,
    extract_note_from_response,
    prepare_user_message,
)


class ExtractNoteFromResponseTests(unittest.TestCase):
    def test_extracts_full_note_with_nested_mermaid_block(self) -> None:
        response = """```markdown
---
tags: [python, bots]
source: unknown
date: 2026-04-22
---

# Complete Note
## Architecture
```mermaid
graph TD
    A[User] --> B[Bot]
```
## Links
- https://example.com
```"""

        note = extract_note_from_response(response)

        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(note.title, "Complete Note")
        self.assertIn("```mermaid", note.content)
        self.assertIn("## Links", note.content)
        self.assertTrue(note.content.rstrip().endswith("- https://example.com"))

    def test_extracts_note_after_intro_text(self) -> None:
        response = """Final note below.

```md
# Title
Note body.
```"""

        note = extract_note_from_response(response)

        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(note.title, "Title")
        self.assertIn("Note body.", note.content)


class ExtractAttachmentTextTests(unittest.TestCase):
    def test_extracts_csv_attachment_text(self) -> None:
        payload = "name,value\nfoo,1\nbar,2\n".encode("utf-8")

        result = extract_attachment_text("table.csv", payload, "text/csv")

        self.assertEqual(result, "name\tvalue\nfoo\t1\nbar\t2")

    def test_extracts_docx_attachment_text(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>First line</w:t></w:r></w:p>
    <w:p><w:r><w:t>Second line</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", xml)

        result = extract_attachment_text(
            "note.docx",
            buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        self.assertEqual(result, "First line\nSecond line")


class LanguagePromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_user_message_adds_russian_language_instruction(self) -> None:
        settings = SimpleNamespace(url_extract_limit=3)

        prompt, primary_url = await prepare_user_message("Сделай заметку по этому тексту", settings)

        self.assertIsNone(primary_url)
        self.assertIn("The detected message language is Russian.", prompt)
        self.assertIn("User message:\nСделай заметку по этому тексту", prompt)

    async def test_prepare_user_message_adds_english_language_instruction(self) -> None:
        settings = SimpleNamespace(url_extract_limit=3)

        prompt, primary_url = await prepare_user_message("Create a note from this message", settings)

        self.assertIsNone(primary_url)
        self.assertIn("The detected message language is English.", prompt)
        self.assertIn("User message:\nCreate a note from this message", prompt)


class DetectMessageLanguageTests(unittest.TestCase):
    def test_detects_russian_text(self) -> None:
        self.assertEqual(detect_message_language("Привет, сделай заметку"), "Russian")

    def test_detects_english_text(self) -> None:
        self.assertEqual(detect_message_language("Hello, create a note"), "English")

    def test_build_language_instruction_for_unknown_text(self) -> None:
        instruction = build_language_instruction("12345 --- 67890")

        self.assertIn("If the message language is unclear", instruction)


if __name__ == "__main__":
    unittest.main()
