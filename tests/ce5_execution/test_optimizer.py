from tbos.ce5_execution.optimizer import BookQuote, optimize_execution


def test_single_book_fully_funds_when_liquidity_sufficient() -> None:
    quotes = [BookQuote(book_id="a", odds=1.9, available_liquidity=1000)]
    splits = optimize_execution(200, quotes)
    assert len(splits) == 1
    assert splits[0].stake_portion == 200


def test_prefers_best_odds_first() -> None:
    quotes = [
        BookQuote(book_id="low", odds=1.8, available_liquidity=1000),
        BookQuote(book_id="high", odds=2.1, available_liquidity=1000),
    ]
    splits = optimize_execution(100, quotes)
    assert splits[0].book_id == "high"


def test_splits_across_books_when_one_lacks_liquidity() -> None:
    quotes = [
        BookQuote(book_id="best", odds=2.1, available_liquidity=50),
        BookQuote(book_id="second", odds=2.0, available_liquidity=1000),
    ]
    splits = optimize_execution(150, quotes)
    assert len(splits) == 2
    assert splits[0].book_id == "best"
    assert splits[0].stake_portion == 50
    assert splits[1].book_id == "second"
    assert splits[1].stake_portion == 100


def test_never_fills_more_than_target_stake() -> None:
    quotes = [BookQuote(book_id="a", odds=2.0, available_liquidity=10_000)]
    splits = optimize_execution(100, quotes)
    assert sum(s.stake_portion for s in splits) == 100


def test_total_liquidity_insufficient_returns_partial_fill() -> None:
    quotes = [BookQuote(book_id="a", odds=2.0, available_liquidity=30)]
    splits = optimize_execution(100, quotes)
    assert sum(s.stake_portion for s in splits) == 30


def test_no_quotes_returns_empty() -> None:
    assert optimize_execution(100, []) == []


def test_zero_target_stake_returns_empty() -> None:
    quotes = [BookQuote(book_id="a", odds=2.0, available_liquidity=1000)]
    assert optimize_execution(0, quotes) == []


def test_negative_liquidity_quote_ignored() -> None:
    quotes = [BookQuote(book_id="a", odds=2.0, available_liquidity=-50)]
    assert optimize_execution(100, quotes) == []
