# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import json
import sqlite3
import time
from pathlib import Path

import requests
from piccione.upload.on_zenodo import get_headers
from rich.console import Console

from changes_metadata_manager.zenodo_metadata import ZenodoUpdatePayload

console = Console()

MAX_RETRIES = 5
BASE_BACKOFF = 10
REQUEST_TIMEOUT = 120
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
CACHE_TTL_SECONDS = 24 * 60 * 60


class ZenodoRecordCache:
    def __init__(self, path: Path, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                zenodo_url TEXT NOT NULL,
                record_id TEXT NOT NULL,
                fetched_at REAL NOT NULL,
                has_edit_draft INTEGER NOT NULL,
                record_json TEXT NOT NULL,
                PRIMARY KEY (zenodo_url, record_id)
            )
            """
        )
        self.connection.commit()

    def __enter__(self) -> "ZenodoRecordCache":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        self.connection.close()

    def get(self, zenodo_url: str, record_id: str) -> tuple[dict, bool] | None:
        normalized_url = zenodo_url.rstrip("/")
        row = self.connection.execute(
            """
            SELECT fetched_at, has_edit_draft, record_json
            FROM records
            WHERE zenodo_url = ? AND record_id = ?
            """,
            (normalized_url, record_id),
        ).fetchone()
        if row is None:
            return None

        fetched_at, has_edit_draft, record_json = row
        if time.time() - fetched_at >= self.ttl_seconds:
            self.invalidate(normalized_url, record_id)
            return None
        return json.loads(record_json), bool(has_edit_draft)

    def set(
        self,
        zenodo_url: str,
        record_id: str,
        record: dict,
        has_edit_draft: bool,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO records (
                zenodo_url, record_id, fetched_at, has_edit_draft, record_json
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (zenodo_url, record_id) DO UPDATE SET
                fetched_at = excluded.fetched_at,
                has_edit_draft = excluded.has_edit_draft,
                record_json = excluded.record_json
            """,
            (
                zenodo_url.rstrip("/"),
                record_id,
                time.time(),
                has_edit_draft,
                json.dumps(record),
            ),
        )
        self.connection.commit()

    def invalidate(self, zenodo_url: str, record_id: str) -> None:
        self.connection.execute(
            "DELETE FROM records WHERE zenodo_url = ? AND record_id = ?",
            (zenodo_url.rstrip("/"), record_id),
        )
        self.connection.commit()


def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    response = requests.request(method, url, **kwargs)
    for attempt in range(1, MAX_RETRIES):
        if response.status_code not in RETRYABLE_STATUS_CODES:
            return response
        wait = BASE_BACKOFF * (2**attempt)
        console.print(
            f"  [yellow]HTTP {response.status_code}, retrying in {wait}s...[/yellow]"
        )
        time.sleep(wait)
        response = requests.request(method, url, **kwargs)
    return response


def fetch_record(
    zenodo_url: str, record_id: str, access_token: str, user_agent: str
) -> tuple[dict, bool]:
    headers = get_headers(access_token, user_agent)
    headers["Accept"] = "application/vnd.inveniordm.v1+json"
    response = request_with_retry(
        "GET",
        f"{zenodo_url}/records/{record_id}/draft",
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    has_edit_draft = response.status_code != 404
    if not has_edit_draft:
        return (
            fetch_published_record(
                zenodo_url,
                record_id,
                access_token,
                user_agent,
            ),
            False,
        )
    response.raise_for_status()
    return response.json(), True


def fetch_published_record(
    zenodo_url: str, record_id: str, access_token: str, user_agent: str
) -> dict:
    return _fetch_published_record(
        f"{zenodo_url}/records/{record_id}",
        access_token,
        user_agent,
    )


def fetch_latest_published_record(
    zenodo_url: str, record_id: str, access_token: str, user_agent: str
) -> dict:
    return _fetch_published_record(
        f"{zenodo_url}/records/{record_id}/versions/latest",
        access_token,
        user_agent,
    )


def _fetch_published_record(
    record_url: str, access_token: str, user_agent: str
) -> dict:
    headers = get_headers(access_token, user_agent)
    headers["Accept"] = "application/vnd.inveniordm.v1+json"
    response = request_with_retry(
        "GET",
        record_url,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def create_edit_draft(
    zenodo_url: str, record_id: str, access_token: str, user_agent: str
) -> dict:
    response = request_with_retry(
        "POST",
        f"{zenodo_url}/records/{record_id}/draft",
        headers=get_headers(access_token, user_agent),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def update_draft(
    zenodo_url: str,
    record_id: str,
    access_token: str,
    user_agent: str,
    payload: ZenodoUpdatePayload,
) -> None:
    response = request_with_retry(
        "PUT",
        f"{zenodo_url}/records/{record_id}/draft",
        headers=get_headers(access_token, user_agent, "application/json"),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()


def publish_draft(
    zenodo_url: str, record_id: str, access_token: str, user_agent: str
) -> None:
    response = request_with_retry(
        "POST",
        f"{zenodo_url}/records/{record_id}/draft/actions/publish",
        headers=get_headers(access_token, user_agent),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
