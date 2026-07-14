from tbos.data_adapters.player_resolution.normalize import normalize_player_name


def test_lowercases_and_collapses_whitespace() -> None:
    assert normalize_player_name("  Novak   Djokovic  ") == "novak djokovic"


def test_strips_accents() -> None:
    assert normalize_player_name("Iga Świątek") == "iga swiatek"


def test_hyphen_becomes_space() -> None:
    assert normalize_player_name("Felix Auger-Aliassime") == "felix auger aliassime"


def test_accent_and_hyphen_combined_matches_sackmann_plain_form() -> None:
    # Real evidence: The Odds API-style accented+hyphenated form must
    # normalize identically to Sackmann's plain-ASCII, space-separated
    # winner_name/loser_name field ("Felix Auger Aliassime", verified in
    # the actual downloaded dataset).
    accented = normalize_player_name("Félix Auger-Aliassime")
    plain = normalize_player_name("Felix Auger Aliassime")
    assert accented == plain


def test_apostrophe_removed() -> None:
    assert normalize_player_name("O'Connell") == "oconnell"


def test_period_becomes_space() -> None:
    assert normalize_player_name("J.J. Wolf") == "j j wolf"


def test_case_insensitive() -> None:
    assert normalize_player_name("NOVAK DJOKOVIC") == normalize_player_name("novak djokovic")


def test_deterministic_same_input_same_output() -> None:
    name = "Botic van de Zandschulp"
    assert normalize_player_name(name) == normalize_player_name(name)
