from enum import Enum


class DokumentTyp(str, Enum):
    PDF = "pdf"
    EML = "eml"
    AUDIO = "audio"
    BILD = "bild"
    TEXT = "text"
    OFFICE = "office"
    VIDEO = "video"
    SONSTIG = "sonstig"


class ExtraktionsMethode(str, Enum):
    SCHNELL = "schnell"
    DOCLING = "docling"
    VISION = "vision"
    WHISPER = "whisper"
    EML = "eml"
    TEXT = "text"


class NerMethode(str, Enum):
    GLINER = "gliner"
    MUSTER = "muster"
    LLM = "llm"


class AnalyseArt(str, Enum):
    ZUSAMMENFASSUNG = "zusammenfassung"
    KLASSIFIKATION = "klassifikation"
    KLASSIFIKATION_CLEF = "klassifikation_clef"
    BILDBESCHREIBUNG = "bildbeschreibung"


class LaufStatus(str, Enum):
    ERFOLG = "erfolg"
    FEHLER = "fehler"
    UEBERSPRUNGEN = "uebersprungen"
