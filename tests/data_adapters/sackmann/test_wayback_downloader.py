"""No real network calls: every test injects an httpx.MockTransport."""

from __future__ import annotations

import json
import logging

import httpx

from tbos.data_adapters.sackmann.wayback_downloader import download_sackmann_matches

CDX_HEADER = ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"]


def _cdx_row(url: str, timestamp: str) -> list[str]:
    return ["urlkey", timestamp, url, "text/plain", "200", "DIGEST", "100"]


def test_downloads_available_years_and_reports_unavailable_ones(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "cdx/search/cdx" in url:
            target = request.url.params.get("url", "")
            if "atp_matches_2020.csv" in target and "refs/heads/master" in target:
                original = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/refs/heads/master/atp_matches_2020.csv"
                return httpx.Response(200, text=json.dumps([CDX_HEADER, _cdx_row(original, "20250717083121")]))
            return httpx.Response(200, text=json.dumps([CDX_HEADER]))  # header only = not archived
        if "web.archive.org/web/" in url and "atp_matches_2020.csv" in url:
            return httpx.Response(200, content=b"tourney_date,winner_id,loser_id\n20200101,p1,p2\n")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = download_sackmann_matches(
        tmp_path, tours=("atp",), start_year=2020, end_year=2021, transport=transport, sleep=lambda _: None,
    )

    assert result.downloaded == ["atp_matches_2020.csv"]
    assert result.unavailable == ["atp_matches_2021.csv"]
    assert (tmp_path / "atp" / "atp_matches_2020.csv").read_bytes() == b"tourney_date,winner_id,loser_id\n20200101,p1,p2\n"


def test_info_level_logging_does_not_crash_on_reserved_logrecord_keys(tmp_path, caplog) -> None:
    """Regression: extra={"filename": ...} collides with the reserved
    LogRecord.filename attribute and raises KeyError inside makeRecord —
    but only once INFO is actually enabled (default level is WARNING, so
    normal test runs silently never exercised this code path). Real bug,
    found by running the downloader with logging.basicConfig(INFO).
    """
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "cdx/search/cdx" in url:
            target = request.url.params.get("url", "")
            if "atp_matches_2020.csv" in target and "refs/heads/master" in target:
                original = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/refs/heads/master/atp_matches_2020.csv"
                return httpx.Response(200, text=json.dumps([CDX_HEADER, _cdx_row(original, "20250717083121")]))
            return httpx.Response(200, text=json.dumps([CDX_HEADER]))
        if "web.archive.org/web/" in url and "atp_matches_2020.csv" in url:
            return httpx.Response(200, content=b"data")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    with caplog.at_level(logging.INFO, logger="tbos.data_adapters.sackmann.wayback"):
        result = download_sackmann_matches(
            tmp_path, tours=("atp",), start_year=2020, end_year=2021, transport=transport, sleep=lambda _: None,
        )

    assert result.downloaded == ["atp_matches_2020.csv"]  # would have raised KeyError before the fix
    assert result.unavailable == ["atp_matches_2021.csv"]
    assert any("downloaded match file" in r.message for r in caplog.records)
    assert any("no Wayback snapshot found" in r.message for r in caplog.records)


def test_already_downloaded_file_is_skipped_not_refetched(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text=json.dumps([CDX_HEADER]))

    tour_dir = tmp_path / "atp"
    tour_dir.mkdir()
    (tour_dir / "atp_matches_2020.csv").write_text("already here")

    transport = httpx.MockTransport(handler)
    result = download_sackmann_matches(
        tmp_path, tours=("atp",), start_year=2020, end_year=2020, transport=transport, sleep=lambda _: None,
    )

    assert result.skipped_existing == ["atp_matches_2020.csv"]
    assert calls["n"] == 0  # no CDX/download calls at all for an existing file
    assert (tour_dir / "atp_matches_2020.csv").read_text() == "already here"  # untouched


def test_cdx_failure_marks_file_unavailable_not_a_crash(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "cdx/search/cdx" in str(request.url):
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = download_sackmann_matches(
        tmp_path, tours=("atp",), start_year=2020, end_year=2020, transport=transport, sleep=lambda _: None,
    )

    assert result.downloaded == []
    assert result.unavailable == ["atp_matches_2020.csv"]


def test_download_failure_after_found_snapshot_marks_unavailable(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "cdx/search/cdx" in url:
            original = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/refs/heads/master/atp_matches_2020.csv"
            return httpx.Response(200, text=json.dumps([CDX_HEADER, _cdx_row(original, "20250717083121")]))
        if "web.archive.org/web/" in url:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = download_sackmann_matches(
        tmp_path, tours=("atp",), start_year=2020, end_year=2020, transport=transport, sleep=lambda _: None,
    )

    assert result.downloaded == []
    assert result.unavailable == ["atp_matches_2020.csv"]
    assert not (tmp_path / "atp" / "atp_matches_2020.csv").exists()  # never a partial/fabricated file


def test_both_tours_write_to_separate_directories(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "cdx/search/cdx" in url:
            target = request.url.params.get("url", "")
            if "refs/heads/master" in target:
                tour = "tennis_atp" if "tennis_atp" in target else "tennis_wta"
                fname = "atp_matches_2020.csv" if tour == "tennis_atp" else "wta_matches_2020.csv"
                original = f"https://raw.githubusercontent.com/JeffSackmann/{tour}/refs/heads/master/{fname}"
                return httpx.Response(200, text=json.dumps([CDX_HEADER, _cdx_row(original, "20250717083121")]))
            return httpx.Response(200, text=json.dumps([CDX_HEADER]))
        if "web.archive.org/web/" in url:
            return httpx.Response(200, content=b"data")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = download_sackmann_matches(
        tmp_path, tours=("atp", "wta"), start_year=2020, end_year=2020, transport=transport, sleep=lambda _: None,
    )

    assert (tmp_path / "atp" / "atp_matches_2020.csv").exists()
    assert (tmp_path / "wta" / "wta_matches_2020.csv").exists()
    assert set(result.downloaded) == {"atp_matches_2020.csv", "wta_matches_2020.csv"}
