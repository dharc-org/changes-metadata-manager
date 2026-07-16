# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from changes_metadata_manager.folder_metadata_builder import load_kg
from changes_metadata_manager.patch.creator_names import patch_creator_names

DATA_DIR = Path(__file__).parent.parent / "data"


def _creator(
    family_name: str,
    given_name: str,
    orcid: str,
    role: str,
    affiliation: str,
) -> dict:
    return {
        "person_or_org": {
            "type": "personal",
            "family_name": family_name,
            "given_name": given_name,
            "identifiers": [{"scheme": "orcid", "identifier": orcid}],
        },
        "role": {"id": role},
        "affiliations": [{"name": affiliation}],
    }


UNIBO = "Alma Mater Studiorum - Università di Bologna"
CNR = "Consiglio Nazionale delle Ricerche"
METADATA_CREATORS = [
    _creator("Massari", "Arcangelo", "0000-0002-8420-0696", "datacurator", UNIBO),
    _creator("Moretti", "Arianna", "0000-0001-5486-7070", "datacurator", UNIBO),
    _creator("Barzaghi", "Sebastian", "0000-0002-0799-1527", "datacurator", UNIBO),
]
VALENTINA = _creator(
    "Girelli", "Valentina Alena", "0000-0001-9257-9803", "researcher", UNIBO
)
ALICE = _creator("Bordignon", "Alice", "0009-0008-3556-0493", "researcher", UNIBO)
FEDERICA = _creator("Giacomini", "Federica", "0009-0002-5840-2769", "researcher", UNIBO)
FRANCESCA = _creator("Fabbri", "Francesca", "0000-0003-4923-9875", "researcher", UNIBO)
MARIA = _creator("Rega", "Maria Felicia", "0000-0001-8404-1640", "researcher", CNR)
RACHELE = _creator(
    "Manganelli Del Fà",
    "Rachele",
    "0000-0002-4767-5684",
    "researcher",
    CNR,
)


@pytest.fixture(scope="module")
def real_kg():
    return load_kg(DATA_DIR / "kg.ttl")


def _draft(record_id: int, status: str = "published") -> dict:
    return {
        "draft_id": record_id,
        "zenodo_url": "https://zenodo.org/api",
        "access_token": "secret-token",
        "user_agent": "changes-metadata-manager/1.0.0",
        "status": status,
    }


def _write_drafts(tmp_path: Path, drafts: list[dict]) -> Path:
    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps(drafts))
    return drafts_path


def _expanded_creators(creators: list[dict]) -> list[dict]:
    expanded = deepcopy(creators)
    for creator in expanded:
        person = creator["person_or_org"]
        person["name"] = f"{person['family_name']}, {person['given_name']}"
        creator["role"]["title"] = {"en": creator["role"]["id"]}
        creator["affiliations"][0]["id"] = "01ggx4157"
    return expanded


def _record(entity_id: str, stage: str, creators: list[dict]) -> dict:
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
            "count": 1,
            "entries": {f"remote-dataset-{stage}.zip": {"size": 123}},
        },
        "metadata": {
            "title": "Title changed directly on Zenodo",
            "resource_type": {"id": "dataset", "title": {"en": "Dataset"}},
            "creators": _expanded_creators(creators),
            "publication_date": "2026-05-27",
            "description": '<p>Remote <a href="https://example.org">HTML</a>.</p>',
            "additional_descriptions": [
                {
                    "description": "<p>Remote method.</p>",
                    "type": {"id": "methods", "title": {"en": "Methods"}},
                }
            ],
            "identifiers": [
                {
                    "identifier": (
                        f"https://w3id.org/changes/4/aldrovandi/itm/{entity_id}/ob00/1"
                    ),
                    "scheme": "url",
                }
            ],
            "related_identifiers": [
                {
                    "identifier": "10.1234/example",
                    "scheme": "doi",
                    "relation_type": {
                        "id": "isdocumentedby",
                        "title": {"en": "Is documented by"},
                    },
                    "resource_type": {
                        "id": "publication-article",
                        "title": {"en": "Journal article"},
                    },
                }
            ],
            "rights": [
                {
                    "title": {"en": "Remote right"},
                    "link": "https://example.org/right",
                }
            ],
            "publisher": "Zenodo",
        },
        "custom_fields": {"project:code": "CHANGES"},
        "id": "server-owned-id",
        "pids": {"doi": {"identifier": "10.5281/zenodo.1"}},
    }


