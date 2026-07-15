from datetime import UTC, datetime

import pytest

from tbos.data_adapters.contracts import EntityNotFoundError
from tbos.data_adapters.player_resolution.resolver import PlayerNameResolver
from tbos.data_adapters.player_resolution.store import PlayerNameMappingStore
from tests.data_adapters.player_resolution.fixtures import (
    ambiguous_initial_matches,
    ambiguous_name_matches,
    real_player_matches,
)

NOW = datetime(2026, 7, 14, tzinfo=UTC)


def _resolver(tmp_path, matches=None) -> tuple[PlayerNameResolver, PlayerNameMappingStore]:
    store = PlayerNameMappingStore(tmp_path / "player_name_mappings.jsonl")
    resolver = PlayerNameResolver(matches or real_player_matches(), store)
    return resolver, store


def test_exact_match_resolves_with_full_confidence(tmp_path) -> None:
    resolver, store = _resolver(tmp_path)
    player_id = resolver.resolve("Novak Djokovic", now=NOW)
    assert player_id == "104925"
    record = store.get("the_odds_api", "Novak Djokovic")
    assert record is not None
    assert record.confidence == 1.0
    assert record.method == "exact"


@pytest.mark.parametrize(
    "source_name,expected_id",
    [
        ("Carlos Alcaraz", "207989"),
        ("Iga Swiatek", "216347"),
        ("Coco Gauff", "221103"),
    ],
)
def test_exact_match_real_players(tmp_path, source_name, expected_id) -> None:
    resolver, _ = _resolver(tmp_path)
    assert resolver.resolve(source_name, now=NOW) == expected_id


def test_accented_hyphenated_variant_resolves_exactly(tmp_path) -> None:
    resolver, store = _resolver(tmp_path)
    player_id = resolver.resolve("Félix Auger-Aliassime", now=NOW)
    assert player_id == "200000"
    assert store.get("the_odds_api", "Félix Auger-Aliassime").method == "exact"


def test_multiword_particle_surname_resolves_exactly(tmp_path) -> None:
    resolver, _ = _resolver(tmp_path)
    assert resolver.resolve("Botic van de Zandschulp", now=NOW) == "122298"


def test_reversed_word_order_resolves_via_reversed_order_tier(tmp_path) -> None:
    resolver, store = _resolver(tmp_path)
    player_id = resolver.resolve("Djokovic Novak", now=NOW)
    assert player_id == "104925"
    record = store.get("the_odds_api", "Djokovic Novak")
    assert record.method == "reversed_order"
    assert record.confidence == 0.95


def test_minor_typo_resolves_via_fuzzy_tier_with_recorded_confidence(tmp_path) -> None:
    resolver, store = _resolver(tmp_path)
    player_id = resolver.resolve("Novak Djokovc", now=NOW)  # missing 'i'
    assert player_id == "104925"
    record = store.get("the_odds_api", "Novak Djokovc")
    assert record.method == "fuzzy"
    assert 0.90 <= record.confidence < 1.0


def test_nickname_vs_legal_name_abstains_below_threshold(tmp_path) -> None:
    """'Cori Gauff' (legal name) vs 'Coco Gauff' (Sackmann/tour nickname)
    — real-world case, ratio ~0.80, below the 0.90 threshold. Must
    abstain rather than guess.
    """
    resolver, store = _resolver(tmp_path)
    with pytest.raises(EntityNotFoundError):
        resolver.resolve("Cori Gauff", now=NOW)
    # abstention is never recorded as a resolution
    assert store.get("the_odds_api", "Cori Gauff") is None


def test_abbreviated_first_name_abstains_below_threshold(tmp_path) -> None:
    resolver, _ = _resolver(tmp_path)
    with pytest.raises(EntityNotFoundError):
        resolver.resolve("N. Djokovic", now=NOW)


def test_unrelated_name_abstains(tmp_path) -> None:
    resolver, _ = _resolver(tmp_path)
    with pytest.raises(EntityNotFoundError):
        resolver.resolve("Some Totally Unrelated Person", now=NOW)


