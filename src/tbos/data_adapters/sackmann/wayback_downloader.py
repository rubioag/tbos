"""Downloads Jeff Sackmann's official tennis_atp/tennis_wta match CSVs
via the Internet Archive Wayback Machine.

Why this exists: github.com/JeffSackmann/tennis_atp and tennis_wta were
live (HTTP 200) as late as 2026-06-06 and returned 404 from 2026-06-22
onward (verified via Wayback CDX timestamps). No rename redirect, no
account suspension, no announcement on tennisabstract.com (Sackmann's
own site, blog silent since 2026-04-16). Cause unknown — not guessed
here. The Wayback Machine holds byte-identical mirrors of the original
raw.githubusercontent.com files, crawled mostly mid-to-late 2025 — the
only remaining traceable, official-content source, so this downloads
from there instead of an unverified third-party fork.

Known, permanent limitation of this source (confirmed via CDX query,
not assumed): no archived snapshot exists for 2025 or 2026 match-year
files for either tour. Whatever the true cutoff year for a given
tour turns out to be, this downloader does not assume it — it queries
the CDX index per file and only downloads what the index confirms
exists. Missing years are skipped and reported, never fabricated.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from tbos.data_adapters.http.retry import retry_with_backoff

logger = logging.getLogger("tbos.data_adapters.sackmann.wayback")

CDX_URL = "https://web.archive.org/cdx/search/cdx"

GITHUB_REPO_PATH = {"atp": "JeffSackmann/tennis_atp", "wta": "JeffSackmann/tennis_wta"}
FILE_PREFIX = {"atp": "atp", "wta": "wta"}

# Two path schemes were observed across CDX snapshots for the same repo,
# depending on when the crawl happened (GitHub changed raw URL layout).
# Both are tried; whichever the index actually has wins.
BRANCH_PATH_VARIANTS = ("refs/heads/master", "master")


class WaybackDownloadResult:
    def __init__(self) -> None:
        self.downloaded: list[str] = []
        self.unavailable: list[str] = []
        self.skipped_existing: list[str] = []


def _find_archived_snapshot(
    client: httpx.Client, repo: str, file_path: str, *, sleep: Callable[[float], None],
) -> tuple[str, str] | None:
    """Returns (archived_content_url, snapshot_timestamp) for the most
    recent HTTP-200 capture of the given raw.githubusercontent.com path,
    or None if the CDX index has no such capture — never guessed.
    """
    for branch_variant in BRANCH_PATH_VARIANTS:
        target = f"raw.githubusercontent.com/{repo}/{branch_variant}/{file_path}"
        params = {"url": target, "output": "json", "filter": "statuscode:200", "collapse": "digest"}

        def _do_request(params: dict[str, str] = params) -> list[list[str]]:
            response = client.get(CDX_URL, params=params)
            response.raise_for_status()
            text = response.text.strip()
            return json.loads(text) if text else []

        try:
            rows = retry_with_backoff(
                _do_request, max_retries=4, backoff_base_seconds=3.0,
                retryable=lambda exc: True, logger=logger, operation_name=f"cdx_lookup({target})",
                sleep=sleep,
            )
        except Exception as exc:  # noqa: BLE001 - CDX/network failure, real limitation, not a bug
            logger.warning(
                "CDX lookup failed, skipping this path variant",
                extra={"target": target, "error": str(exc)},
            )
            continue

        if len(rows) <= 1:  # header row only, or empty — no capture exists
            continue

        _header, *data_rows = rows
        timestamp = data_rows[-1][1]  # most recent matching capture
        original_url = f"https://raw.githubusercontent.com/{repo}/{branch_variant}/{file_path}"
        archived_url = f"https://web.archive.org/web/{timestamp}id_/{original_url}"
        return archived_url, timestamp

    return None


def _download_content(
    client: httpx.Client, archived_url: str, *, sleep: Callable[[float], None],
) -> bytes | None:
    def _do_request() -> bytes:
        response = client.get(archived_url)
        response.raise_for_status()
        return response.content

    try:
        return retry_with_backoff(
            _do_request, max_retries=3, backoff_base_seconds=3.0,
            retryable=lambda exc: True, logger=logger, operation_name=f"download({archived_url})",
            sleep=sleep,
        )
    except Exception as exc:  # noqa: BLE001 - network/Wayback failure, real limitation, not a bug
        logger.warning(
            "archived content download failed, skipping file",
            extra={"url": archived_url, "error": str(exc)},
        )
        return None


def download_sackmann_matches(
    dest_dir: Path,
    *,
    tours: tuple[str, ...] = ("atp", "wta"),
    start_year: int = 1968,
    end_year: int = 2026,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> WaybackDownloadResult:
    """Populates dest_dir/{atp,wta}/{prefix}_matches_{year}.csv from the
    Wayback Machine. Incremental: files already present on disk are never
    re-downloaded. Never raises for an individual missing year — that is
    an expected, reported outcome, not a failure of this function.
    """
    result = WaybackDownloadResult()

    with httpx.Client(timeout=30.0, transport=transport) as client:
        for tour in tours:
            repo = GITHUB_REPO_PATH[tour]
            prefix = FILE_PREFIX[tour]
            tour_dir = dest_dir / tour
            tour_dir.mkdir(parents=True, exist_ok=True)

            for year in range(start_year, end_year + 1):
                filename = f"{prefix}_matches_{year}.csv"
                dest_path = tour_dir / filename

                if dest_path.exists():
                    result.skipped_existing.append(filename)
                    continue

                snapshot = _find_archived_snapshot(client, repo, filename, sleep=sleep)
                if snapshot is None:
                    result.unavailable.append(filename)
                    logger.info(
                        "no Wayback snapshot found for this file, skipped",
                        extra={"csv_filename": filename, "tour": tour},
                    )
                    continue

                archived_url, timestamp = snapshot
                content = _download_content(client, archived_url, sleep=sleep)
                if content is None:
                    result.unavailable.append(filename)
                    continue

                dest_path.write_bytes(content)
                result.downloaded.append(filename)
                logger.info(
                    "downloaded match file from Wayback Machine",
                    extra={
                        "csv_filename": filename, "tour": tour,
                        "snapshot_timestamp": timestamp, "bytes": len(content),
                    },
                )

    return result
