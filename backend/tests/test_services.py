from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from services import (
    build_language_instruction,
    build_system_prompt,
    detect_message_language,
    extract_attachment_text,
    extract_note_from_response,
    make_safe_filename,
    prepare_user_message,
    scan_obsidian_vault,
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


class MakeSafeFilenameTests(unittest.TestCase):
    def test_keeps_spaces_and_removes_unsafe_chars(self) -> None:
        filename = make_safe_filename("My Super: Note? Title!")
        self.assertEqual(filename, "My Super Note Title!.md")

    def test_truncates_long_filename(self) -> None:
        long_title = "a" * 150
        filename = make_safe_filename(long_title)
        self.assertEqual(len(filename), 103)  # 100 characters + .md
        self.assertEqual(filename, "a" * 100 + ".md")


class VaultScanningCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_cache_for_unchanged_files(self) -> None:
        from services import _VAULT_CACHE
        _VAULT_CACHE.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir)
            file_path = vault_path / "test_note.md"
            file_path.write_text("---\ntags: [tag1]\n---\n# Title\ncontent", encoding="utf-8")

            # First scan - should read from disk
            index1 = await scan_obsidian_vault(vault_path)
            self.assertEqual(len(index1.notes), 1)
            self.assertEqual(index1.notes[0].link_name, "test_note")

            # Mock read_text to ensure it's not called again
            with patch("pathlib.Path.read_text", side_effect=RuntimeError("Should not read file")):
                index2 = await scan_obsidian_vault(vault_path)
                self.assertEqual(len(index2.notes), 1)
                self.assertEqual(index2.notes[0].link_name, "test_note")


class SystemPromptOverrideTests(unittest.IsolatedAsyncioTestCase):
    async def test_loads_prompt_from_vault_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir)
            prompt_file = vault_path / "prompt.md"
            prompt_file.write_text("Custom prompt template {today}", encoding="utf-8")

            settings = SimpleNamespace(
                vault_path=vault_path,
                system_prompt_template="Default prompt {today}",
                obsidian_prompt_notes_limit=10,
            )

            prompt = build_system_prompt(settings, None)
            self.assertIn("Custom prompt template", prompt)


class ExtractPdfTextTests(unittest.TestCase):
    @patch("pypdf.PdfReader")
    def test_extracts_pdf_attachment_text(self, mock_pdf_reader) -> None:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "PDF page text content"

        mock_reader_instance = MagicMock()
        mock_reader_instance.pages = [mock_page]
        mock_pdf_reader.return_value = mock_reader_instance

        result = extract_attachment_text("doc.pdf", b"fake pdf data", "application/pdf")
        self.assertEqual(result, "PDF page text content")


if __name__ == "__main__":
    unittest.main()