def _expected_payload(expected_creators: list[dict]) -> dict:
    return {
        "access": {
            "record": "public",
            "files": "public",
        },
        "files": {"enabled": True, "order": []},
        "metadata": {
            "title": "Title changed directly on Zenodo",
            "resource_type": {"id": "dataset"},
            "creators": expected_creators,
            "publication_date": "2026-05-27",
            "description": '<p>Remote <a href="https://example.org">HTML</a>.</p>',
            "additional_descriptions": [
                {
                    "description": "<p>Remote method.</p>",
                    "type": {"id": "methods"},
                }
            ],
            "identifiers": [
                {
                    "identifier": (
                        "https://w3id.org/changes/4/aldrovandi/itm/40/ob00/1"
                    ),
                    "scheme": "url",
                }
            ],
            "related_identifiers": [
                {
                    "identifier": "10.1234/example",
                    "scheme": "doi",
                    "relation_type": {"id": "isdocumentedby"},
                    "resource_type": {"id": "publication-article"},
                }
            ],
            "rights": [
                {
                    "title": {"en": "Remote right"},
                    "link": "https://example.org/right",
                }
            ],
            "publisher": "Zenodo",
        },
        "custom_fields": {"project:code": "CHANGES"},
    }


@patch("changes_metadata_manager.patch.creator_names.time.sleep")
@patch("changes_metadata_manager.patch.creator_names.publish_draft")
@patch("changes_metadata_manager.patch.creator_names.update_draft")
@patch("changes_metadata_manager.patch.creator_names.create_edit_draft")
@patch("changes_metadata_manager.patch.creator_names.fetch_record")
def test_audit_uses_remote_record_without_local_config(
    mock_fetch,
    mock_create,
    mock_update,
    mock_publish,
    mock_sleep,
    tmp_path,
    real_kg,
):
    drafts_path = _write_drafts(tmp_path, [_draft(20420559)])
    mock_fetch.return_value = (_record("40", "raw", METADATA_CREATORS), False)

    with patch(
        "changes_metadata_manager.patch.creator_names.load_kg", return_value=real_kg
    ):
        log_path = patch_creator_names(drafts_path, DATA_DIR / "kg.ttl")

    assert json.loads(log_path.read_text()) == [
        {
            "record_id": 20420559,
            "entity_ids": ["40"],
            "stage": "raw",
            "missing_creators": [
                {
                    "name": "Valentina Alena Girelli",
                    "orcid": "0000-0001-9257-9803",
                }
            ],
            "status": "would_patch",
        }
    ]
    mock_create.assert_not_called()
    mock_update.assert_not_called()
    mock_publish.assert_not_called()


@patch("changes_metadata_manager.patch.creator_names.time.sleep")
@patch("changes_metadata_manager.patch.creator_names.publish_draft")
@patch("changes_metadata_manager.patch.creator_names.update_draft")
@patch("changes_metadata_manager.patch.creator_names.create_edit_draft")
@patch("changes_metadata_manager.patch.creator_names.fetch_record")
def test_apply_builds_payload_from_created_remote_draft(
    mock_fetch,
    mock_create,
    mock_update,
    mock_publish,
    mock_sleep,
    tmp_path,
    real_kg,
):
    drafts_path = _write_drafts(tmp_path, [_draft(20420559)])
    record = _record("40", "raw", METADATA_CREATORS)
    mock_fetch.return_value = (record, False)
    mock_create.return_value = deepcopy(record)
    expected_creators = [VALENTINA, *METADATA_CREATORS]

    with patch(
        "changes_metadata_manager.patch.creator_names.load_kg", return_value=real_kg
    ):
        log_path = patch_creator_names(drafts_path, DATA_DIR / "kg.ttl", apply=True)

    mock_create.assert_called_once_with(
        "https://zenodo.org/api",
        "20420559",
        "secret-token",
        "changes-metadata-manager/1.0.0",
    )
    mock_update.assert_called_once_with(
        "https://zenodo.org/api",
        "20420559",
        "secret-token",
        "changes-metadata-manager/1.0.0",
        _expected_payload(expected_creators),
    )
    mock_publish.assert_called_once_with(
        "https://zenodo.org/api",
        "20420559",
        "secret-token",
        "changes-metadata-manager/1.0.0",
    )
    assert json.loads(log_path.read_text()) == [
        {
            "record_id": 20420559,
            "entity_ids": ["40"],
            "stage": "raw",
            "missing_creators": [
                {
                    "name": "Valentina Alena Girelli",
                    "orcid": "0000-0001-9257-9803",
                }
            ],
            "status": "patched",
        }
    ]


