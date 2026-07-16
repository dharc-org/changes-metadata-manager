# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import json
from copy import deepcopy
from unittest.mock import patch

import requests
from piccione.upload.on_zenodo import text_to_html

from changes_metadata_manager.patch.license_metadata import (
    _current_content_license,
    _has_cc0_disclaimer,
    _rebuild_additional_descriptions,
    patch_drafts,
)
from changes_metadata_manager.zenodo_upload import CC0_DISCLAIMER, build_rights


def _draft(record_id: int, status: str = "published") -> dict:
    return {
        "draft_id": record_id,
        "zenodo_url": "https://zenodo.org/api",
        "access_token": "secret-token",
        "user_agent": "changes-metadata-manager/1.0.0",
        "status": status,
    }


def _write_drafts(tmp_path, entries: list[dict]):
    path = tmp_path / "drafts.json"
    path.write_text(json.dumps(entries))
    return path


def _record(
    content_license: str = "cc-by-nc-4.0",
    *,
    disclaimer: bool = False,
) -> dict:
    additional_descriptions = [
        {
            "description": "<p>Remote method.</p>",
            "type": {"id": "methods", "title": {"en": "Methods"}},
        }
    ]
    if disclaimer:
        additional_descriptions.append(
            {
                "description": text_to_html(CC0_DISCLAIMER),
                "type": {"id": "notes", "title": {"en": "Notes"}},
            }
        )
    return {
        "access": {
            "record": "public",
            "files": "public",
            "embargo": {"active": False, "reason": None},
            "status": "open",
        },
        "files": {
            "enabled": True,
            "order": [],
            "default_preview": None,
            "entries": {"remote-dataset-dcho.zip": {"size": 123}},
            "count": 1,
        },
        "metadata": {
            "title": "Title changed directly on Zenodo",
            "resource_type": {"id": "dataset", "title": {"en": "Dataset"}},
            "creators": [
                {
                    "person_or_org": {
                        "type": "personal",
                        "family_name": "Example",
                        "given_name": "Alice",
                    },
                    "role": {"id": "researcher", "title": {"en": "Researcher"}},
                    "affiliations": [{"name": "Remote institution"}],
                }
            ],
            "publication_date": "2026-05-27",
            "description": "<p>Remote description.</p>",
            "additional_descriptions": additional_descriptions,
            "identifiers": [
                {
                    "identifier": (
                        "https://w3id.org/changes/4/aldrovandi/itm/42/ob00/1"
                    ),
                    "scheme": "url",
                }
            ],
            "rights": build_rights(content_license),
            "publisher": "Zenodo",
        },
        "custom_fields": {"project:code": "CHANGES"},
        "pids": {"doi": {"identifier": "10.5281/zenodo.456"}},
    }


def _expected_cc0_payload() -> dict:
    return {
        "access": {
            "record": "public",
            "files": "public",
        },
        "files": {"enabled": True, "order": []},
        "metadata": {
            "title": "Title changed directly on Zenodo",
            "resource_type": {"id": "dataset"},
            "creators": [
                {
                    "person_or_org": {
                        "type": "personal",
                        "family_name": "Example",
                        "given_name": "Alice",
                    },
                    "role": {"id": "researcher"},
                    "affiliations": [{"name": "Remote institution"}],
                }
            ],
            "publication_date": "2026-05-27",
            "description": "<p>Remote description.</p>",
            "additional_descriptions": [
                {
                    "description": "<p>Remote method.</p>",
                    "type": {"id": "methods"},
                },
                {
                    "description": text_to_html(CC0_DISCLAIMER),
                    "type": {"id": "notes"},
                },
            ],
            "identifiers": [
                {
                    "identifier": (
                        "https://w3id.org/changes/4/aldrovandi/itm/42/ob00/1"
                    ),
                    "scheme": "url",
                }
            ],
            "rights": build_rights("cc0-1.0"),
            "publisher": "Zenodo",
        },
        "custom_fields": {"project:code": "CHANGES"},
    }


def test_detects_content_license_and_disclaimer():
    metadata = _record("cc-by-nc-4.0")["metadata"]
    assert _current_content_license(metadata) == "cc-by-nc-4.0"
    assert _has_cc0_disclaimer(metadata) is False

    cc0_metadata = _record("cc0-1.0", disclaimer=True)["metadata"]
    assert _current_content_license(cc0_metadata) == "cc0-1.0"
    assert _has_cc0_disclaimer(cc0_metadata) is True


