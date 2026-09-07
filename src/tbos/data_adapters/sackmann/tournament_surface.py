"""Tournament -> surface lookup, built entirely from Sackmann's own
historical `surface` field keyed by `tourney_name`. No external API: none
of the free odds/stats providers investigated expose per-event surface
reliably (see the MatchContextProvider investigation) — tournaments play
on the same surface year after year in practice (Bastad/Gstaad/Umag =
clay every year in our real downloaded data, 2003-2024), so this is a
real, verifiable signal, not a guess.

A tournament name is only trusted when its RECENT history shows exactly
ONE distinct surface — a name that still maps to multiple surfaces within
that window (relocated tournament, name collision, a change that just
happened) is excluded rather than guessed.

Recency matters because some tournaments genuinely changed surface once,
decades ago, and have been stable ever since: in our real downloaded data
the US Open was Grass (1968-1974), Clay (1975), then Hard (1979-2024), and
the Australian Open was Grass (1969-1987) then Hard (1988-2024). Judging
those against all history would call them "ambiguous" forever on the
strength of evidence that stopped being true 40 years ago. Only the last
`RECENT_EDITIONS_WINDOW` editions of each tournament are considered, and
the window is measured per tournament against its OWN latest edition — so a
discontinued tournament is still judged on its final years rather than
being silently dropped for having no modern editions.

This narrows *which* observations count; it does not weaken the rule
itself. Disagreement inside the window is still an exclusion, never a
guess, and no surface is ever inferred from a tournament's neighbours,
name, or location. Real, honest coverage gap: tournaments with zero
Sackmann history under that name (e.g. Challengers/ITF, whose files this
system doesn't currently download) resolve to nothing — never fabricated.
"""

from __future__ import annotations

import re
from collections import defaultdict

from tbos.data_adapters.sackmann.models import SURFACE_MAP, MatchRow
from tbos.inf1_config.taxonomy import Surface

# Providers punctuate tournament names differently for the same event —
# Sackmann stores "Winston-Salem", odds-api.io sends "Winston Salem". Both
# sides go through the same collapse, so neither spelling is privileged.
_PUNCTUATION = re.compile(r"[^0-9a-z]+")

# A provider sometimes numbers a second edition held in the same year
# ("Kingston 2"); Sackmann only ever names the base tournament.
_EDITION_SUFFIX = re.compile(r"\s+\d+$")

# How many of a tournament's most recent editions are allowed to speak for
# its current surface. Wide enough that a single freak edition (a one-off
# indoor relocation) still shows up as disagreement and forces an exclusion,
# narrow enough that a real, long-settled surface change stops blocking the
# tournament forever.
RECENT_EDITIONS_WINDOW = 10


def normalize_tournament_name(name: str) -> str:
    """Lowercase and collapse every run of punctuation/whitespace to one
    space. Two names that differ only in punctuation therefore land on the
    same key — which is a merge, not a guess: if the merged name turns out
    to cover two real tournaments on different surfaces, the one-surface
    rule below excludes it exactly as it would any other ambiguous name.
    """
    return _PUNCTUATION.sub(" ", name.strip().lower()).strip()


def build_tournament_surface_lookup(
    matches: list[MatchRow], *, recent_editions: int = RECENT_EDITIONS_WINDOW
) -> dict[str, Surface]:
    surfaces_by_edition: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for match in matches:
        if not match.tourney_name or not match.surface:
            continue
        mapped = SURFACE_MAP.get(match.surface)
        if mapped is None:
            continue
        name = normalize_tournament_name(match.tourney_name)
        surfaces_by_edition[name][match.tourney_date.year].add(mapped)

    lookup: dict[str, Surface] = {}
    for name, by_year in surfaces_by_edition.items():
        recent_years = sorted(by_year)[-recent_editions:]
        surfaces = {surface for year in recent_years for surface in by_year[year]}
        if len(surfaces) == 1:
            lookup[name] = Surface(next(iter(surfaces)))
    return lookup


def resolve_league_surface(league_name: str, lookup: dict[str, Surface]) -> Surface | None:
    """`league_name` is odds-api.io's format, e.g. "ATP - Bastad, Sweden"
    or "Challenger - Cordenons, Italy". Tries the text after the tour
    prefix, then just the leading (city/tournament) segment before a
    comma. Exact, normalized match only — never fuzzy, never guessed.
    Returns None if nothing matches (a real, honest "no data" outcome).
    """
    text = league_name.split(" - ", 1)[-1] if " - " in league_name else league_name
    candidates = [text.strip()]
    if "," in text:
        candidates.append(text.split(",", 1)[0].strip())

    normalized = [normalize_tournament_name(c) for c in candidates]
    for candidate in normalized:
        surface = lookup.get(candidate)
        if surface is not None:
            return surface

    # Last resort only: a numbered edition falls back to its base name, and
    # never before every exact form has been tried — so a numbered event that
    # exists in its own right still wins.
    for candidate in normalized:
        stripped = _EDITION_SUFFIX.sub("", candidate)
        if stripped == candidate:
            continue
        surface = lookup.get(stripped)
        if surface is not None:
            return surface
    return None
