# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import time

import requests
from piccione.upload.on_zenodo import get_headers
from rich.console import Console

from changes_metadata_manager.zenodo_metadata import ZenodoUpdatePayload

console = Console()

MAX_RETRIES = 5
BASE_BACKOFF = 10


def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    response = requests.request(method, url, **kwargs)
    for attempt in range(1, MAX_RETRIES):
        if response.status_code != 429:
            return response
        wait = BASE_BACKOFF * (2**attempt)
        console.print(f"  [yellow]Rate limited, retrying in {wait}s...[/yellow]")
        time.sleep(wait)
        response = requests.request(method, url, **kwargs)
    return response


def fetch_record(
    zenodo_url: str, record_id: str, access_token: str, user_agent: str
) -> tuple[dict, bool]:
    headers = get_headers(access_token, user_agent)
    headers["Accept"] = "application/vnd.inveniordm.v1+json"
    response = request_with_retry(
        "GET", f"{zenodo_url}/records/{record_id}/draft", headers=headers, timeout=30
    )
    has_edit_draft = response.status_code != 404
    if not has_edit_draft:
        response = request_with_retry(
            "GET", f"{zenodo_url}/records/{record_id}", headers=headers, timeout=30
        )
    response.raise_for_status()
    return response.json(), has_edit_draft


def create_edit_draft(
    zenodo_url: str, record_id: str, access_token: str, user_agent: str
) -> dict:
    response = request_with_retry(
        "POST",
        f"{zenodo_url}/records/{record_id}/draft",
        headers=get_headers(access_token, user_agent),
        timeout=30,
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
        timeout=30,
    )
    response.raise_for_status()


def publish_draft(
    zenodo_url: str, record_id: str, access_token: str, user_agent: str
) -> None:
    response = request_with_retry(
        "POST",
        f"{zenodo_url}/records/{record_id}/draft/actions/publish",
        headers=get_headers(access_token, user_agent),
        timeout=30,
    )
    response.raise_for_status()
