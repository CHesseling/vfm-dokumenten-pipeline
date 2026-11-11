def text_lesen(inhalt: bytes) -> str:
    try:
        return inhalt.decode("utf-8")
    except UnicodeDecodeError:
        return inhalt.decode("cp1252", errors="replace")
