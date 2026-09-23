"""Helpers de deep link seguros para cerrar openAuthSessionAsync tras OAuth."""

from __future__ import annotations

from urllib.parse import urlencode, urlparse


def safe_app_redirect(url: str | None) -> str | None:
    """
    Solo deep links de la app (exp/eliseo) o proxy de Expo Auth.
    Evita open-redirect hacia dominios arbitrarios.
    """
    if not url or not str(url).strip():
        return None
    raw = str(url).strip()
    if len(raw) > 512:
        return None
    parsed = urlparse(raw)
    if parsed.scheme in {"exp", "exps", "eliseo"}:
        return raw
    if parsed.scheme == "https" and parsed.netloc == "auth.expo.io":
        return raw
    return None


def with_query(url: str, **params: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{urlencode(params)}"
