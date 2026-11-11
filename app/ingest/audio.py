from app.providers.transcribe import Transkribierer


def audio_transkribieren(inhalt: bytes, dateiname: str, t: Transkribierer) -> str:
    return t.transkribieren(inhalt, dateiname)
