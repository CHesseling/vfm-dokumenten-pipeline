"""URLs fuer Anzeige und Fehlermeldungen: Zugangsdaten (user:pass@) entfernen."""

import re
from urllib.parse import urlsplit


def ohne_zugangsdaten(url: str | None) -> str | None:
    if not url:
        return url
    try:
        teile = urlsplit(url)
        if teile.username is None and teile.password is None:
            return url
        host = teile.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if teile.port:
            host += f":{teile.port}"
        return teile._replace(netloc=host).geturl()
    except ValueError:  # z. B. ungueltiger Port: textuell entfernen
        return re.sub(r"^([A-Za-z][A-Za-z0-9+.-]*://)[^/?#]*@", r"\1", url)
