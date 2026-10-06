"""Optional full model smoke test; requires installed dependencies and weights."""
import tempfile
from pathlib import Path

import pymupdf

from engine import Engine

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    path = root / "probe.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((50, 50), "Der Klimawandel beeinflusst die Landwirtschaft erheblich.")
    pdf.save(path)
    pdf.close()
    engine = Engine(root / "probe.sqlite")
    item = {"library_id": 1, "item_key": "ABC", "attachment_key": "DEF",
            "pdf_path": str(path), "title": "Test", "creators": "", "year": "2026",
            "zotero_uri": "zotero://select/library/items/ABC"}
    indexed = engine.index_pdf(item)
    hits = engine.search({"library_id": 1, "query": "Klima Landwirtschaft"})
    other = engine.search({"library_id": 2, "query": "Klima Landwirtschaft"})
    assert indexed["chunks"] == 1
    assert hits and "Klimawandel" in hits[0]["quote"]
    assert other == []
    print("PDF > Chunk > Embedding > SQLite > BERTScore > Zitat: OK")
