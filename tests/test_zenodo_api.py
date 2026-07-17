# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

from unittest.mock import MagicMock, call, patch

import pytest
import requests

from changes_metadata_manager.zenodo_api import (
    CACHE_TTL_SECONDS,
    MAX_RETRIES,
    ZenodoRecordCache,
    create_edit_draft,
    fetch_latest_published_record,
    fetch_published_record,
    fetch_record,
    publish_draft,
    request_with_retry,
    update_draft,
)
from changes_metadata_manager.zenodo_metadata import ZenodoUpdatePayload


@patch("changes_metadata_manager.zenodo_api.time.time", return_value=1000)
def test_record_cache_stores_expires_and_invalidates(mock_time, tmp_path):
    cache_path = tmp_path / "records.sqlite3"
    record = {"metadata": {"title": "Record"}}

    with ZenodoRecordCache(cache_path) as cache:
        assert cache.get("https://zenodo.org/api/", "123") is None

        cache.set("https://zenodo.org/api/", "123", record, False)
        assert cache.get("https://zenodo.org/api", "123") == (record, False)
        assert cache.get("https://sandbox.zenodo.org/api", "123") is None

        mock_time.return_value = 1000 + CACHE_TTL_SECONDS
        assert cache.get("https://zenodo.org/api", "123") is None

        cache.set("https://zenodo.org/api", "123", record, True)
        assert cache.get("https://zenodo.org/api", "123") == (record, True)
        cache.invalidate("https://zenodo.org/api/", "123")
        assert cache.get("https://zenodo.org/api", "123") is None


@patch("changes_metadata_manager.zenodo_api.time.sleep")
@patch("changes_metadata_manager.zenodo_api.requests.request")
def test_request_retries_rate_limits(mock_request, mock_sleep):
    rate_limited = MagicMock(status_code=429)
    success = MagicMock(status_code=200)
    mock_request.side_effect = [rate_limited, rate_limited, success]

    result = request_with_retry("GET", "https://example.org")

    assert result == success
    assert mock_request.call_count == 3
    assert mock_sleep.call_args_list == [call(20), call(40)]


@pytest.mark.parametrize("status_code", [502, 503, 504])
@patch("changes_metadata_manager.zenodo_api.time.sleep")
@patch("changes_metadata_manager.zenodo_api.requests.request")
def test_request_retries_gateway_errors(mock_request, mock_sleep, status_code):
    gateway_error = MagicMock(status_code=status_code)
    success = MagicMock(status_code=200)
    mock_request.side_effect = [gateway_error, success]

    result = request_with_retry("GET", "https://example.org")

    assert result == success
    assert mock_request.call_count == 2
    assert mock_sleep.call_args_list == [call(20)]


@patch("changes_metadata_manager.zenodo_api.time.sleep")
@patch("changes_metadata_manager.zenodo_api.requests.request")
def test_request_returns_final_rate_limit(mock_request, mock_sleep):
    rate_limited = MagicMock(status_code=429)
    mock_request.return_value = rate_limited

    result = request_with_retry("GET", "https://example.org")

    assert result == rate_limited
    assert mock_request.call_count == MAX_RETRIES


@patch("changes_metadata_manager.zenodo_api.request_with_retry")
def test_fetches_existing_draft(mock_request):
    response = MagicMock(status_code=200)
    response.json.return_value = {"metadata": {"title": "draft"}}
    mock_request.return_value = response

    result = fetch_record("https://zenodo.org/api", "123", "token", "agent")

    assert result == ({"metadata": {"title": "draft"}}, True)
    assert mock_request.call_count == 1
    assert mock_request.call_args.args[:2] == (
        "GET",
        "https://zenodo.org/api/records/123/draft",
    )


@patch("changes_metadata_manager.zenodo_api.request_with_retry")
def test_fetches_published_record_when_draft_is_missing(mock_request):
    missing = MagicMock(status_code=404)
    published = MagicMock(status_code=200)
    published.json.return_value = {"metadata": {"title": "published"}}
    mock_request.side_effect = [missing, published]

    result = fetch_record("https://zenodo.org/api", "123", "token", "agent")

    assert result == ({"metadata": {"title": "published"}}, False)
    assert [item.args[:2] for item in mock_request.call_args_list] == [
        ("GET", "https://zenodo.org/api/records/123/draft"),
        ("GET", "https://zenodo.org/api/records/123"),
    ]


@patch("changes_metadata_manager.zenodo_api.request_with_retry")
def test_fetches_published_record_without_checking_draft(mock_request):
    published = MagicMock(status_code=200)
    published.json.return_value = {"metadata": {"title": "published"}}
    mock_request.return_value = published

    result = fetch_published_record("https://zenodo.org/api", "123", "token", "agent")

    assert result == {"metadata": {"title": "published"}}
    assert [item.args[:2] for item in mock_request.call_args_list] == [
        ("GET", "https://zenodo.org/api/records/123")
    ]
    assert published.raise_for_status.call_count == 1


@patch("changes_metadata_manager.zenodo_api.request_with_retry")
def test_fetches_latest_published_version(mock_request):
    published = MagicMock(status_code=200)
    published.json.return_value = {"id": "456"}
    mock_request.return_value = published

    result = fetch_latest_published_record(
        "https://zenodo.org/api", "123", "token", "agent"
    )

    assert result == {"id": "456"}
    assert [item.args[:2] for item in mock_request.call_args_list] == [
        ("GET", "https://zenodo.org/api/records/123/versions/latest")
    ]
    assert published.raise_for_status.call_count == 1


@patch("changes_metadata_manager.zenodo_api.request_with_retry")
def test_edit_draft_lifecycle_uses_expected_endpoints(mock_request):
    created = MagicMock(status_code=201)
    created.json.return_value = {"metadata": {"title": "draft"}}
    updated = MagicMock(status_code=200)
    published = MagicMock(status_code=202)
    mock_request.side_effect = [created, updated, published]
    payload: ZenodoUpdatePayload = {
        "access": {"record": "public", "files": "public"},
        "files": {"enabled": True},
        "metadata": {"title": "draft"},
    }

    draft = create_edit_draft("https://zenodo.org/api", "123", "token", "agent")
    update_draft("https://zenodo.org/api", "123", "token", "agent", payload)
    publish_draft("https://zenodo.org/api", "123", "token", "agent")

    assert draft == {"metadata": {"title": "draft"}}
    assert [item.args[:2] for item in mock_request.call_args_list] == [
        ("POST", "https://zenodo.org/api/records/123/draft"),
        ("PUT", "https://zenodo.org/api/records/123/draft"),
        (
            "POST",
            "https://zenodo.org/api/records/123/draft/actions/publish",
        ),
    ]
    assert mock_request.call_args_list[1].kwargs["json"] == payload
    assert created.raise_for_status.call_count == 1
    assert updated.raise_for_status.call_count == 1
    assert published.raise_for_status.call_count == 1


@patch("changes_metadata_manager.zenodo_api.request_with_retry")
def test_create_edit_draft_propagates_http_error(mock_request):
    response = MagicMock(status_code=500)
    response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
    mock_request.return_value = response

    try:
        create_edit_draft("https://zenodo.org/api", "123", "token", "agent")
    except requests.HTTPError as exc:
        assert str(exc) == "500 Server Error"
    else:
        raise AssertionError("HTTP error was not propagated")
