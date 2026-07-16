# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

from unittest.mock import MagicMock, call, patch

import requests

from changes_metadata_manager.zenodo_api import (
    MAX_RETRIES,
    create_edit_draft,
    fetch_record,
    publish_draft,
    request_with_retry,
    update_draft,
)
from changes_metadata_manager.zenodo_metadata import ZenodoUpdatePayload


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
