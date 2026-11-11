"""Text in überlappende Chunks teilen (Absatz-, Satz-, Wortgrenze)."""

_TRENNER = ("\n\n", "\n", ". ", "! ", "? ", " ")


def _ende_finden(text: str, start: int, grenze: int) -> int:
    """Bestes Chunk-Ende in (start+Hälfte, grenze]; sonst hartes Ende."""
    untergrenze = start + (grenze - start) // 2
    for trenner in _TRENNER:
        pos = text.rfind(trenner, untergrenze, grenze)
        if pos != -1:
            return pos + len(trenner)
    return grenze


def chunken(text: str, zeichen: int, ueberlappung: int) -> list[tuple[int, int, str]]:
    """Liefert (start, ende, text) mit text == text_gesamt[start:ende]."""
    if not text.strip():
        return []
    n = len(text)
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < n:
        ende = n if start + zeichen >= n else _ende_finden(text, start, start + zeichen)
        if text[start:ende].strip():
            chunks.append((start, ende, text[start:ende]))
        if ende >= n:
            break
        naechster = max(ende - ueberlappung, start + 1)
        # an Wortgrenze ausrichten (nicht mitten im Wort beginnen)
        while naechster < ende and not text[naechster - 1].isspace():
            naechster += 1
        start = naechster
    return chunks
