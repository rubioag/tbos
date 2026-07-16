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


def test_comma_becomes_space() -> None:
    # Real bug found via odds-api.io evidence: "Surname, Firstname" must
    # not leave a dangling comma glued to the surname token.
    assert normalize_player_name("Borges, Nuno") == "borges nuno"


def test_surname_comma_firstname_matches_reversed_sackmann_form() -> None:
    odds_api_io_form = normalize_player_name("Borges, Nuno")
    sackmann_form = normalize_player_name("Nuno Borges")
    tokens = odds_api_io_form.split(" ")
    assert " ".join(tokens[::-1]) == sackmann_form
