# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import json
import zipfile
from pathlib import Path
from unittest.mock import call, patch

import requests
import yaml
from rdflib import Graph, URIRef

from changes_metadata_manager.folder_metadata_builder import BASE_URI
from changes_metadata_manager.patch.source_notices import (
    NEW_NOTICE_HTML,
    OLD_NOTICE_HTML,
    prepare_source_notice_patches,
)


def _draft(
    tmp_path: Path,
    record_id: int,
    entity_id: str,
    stage: str,
    *,
    content_license: bool = False,
) -> dict:
    archive_path = tmp_path / f"dataset-{entity_id}-{stage}.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(f"S1-{entity_id}-Test/{stage}/meta.ttl", "")
    config_path = tmp_path / f"{record_id}.yaml"
    rights = (
        [
            {
                "title": {"en": "Creative Commons Zero (Content license)"},
                "link": "https://creativecommons.org/publicdomain/zero/1.0/",
            }
        ]
        if content_license
        else []
    )
    config_path.write_text(
        yaml.safe_dump({"files": [str(archive_path)], "rights": rights})
    )
    return {
        "draft_id": record_id,
        "config_file": str(config_path),
        "zenodo_url": "https://zenodo.org/api",
        "access_token": "secret-token",
        "user_agent": "changes-metadata-manager/1.0.0",
        "status": "published",
    }


def _write_drafts(tmp_path: Path, drafts: list[dict]) -> Path:
    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps(drafts))
    return drafts_path


def _record(entity_id: str, stage: str, notice: str) -> dict:
    return {
        "access": {
            "record": "public",
            "files": "public",
            "embargo": {"active": False, "reason": None},
        },
        "files": {
            "enabled": True,
            "order": [],
            "default_preview": None,
            "entries": {f"remote-dataset-{stage}.zip": {"size": 123}},
        },
        "metadata": {
            "title": "Remote title",
            "resource_type": {"id": "dataset", "title": {"en": "Dataset"}},
            "additional_descriptions": [
                {
                    "description": "<p>Remote method.</p>",
                    "type": {"id": "methods", "title": {"en": "Methods"}},
                },
                {
                    "description": notice,
                    "type": {"id": "notes", "title": {"en": "Notes"}},
                },
            ],
            "identifiers": [
                {
                    "identifier": (
                        f"https://w3id.org/changes/4/aldrovandi/itm/{entity_id}/ob00/1"
                    ),
                    "scheme": "url",
                }
            ],
            "publisher": "Zenodo",
        },
    }


def _expected_payload(entity_id: str) -> dict:
    return {
        "access": {"record": "public", "files": "public"},
        "files": {"enabled": True, "order": []},
        "metadata": {
            "title": "Remote title",
            "resource_type": {"id": "dataset"},
            "additional_descriptions": [
                {
                    "description": "<p>Remote method.</p>",
                    "type": {"id": "methods"},
                },
                {
                    "description": NEW_NOTICE_HTML,
                    "type": {"id": "notes"},
                },
            ],
            "identifiers": [
                {
                    "identifier": (
                        f"https://w3id.org/changes/4/aldrovandi/itm/{entity_id}/ob00/1"
                    ),
                    "scheme": "url",
                }
            ],
            "publisher": "Zenodo",
        },
    }