@patch("changes_metadata_manager.patch.creator_names.time.sleep")
@patch("changes_metadata_manager.patch.creator_names.fetch_record")
def test_grouped_entities_are_reconstructed_from_remote_id_and_kg(
    mock_fetch, mock_sleep, tmp_path, real_kg
):
    current_creators = [
        ALICE,
        FEDERICA,
        FRANCESCA,
        MARIA,
        *METADATA_CREATORS,
    ]
    drafts_path = _write_drafts(tmp_path, [_draft(20437073)])
    mock_fetch.return_value = (
        _record("74a", "dchoo", current_creators),
        False,
    )

    with patch(
        "changes_metadata_manager.patch.creator_names.load_kg", return_value=real_kg
    ):
        log_path = patch_creator_names(drafts_path, DATA_DIR / "kg.ttl")

    assert json.loads(log_path.read_text()) == [
        {
            "record_id": 20437073,
            "entity_ids": ["74a", "74b", "74c", "74d", "74e"],
            "stage": "dchoo",
            "missing_creators": [
                {
                    "name": "Rachele Manganelli Del Fà",
                    "orcid": "0000-0002-4767-5684",
                }
            ],
            "status": "would_patch",
        }
    ]


@patch("changes_metadata_manager.patch.creator_names.time.sleep")
@patch("changes_metadata_manager.patch.creator_names.publish_draft")
@patch("changes_metadata_manager.patch.creator_names.update_draft")
@patch("changes_metadata_manager.patch.creator_names.create_edit_draft")
@patch("changes_metadata_manager.patch.creator_names.fetch_record")
def test_blocks_existing_draft_and_unrelated_creator_difference(
    mock_fetch,
    mock_create,
    mock_update,
    mock_publish,
    mock_sleep,
    tmp_path,
    real_kg,
):
    unrelated_creators = deepcopy(METADATA_CREATORS)
    unrelated_creators[0]["role"]["id"] = "researcher"
    drafts_path = _write_drafts(
        tmp_path,
        [_draft(20420559), _draft(20436931)],
    )
    mock_fetch.side_effect = [
        (_record("40", "raw", METADATA_CREATORS), True),
        (_record("105", "raw", unrelated_creators), False),
    ]

    with patch(
        "changes_metadata_manager.patch.creator_names.load_kg", return_value=real_kg
    ):
        log_path = patch_creator_names(drafts_path, DATA_DIR / "kg.ttl", apply=True)

    assert json.loads(log_path.read_text()) == [
        {
            "record_id": 20420559,
            "entity_ids": ["40"],
            "stage": "raw",
            "missing_creators": [
                {
                    "name": "Valentina Alena Girelli",
                    "orcid": "0000-0001-9257-9803",
                }
            ],
            "status": "blocked",
            "reason": "An edit draft already exists",
        },
        {
            "record_id": 20436931,
            "entity_ids": ["105"],
            "stage": "raw",
            "missing_creators": [
                {
                    "name": "Rachele Manganelli Del Fà",
                    "orcid": "0000-0002-4767-5684",
                }
            ],
            "status": "blocked",
            "reason": "Creator differences are not limited to missing creators",
        },
    ]
    mock_create.assert_not_called()
    mock_update.assert_not_called()
    mock_publish.assert_not_called()


@patch("changes_metadata_manager.patch.creator_names.time.sleep")
@patch("changes_metadata_manager.patch.creator_names.fetch_record")
def test_reports_already_correct_remote_record(
    mock_fetch, mock_sleep, tmp_path, real_kg
):
    drafts_path = _write_drafts(tmp_path, [_draft(20420559)])
    expected_creators = [VALENTINA, *METADATA_CREATORS]
    mock_fetch.return_value = (
        _record("40", "raw", expected_creators),
        False,
    )

    with patch(
        "changes_metadata_manager.patch.creator_names.load_kg", return_value=real_kg
    ):
        log_path = patch_creator_names(drafts_path, DATA_DIR / "kg.ttl")

    assert json.loads(log_path.read_text()) == [
        {
            "record_id": 20420559,
            "entity_ids": ["40"],
            "stage": "raw",
            "missing_creators": [],
            "status": "already_correct",
        }
    ]


@patch("changes_metadata_manager.patch.creator_names.time.sleep")
@patch("changes_metadata_manager.patch.creator_names.fetch_record")
def test_logs_http_error_without_credentials(mock_fetch, mock_sleep, tmp_path, real_kg):
    drafts_path = _write_drafts(tmp_path, [_draft(20420559)])
    mock_fetch.side_effect = requests.HTTPError("500 Server Error")

    with patch(
        "changes_metadata_manager.patch.creator_names.load_kg", return_value=real_kg
    ):
        log_path = patch_creator_names(drafts_path, DATA_DIR / "kg.ttl")

    assert json.loads(log_path.read_text()) == [
        {
            "record_id": 20420559,
            "status": "error",
            "error": "500 Server Error",
        }
    ]
    assert "secret-token" not in log_path.read_text()
