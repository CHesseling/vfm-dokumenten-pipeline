from app.ingest.chunking import chunken


def test_chunken_ueberlappung():
    text = ("wort" * 1 + " ") * 800  # 4000 Zeichen
    chunks = chunken(text, 1500, 200)
    assert len(chunks) == 3
    assert abs(chunks[1][0] - (chunks[0][1] - 200)) <= 50
    for start, ende, t in chunks:
        assert t == text[start:ende]
    assert chunks[-1][1] == len(text)


def test_chunken_leer():
    assert chunken("", 1500, 200) == []
    assert chunken("  \n ", 1500, 200) == []


def test_chunken_kurz_ein_chunk():
    assert chunken("Hallo Welt.", 1500, 200) == [(0, 11, "Hallo Welt.")]


def test_chunken_bevorzugt_absatz():
    text = "a" * 10 + " " + "b" * 1000 + "\n\n" + "c " * 400
    chunks = chunken(text, 1500, 100)
    assert text[: chunks[0][1]].endswith("\n\n")