def test_rebuilds_additional_descriptions_exactly():
    current = [
        {"description": "<p>Remote note.</p>", "type": {"id": "notes"}},
        {"description": "Ai sensi del D. Lgs. 42/2004...", "type": {"id": "notes"}},
    ]
    assert _rebuild_additional_descriptions(current, "cc0-1.0") == [
        {"description": "<p>Remote note.</p>", "type": {"id": "notes"}},
        {
            "description": text_to_html(CC0_DISCLAIMER),
            "type": {"id": "notes"},
        },
    ]
    assert _rebuild_additional_descriptions(current, "cc-by-nc-4.0") == [
        {"description": "<p>Remote note.</p>", "type": {"id": "notes"}}
    ]


@patch("changes_metadata_manager.patch.license_metadata.time.sleep")
@patch("changes_metadata_manager.patch.license_metadata.publish_draft")
@patch("changes_metadata_manager.patch.license_metadata.update_draft")
@patch("changes_metadata_manager.patch.license_metadata.create_edit_draft")
@patch(
    "changes_metadata_manager.patch.license_metadata.extract_license_for_entity_stage"
)
@patch("changes_metadata_manager.patch.license_metadata.fetch_record")
def test_dry_run_uses_remote_record_without_local_config(
    mock_fetch,
    mock_extract,
    mock_create,
    mock_update,
    mock_publish,
    mock_sleep,
    tmp_path,
):
    drafts_path = _write_drafts(tmp_path, [_draft(123)])
    mock_fetch.return_value = (_record(), False)
    mock_extract.return_value = "cc0-1.0"

    with patch("changes_metadata_manager.patch.license_metadata.load_kg"):
        patch_drafts(drafts_path, tmp_path / "kg.ttl", dry_run=True)

    assert json.loads((tmp_path / "patch_license_log.json").read_text()) == [
        {
            "record_id": 123,
            "entity_id": "42",
            "stage": "dcho",
            "old_license": "cc-by-nc-4.0",
            "new_license": "cc0-1.0",
            "rights_changed": True,
            "disclaimer_changed": True,
            "status": "dry_run",
        }
    ]
    mock_create.assert_not_called()
    mock_update.assert_not_called()
    mock_publish.assert_not_called()


@patch("changes_metadata_manager.patch.license_metadata.time.sleep")
@patch("changes_metadata_manager.patch.license_metadata.publish_draft")
@patch("changes_metadata_manager.patch.license_metadata.update_draft")
@patch("changes_metadata_manager.patch.license_metadata.create_edit_draft")
@patch(
    "changes_metadata_manager.patch.license_metadata.extract_license_for_entity_stage"
)
@patch("changes_metadata_manager.patch.license_metadata.fetch_record")
def test_published_record_updates_only_remote_license_fields(
    mock_fetch,
    mock_extract,
    mock_create,
    mock_update,
    mock_publish,
    mock_sleep,
    tmp_path,
):
    drafts_path = _write_drafts(tmp_path, [_draft(456)])
    record = _record()
    mock_fetch.return_value = (record, False)
    mock_extract.return_value = "cc0-1.0"
    mock_create.return_value = deepcopy(record)

    with patch("changes_metadata_manager.patch.license_metadata.load_kg"):
        patch_drafts(drafts_path, tmp_path / "kg.ttl")

    mock_create.assert_called_once_with(
        "https://zenodo.org/api",
        "456",
        "secret-token",
        "changes-metadata-manager/1.0.0",
    )
    mock_update.assert_called_once_with(
        "https://zenodo.org/api",
        "456",
        "secret-token",
        "changes-metadata-manager/1.0.0",
        _expected_cc0_payload(),
    )
    mock_publish.assert_called_once_with(
        "https://zenodo.org/api",
        "456",
        "secret-token",
        "changes-metadata-manager/1.0.0",
    )
    assert json.loads((tmp_path / "patch_license_log.json").read_text()) == [
        {
            "record_id": 456,
            "entity_id": "42",
            "stage": "dcho",
            "old_license": "cc-by-nc-4.0",
            "new_license": "cc0-1.0",
            "rights_changed": True,
            "disclaimer_changed": True,
            "status": "patched",
        }
    ]


