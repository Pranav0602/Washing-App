"""URL helpers shared by every module's URL configuration.

Why this exists
---------------
Django's ``APPEND_SLASH`` is disabled for this API on purpose: a redirect can drop a
POST body or change the method depending on the client, which is unacceptable for
money and booking commands. Every hand-written route here therefore has **no**
trailing slash.

DRF's routers, however, always emit one (``^addresses/$``). With both conventions in
play, a request to ``/api/v1/addresses`` 404s while ``/api/v1/addresses/`` works,
which is exactly the kind of inconsistency that produces silent client bugs.

:func:`normalise_patterns` rebuilds router patterns without the trailing slash so the
whole API follows one rule.
"""

from __future__ import annotations

from django.urls import URLPattern, URLResolver
from django.urls.resolvers import RegexPattern


def _without_trailing_slash(regex: str) -> str:
    """``^addresses/$`` -> ``^addresses\\Z``.

    ``\\Z`` rather than ``$``: both anchor the end of the string, but ``$`` also
    matches before a trailing newline, and Django's own system check warns about any
    ``include()``-ed route ending in ``$``. ``\\Z`` is both stricter and warning-free.
    """
    if regex.endswith("/$"):
        return regex[:-2] + r"\Z"
    if regex.endswith("/"):
        return regex[:-1]
    return regex


def normalise_patterns(patterns) -> list:
    """Recursively remove trailing slashes from URL patterns.

    ``URLResolver`` entries are normalised in place; leaf ``URLPattern`` entries are
    rebuilt with a corrected regex, because a route pattern's compiled regex is
    derived in its constructor and cannot be edited afterwards.
    """
    normalised: list = []
    for entry in patterns:
        if isinstance(entry, URLResolver):
            entry.url_patterns = normalise_patterns(entry.url_patterns)
            normalised.append(entry)
            continue

        regex = getattr(entry.pattern, "regex", None)
        raw = regex.pattern if regex is not None else str(entry.pattern)
        fixed = _without_trailing_slash(raw)

        if fixed != raw:
            normalised.append(
                URLPattern(
                    RegexPattern(fixed, name=getattr(entry.pattern, "name", None)),
                    entry.callback,
                    entry.default_args,
                    entry.name,
                )
            )
        else:
            normalised.append(entry)
    return normalised