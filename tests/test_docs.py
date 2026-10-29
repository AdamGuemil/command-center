"""Guide : seuls les documents listes sont servis, et un document absent disparait."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

CC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CC))

from core import docs  # noqa: E402


class DocsTests(unittest.TestCase):
    def test_only_listed_documents_are_served(self):
        with self.assertRaises(ValueError):
            docs.read("../.env")
        with self.assertRaises(ValueError):
            docs.read("README.md")

    def test_pipelines_is_listed_with_content(self):
        data = {d["id"]: d for d in docs.all_text()["docs"]}
        self.assertIn("pipelines", data)
        self.assertIn("# Pipelines du Command Center", data["pipelines"]["markdown"])
        self.assertNotIn("\r", data["pipelines"]["markdown"])

    def test_missing_document_is_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = [("x", "X", "", Path(tmp) / "absent.md"), ("y", "Y", "", None)]
            with patch.object(docs, "DOCS", fake):
                self.assertEqual(docs.listing()["docs"], [])
                with self.assertRaises(ValueError):
                    docs.read("x")


if __name__ == "__main__":
    unittest.main()