def test_ambiguous_exact_match_abstains_never_guesses(tmp_path) -> None:
    resolver, store = _resolver(tmp_path, matches=ambiguous_name_matches())
    with pytest.raises(EntityNotFoundError, match="ambiguous"):
        resolver.resolve("John Smith", now=NOW)
    assert store.get("the_odds_api", "John Smith") is None


def test_second_resolve_uses_cached_store_not_recomputed(tmp_path) -> None:
    store = PlayerNameMappingStore(tmp_path / "mappings.jsonl")
    resolver = PlayerNameResolver(real_player_matches(), store)
    resolver.resolve("Novak Djokovic", now=NOW)

    # A resolver with an EMPTY match index still resolves the same name
    # correctly, because the store answers before the index is consulted.
    empty_resolver = PlayerNameResolver([], store)
    assert empty_resolver.resolve("Novak Djokovic", now=NOW) == "104925"


def test_mapping_persists_across_store_instances(tmp_path) -> None:
    path = tmp_path / "mappings.jsonl"
    store1 = PlayerNameMappingStore(path)
    resolver1 = PlayerNameResolver(real_player_matches(), store1)
    resolver1.resolve("Novak Djokovic", now=NOW)

    store2 = PlayerNameMappingStore(path)  # fresh instance, same file
    assert store2.get("the_odds_api", "Novak Djokovic").player_id == "104925"


def test_store_file_is_append_only_one_line_per_new_resolution(tmp_path) -> None:
    path = tmp_path / "mappings.jsonl"
    store = PlayerNameMappingStore(path)
    resolver = PlayerNameResolver(real_player_matches(), store)

    resolver.resolve("Novak Djokovic", now=NOW)
    resolver.resolve("Novak Djokovic", now=NOW)  # repeat, must not add a second line
    resolver.resolve("Carlos Alcaraz", now=NOW)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_different_sources_kept_independent(tmp_path) -> None:
    store = PlayerNameMappingStore(tmp_path / "mappings.jsonl")
    resolver_a = PlayerNameResolver(real_player_matches(), store, source="the_odds_api")
    resolver_b = PlayerNameResolver(real_player_matches(), store, source="some_other_provider")

    resolver_a.resolve("Novak Djokovic", now=NOW)
    assert store.get("some_other_provider", "Novak Djokovic") is None
    resolver_b.resolve("Novak Djokovic", now=NOW)
    assert store.get("some_other_provider", "Novak Djokovic") is not None


@pytest.mark.parametrize(
    "abbreviated_name,expected_id",
    [
        ("Tiafoe F.", "126207"),
        ("Djokovic N.", "104925"),
        ("Swiatek I.", "216347"),
        ("Gauff C.", "221103"),
        ("Auger-Aliassime F.", "200000"),  # tennis-data.co.uk hyphenates this one
        ("Van De Zandschulp B.", "122298"),
    ],
)
def test_abbreviated_surname_resolves_real_tennis_data_format(tmp_path, abbreviated_name, expected_id) -> None:
    resolver, store = _resolver(tmp_path)
    player_id = resolver.resolve(abbreviated_name, now=NOW)
    assert player_id == expected_id
    record = store.get("the_odds_api", abbreviated_name)
    assert record.method == "abbreviated_surname"
    assert record.confidence == 0.92


def test_abbreviated_surname_ambiguous_initial_abstains(tmp_path) -> None:
    """Two different players, both surnamed Djokovic, both first names
    starting with 'N' — "Djokovic N." cannot be disambiguated from
    surname+initial alone and must abstain, never guess one.
    """
    resolver, store = _resolver(tmp_path, matches=ambiguous_initial_matches())
    with pytest.raises(EntityNotFoundError, match="ambiguous"):
        resolver.resolve("Djokovic N.", now=NOW)
    assert store.get("the_odds_api", "Djokovic N.") is None


def test_abbreviated_surname_unknown_player_abstains(tmp_path) -> None:
    resolver, _ = _resolver(tmp_path)
    with pytest.raises(EntityNotFoundError):
        resolver.resolve("Nobody Z.", now=NOW)
