from app.ingest.text import text_lesen


def test_text_utf8():
    assert text_lesen("Grüße".encode("utf-8")) == "Grüße"


def test_text_cp1252():
    assert text_lesen("Grüße".encode("cp1252")) == "Grüße"