@patch("changes_metadata_manager.patch.source_notices.time.sleep")
@patch("changes_metadata_manager.patch.source_notices.fetch_record")
def test_prepare_selects_from_rdf_and_reuses_cache(mock_fetch, mock_sleep, tmp_path):
    kg = Graph()
    kg.add(
        (
            URIRef(f"{BASE_URI}/act/43/00/1"),
            URIRef("https://example.org/predicate"),
            URIRef("https://example.org/object"),
        )
    )
    drafts_path = _write_drafts(
        tmp_path,
        [
            _draft(tmp_path, 100, "42", "raw"),
            _draft(tmp_path, 101, "43", "raw"),
            _draft(tmp_path, 102, "44", "raw", content_license=True),
        ],
    )
    output_dir = tmp_path / "prepared"
    record = _record("42", "raw", OLD_NOTICE_HTML)
    mock_fetch.return_value = (record, False)

    with patch(
        "changes_metadata_manager.patch.source_notices.load_kg", return_value=kg
    ):
        manifest_path = prepare_source_notice_patches(
            drafts_path, tmp_path / "kg.ttl", output_dir
        )
        second_manifest_path = prepare_source_notice_patches(
            drafts_path, tmp_path / "kg.ttl", output_dir
        )

    expected_manifest = [
        {
            "record_id": 100,
            "entity_ids": ["42"],
            "stage": "raw",
            "status": "would_patch",
            "payload_file": "100.yaml",
        }
    ]
    assert json.loads(manifest_path.read_text()) == expected_manifest
    assert json.loads(second_manifest_path.read_text()) == expected_manifest
    assert yaml.safe_load((output_dir / "100.yaml").read_text()) == _expected_payload(
        "42"
    )
    assert mock_fetch.call_count == 1
    assert mock_sleep.call_args_list == [call(2)]
    assert "secret-token" not in manifest_path.read_text()


@patch("changes_metadata_manager.patch.source_notices.time.sleep")
@patch("changes_metadata_manager.patch.source_notices.fetch_record")
def test_prepare_reports_correct_and_blocked_records(mock_fetch, mock_sleep, tmp_path):
    kg = Graph()
    drafts_path = _write_drafts(
        tmp_path,
        [
            _draft(tmp_path, 100, "42", "raw"),
            _draft(tmp_path, 101, "43", "raw"),
            _draft(tmp_path, 102, "44", "raw"),
        ],
    )
    output_dir = tmp_path / "prepared"
    mock_fetch.side_effect = [
        (_record("42", "raw", NEW_NOTICE_HTML), False),
        (_record("43", "raw", OLD_NOTICE_HTML), True),
        (_record("44", "raw", "<p>Manual remote note.</p>"), False),
    ]

    with patch(
        "changes_metadata_manager.patch.source_notices.load_kg", return_value=kg
    ):
        manifest_path = prepare_source_notice_patches(
            drafts_path, tmp_path / "kg.ttl", output_dir
        )

    assert json.loads(manifest_path.read_text()) == [
        {
            "record_id": 100,
            "entity_ids": ["42"],
            "stage": "raw",
            "status": "already_correct",
        },
        {
            "record_id": 101,
            "entity_ids": ["43"],
            "stage": "raw",
            "status": "blocked",
            "reason": "An edit draft already exists",
        },
        {
            "record_id": 102,
            "entity_ids": ["44"],
            "stage": "raw",
            "status": "blocked",
            "reason": "Expected source notice not found",
        },
    ]
    assert {path.name for path in output_dir.iterdir()} == {"manifest.json"}
    assert mock_sleep.call_args_list == [call(2), call(2), call(2)]


@patch("changes_metadata_manager.patch.source_notices.time.sleep")
@patch("changes_metadata_manager.patch.source_notices.fetch_record")
def test_prepare_records_http_error(mock_fetch, mock_sleep, tmp_path):
    kg = Graph()
    drafts_path = _write_drafts(tmp_path, [_draft(tmp_path, 100, "42", "raw")])
    output_dir = tmp_path / "prepared"
    mock_fetch.side_effect = requests.HTTPError("500 Server Error")

    with patch(
        "changes_metadata_manager.patch.source_notices.load_kg", return_value=kg
    ):
        manifest_path = prepare_source_notice_patches(
            drafts_path, tmp_path / "kg.ttl", output_dir
        )

    assert json.loads(manifest_path.read_text()) == [
        {
            "record_id": 100,
            "entity_ids": ["42"],
            "stage": "raw",
            "status": "error",
            "error": "500 Server Error",
        }
    ]
    assert mock_sleep.call_args_list == [call(2)]
