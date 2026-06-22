import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Strip ANSI SGR codes so --help assertions match literal option strings.

    Rich styles each character run separately (e.g. `--opt` becomes `-`+`-opt`
    around color codes), and its color detection is env/version dependent, so
    asserting on raw output is unreliable. Stripping is deterministic.
    """
    return _ANSI_RE.sub("", text)
