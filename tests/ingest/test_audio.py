from app.ingest.audio import audio_transkribieren


class FakeTranskribierer:
    def __init__(self):
        self.aufrufe = []

    def transkribieren(self, inhalt: bytes, dateiname: str) -> str:
        self.aufrufe.append((inhalt, dateiname))
        return "Hallo Welt"


def test_audio_delegiert():
    t = FakeTranskribierer()
    assert audio_transkribieren(b"abc", "memo.m4a", t) == "Hallo Welt"
    assert t.aufrufe == [(b"abc", "memo.m4a")]
