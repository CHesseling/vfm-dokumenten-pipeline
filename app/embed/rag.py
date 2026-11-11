"""RAG: Antwort aus den gefundenen Textabschnitten, mit Quellenverweisen [1], [2]."""

from dataclasses import dataclass

from app.embed.treffer import SuchTreffer
from app.providers.llm_client import LLMClient

KEINE_ANTWORT = "Dazu finde ich in den Dokumenten nichts."

SYSTEM_PROMPT = (
    "Du beantwortest Fragen ausschließlich anhand der unten angegebenen Quellen. "
    "Zitiere die Quellen im Text mit ihrer Nummer in eckigen Klammern, z. B. [1] oder [2]. "
    "Erfinde nichts und nutze kein Wissen von außerhalb der Quellen. "
    f"Wenn die Quellen die Frage nicht beantworten, antworte genau: \"{KEINE_ANTWORT}\" "
    "Antworte auf Deutsch, knapp und sachlich."
)


@dataclass
class RagAntwort:
    text: str
    quellen: list[SuchTreffer]


def quellen_text(treffer: list[SuchTreffer], max_zeichen_je_quelle: int) -> str:
    return "\n\n".join(
        f"[{n}] {t.dateiname} (Dokument {t.dokument_id})\n{t.text[:max_zeichen_je_quelle]}"
        for n, t in enumerate(treffer, 1)
    )


def antwort_erzeugen(
    llm: LLMClient, frage: str, treffer: list[SuchTreffer], max_zeichen_je_quelle: int = 2000
) -> RagAntwort:
    if not treffer:
        return RagAntwort(KEINE_ANTWORT, [])
    nachrichten = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Quellen:\n\n{quellen_text(treffer, max_zeichen_je_quelle)}\n\nFrage: {frage}"},
    ]
    return RagAntwort(llm.chat_text(nachrichten), treffer)
