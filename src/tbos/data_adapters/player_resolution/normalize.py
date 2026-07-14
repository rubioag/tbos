"""Deterministic name normalization — the same input always produces the
same output, with no locale/OS-dependent behavior (pure Unicode
normalization, no external calls, no randomness).

Strips accents (NFKD decomposition + drop combining marks), flattens
hyphens/periods/apostrophes to spaces or removes them, collapses
whitespace, lowercases. This alone resolves most real cross-provider
spelling differences exactly (e.g. "Félix Auger-Aliassime" vs Sackmann's
"Felix Auger Aliassime" both normalize to "felix auger aliassime") —
verified against TBOS's actual downloaded Sackmann data, not assumed.
"""

from __future__ import annotations

import re
import unicodedata

_PUNCTUATION_TO_SPACE = str.maketrans({"-": " ", ".": " ", "'": "", "’": ""})
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_player_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name.strip())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    flattened = without_accents.translate(_PUNCTUATION_TO_SPACE)
    collapsed = _WHITESPACE_RE.sub(" ", flattened).strip()
    return collapsed.lower()