@patch("changes_metadata_manager.patch.license_metadata.time.sleep")
@patch("changes_metadata_manager.patch.license_metadata.publish_draft")
@patch("changes_metadata_manager.patch.license_metadata.update_draft")
@patch("changes_metadata_manager.patch.license_metadata.create_edit_draft")
@patch(
    "changes_metadata_manager.patch.license_metadata.extract_license_for_entity_stage"
)
@patch("changes_metadata_manager.patch.license_metadata.fetch_record")
def test_unpublished_record_updates_existing_draft_without_publishing(
    mock_fetch,
    mock_extract,
    mock_create,
    mock_update,
    mock_publish,
    mock_sleep,
    tmp_path,
):
    drafts_path = _write_drafts(tmp_path, [_draft(789, "uploaded")])
    record = _record()
    mock_fetch.return_value = (record, True)
    mock_extract.return_value = "cc0-1.0"

    with patch("changes_metadata_manager.patch.license_metadata.load_kg"):
        patch_drafts(drafts_path, tmp_path / "kg.ttl")

    mock_update.assert_called_once_with(
        "https://zenodo.org/api",
        "789",
        "secret-token",
        "changes-metadata-manager/1.0.0",
        _expected_cc0_payload(),
    )
    mock_create.assert_not_called()
    mock_publish.assert_not_called()


@patch("changes_metadata_manager.patch.license_metadata.time.sleep")
@patch("changes_metadata_manager.patch.license_metadata.publish_draft")
@patch("changes_metadata_manager.patch.license_metadata.update_draft")
@patch("changes_metadata_manager.patch.license_metadata.create_edit_draft")
@patch(
    "changes_metadata_manager.patch.license_metadata.extract_license_for_entity_stage"
)
@patch("changes_metadata_manager.patch.license_metadata.fetch_record")
def test_blocks_existing_edit_draft_for_published_record(
    mock_fetch,
    mock_extract,
    mock_create,
    mock_update,
    mock_publish,
    mock_sleep,
    tmp_path,
):
    drafts_path = _write_drafts(tmp_path, [_draft(456)])
    mock_fetch.return_value = (_record(), True)
    mock_extract.return_value = "cc0-1.0"

    with patch("changes_metadata_manager.patch.license_metadata.load_kg"):
        patch_drafts(drafts_path, tmp_path / "kg.ttl")

    assert json.loads((tmp_path / "patch_license_log.json").read_text()) == [
        {
            "record_id": 456,
            "entity_id": "42",
            "stage": "dcho",
            "old_license": "cc-by-nc-4.0",
            "new_license": "cc0-1.0",
            "rights_changed": True,
            "disclaimer_changed": True,
            "status": "blocked",
            "reason": "An edit draft already exists",
        }
    ]
    mock_create.assert_not_called()
    mock_update.assert_not_called()
    mock_publish.assert_not_called()


@patch("changes_metadata_manager.patch.license_metadata.time.sleep")
@patch(
    "changes_metadata_manager.patch.license_metadata.extract_license_for_entity_stage"
)
@patch("changes_metadata_manager.patch.license_metadata.fetch_record")
def test_skips_already_correct_record(mock_fetch, mock_extract, mock_sleep, tmp_path):
    drafts_path = _write_drafts(tmp_path, [_draft(111)])
    mock_fetch.return_value = (_record("cc0-1.0", disclaimer=True), False)
    mock_extract.return_value = "cc0-1.0"

    with patch("changes_metadata_manager.patch.license_metadata.load_kg"):
        patch_drafts(drafts_path, tmp_path / "kg.ttl", dry_run=True)

    assert json.loads((tmp_path / "patch_license_log.json").read_text()) == []


@patch("changes_metadata_manager.patch.license_metadata.time.sleep")
@patch("changes_metadata_manager.patch.license_metadata.fetch_record")
def test_logs_http_error_without_credentials(mock_fetch, mock_sleep, tmp_path):
    drafts_path = _write_drafts(tmp_path, [_draft(999)])
    mock_fetch.side_effect = requests.HTTPError("500 Server Error")

    with patch("changes_metadata_manager.patch.license_metadata.load_kg"):
        patch_drafts(drafts_path, tmp_path / "kg.ttl")

    log_text = (tmp_path / "patch_license_log.json").read_text()
    assert json.loads(log_text) == [
        {
            "record_id": 999,
            "status": "error",
            "error": "500 Server Error",
        }
    ]
    assert "secret-token" not in log_text
