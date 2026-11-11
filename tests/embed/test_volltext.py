from app.embed.volltext import volltext_suche
from tests.embed.test_index import chunks_anlegen


def test_volltext_stemming(session):
    chunks_anlegen(session, ["Die Rechnung liegt vor.", "Ganz anderes Thema."])
    treffer = volltext_suche(session, "Rechnungen")
    assert len(treffer) == 1
    assert "<b>Rechnung</b>" in treffer[0].snippet
    assert treffer[0].vektor_rang is None and treffer[0].rerank_rang is None
    assert treffer[0].dateiname == "s1.txt"


def test_volltext_nur_aktive(session):
    chunks_anlegen(session, ["Die Rechnung liegt vor."], aktiv=False)
    assert volltext_suche(session, "Rechnung") == []


def test_volltext_leere_anfrage(session):
    assert volltext_suche(session, "  ") == []
