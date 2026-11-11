from app.config import Settings
from app.enums import DokumentTyp, ExtraktionsMethode
from app.models import Dokument, TextExtraktion
from app.statistik import STUFEN, zaehlerstaende


def test_zaehlerstaende(session):
    d = Dokument(sha256="a", dateiname="a.pdf", typ=DokumentTyp.PDF, mime="application/pdf", groesse=1)
    session.add(d)
    session.commit()
    session.add(TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.SCHNELL, text="x", ist_aktiv=True))
    session.commit()
    s = Settings(database_url="x", chat_base_url="http://c/v1", chat_model="m",
                 embed_base_url="http://e/v1", embed_model="e", _env_file=None)
    z = zaehlerstaende(session, s)
    assert set(z) == set(STUFEN)
    assert z["gesamt"][DokumentTyp.PDF] == 1 and z["mit_text"][DokumentTyp.PDF] == 1
    assert z["mit_entitaeten"].get(DokumentTyp.PDF, 0) == 0
