"""Optional genuine model/PDF smoke test, separate from the user's index.

Run with the installed Python environment. Set HF_HOME to the model cache.
Weights are downloaded if missing unless HF_HUB_OFFLINE=1 is set.
"""
import argparse
import tempfile
from pathlib import Path

import pymupdf

from embedding_models import MODEL_BY_ID
from engine import Engine


def smoke(name):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        path = root / "test.pdf"
        pdf = pymupdf.open()
        for text in (
            "Overfitting reduces generalization performance on unseen test data. "
            "Training loss is low while validation error increases.",
            "Crop yields respond to soil temperature and seasonal rainfall. "
            "Farmers monitor soil moisture to optimize irrigation.",
        ):
            page = pdf.new_page()
            page.insert_textbox((50, 50, 500, 250), text, fontsize=11)
        pdf.save(path)
        pdf.close()
        engine = Engine(root / "test.sqlite")
        # This database is new and has no vectors to migrate.
        with engine._connect() as db:
            db.execute("UPDATE index_metadata SET value=? WHERE key='embedding_model'", (name,))
        engine.model_name = name
        for library in (7, 8):
            indexed = engine.index_pdf({"library_id":library, "item_key":"PAPER", "attachment_key":"PDF",
                                       "pdf_path":str(path), "title":"Generalization study", "language":"en"})
            assert indexed["chunks"] == 2, indexed
        hits = engine.search({"library_id":7, "query":"overfitting generalization performance"})
        assert hits and all(hit["library_id"] == 7 for hit in hits), hits
        assert "Overfitting" in hits[0]["quote"], hits
        assert hits[0]["position"].get("rects"), hits[0]
        assert engine.search({"library_id":99, "query":"overfitting generalization performance"}) == []
        assert engine.search({"library_id":7, "query":"medieval cathedral architecture"}) == []
        assert Engine(engine.db_path).model_name == name
        print(f"{name}: PDF/index/search/highlight/library scope/no unrelated quotes/restart OK", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+", choices=sorted(MODEL_BY_ID))
    for name in parser.parse_args().models:
        smoke(name)
