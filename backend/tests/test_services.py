from __future__ import annotations

import io
import unittest
import zipfile

from services import extract_attachment_text, extract_note_from_response


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


if __name__ == "__main__":
    unittest.main()
