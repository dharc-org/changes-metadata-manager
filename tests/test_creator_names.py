# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import json
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import call, patch

import pytest
import requests
import yaml
from rdflib import Graph

from changes_metadata_manager.folder_metadata_builder import load_kg
from changes_metadata_manager.patch.creator_names import (
    CACHE_FILENAME,
    MANIFEST_FILENAME,
    apply_creator_name_patches,
    prepare_creator_name_patches,
)
from changes_metadata_manager.zenodo_api import ZenodoRecordCache

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


def _draft(
    record_id: int,
    status: str = "published",
    folder_names: tuple[str, ...] = ("S1-40-Test",),
) -> dict:
    return {
        "draft_id": record_id,
        "zenodo_url": "https://zenodo.org/api",
        "access_token": "secret-token",
        "user_agent": "changes-metadata-manager/1.0.0",
        "status": status,
        "folder_names": folder_names,
    }


def _write_drafts(tmp_path: Path, drafts: list[dict]) -> Path:
    serialized_drafts = []
    for source_draft in drafts:
        draft = dict(source_draft)
        folder_names = draft.pop("folder_names")
        zip_path = tmp_path / f"{draft['draft_id']}.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            for folder_name in folder_names:
                archive.writestr(f"{folder_name}/raw/meta.ttl", "")
        config_path = tmp_path / f"{draft['draft_id']}.yaml"
        config_path.write_text(yaml.safe_dump({"files": [str(zip_path)]}))
        draft["config_file"] = str(config_path)
        serialized_drafts.append(draft)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps(serialized_drafts))
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


def _run_prepare(drafts_path: Path, output_dir: Path, real_kg: Graph) -> Path:
    with patch(
        "changes_metadata_manager.patch.creator_names.load_kg", return_value=real_kg
    ):
        return prepare_creator_name_patches(
            drafts_path, DATA_DIR / "kg.ttl", output_dir
        )


@patch("changes_metadata_manager.patch.creator_names.time.sleep")
@patch("changes_metadata_manager.patch.creator_names.fetch_record")
def test_prepare_writes_payload_manifest_and_reuses_cache(
    mock_fetch, mock_sleep, tmp_path, real_kg
):
    drafts_path = _write_drafts(tmp_path, [_draft(20420559)])
    output_dir = tmp_path / "prepared"
    record = _record("40", "raw", METADATA_CREATORS)
    mock_fetch.return_value = (record, False)
    expected_creators = [VALENTINA, *METADATA_CREATORS]
    expected_manifest = [
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
            "payload_file": "20420559.yaml",
        }
    ]

    manifest_path = _run_prepare(drafts_path, output_dir, real_kg)

    assert json.loads(manifest_path.read_text()) == expected_manifest
    assert yaml.safe_load((output_dir / "20420559.yaml").read_text()) == (
        _expected_payload(expected_creators)
    )
    assert {path.name for path in output_dir.iterdir()} == {
        MANIFEST_FILENAME,
        "20420559.yaml",
    }
    assert "secret-token" not in manifest_path.read_text()
    assert "secret-token" not in (output_dir / "20420559.yaml").read_text()

    second_manifest_path = _run_prepare(drafts_path, output_dir, real_kg)

    assert json.loads(second_manifest_path.read_text()) == expected_manifest
    assert mock_fetch.call_count == 1
    assert mock_sleep.call_args_list == [call(2)]


@patch("changes_metadata_manager.patch.creator_names.time.sleep")
@patch("changes_metadata_manager.patch.prepared_updates.publish_draft")
@patch("changes_metadata_manager.patch.prepared_updates.update_draft")
@patch("changes_metadata_manager.patch.prepared_updates.create_edit_draft")
@patch("changes_metadata_manager.patch.creator_names.fetch_record")
def test_apply_uses_prepared_payload_without_refetching(
    mock_fetch,
    mock_create,
    mock_update,
    mock_publish,
    mock_sleep,
    tmp_path,
    real_kg,
):
    drafts_path = _write_drafts(tmp_path, [_draft(20420559)])
    output_dir = tmp_path / "prepared"
    record = _record("40", "raw", METADATA_CREATORS)
    mock_fetch.return_value = (record, False)
    expected_payload = _expected_payload([VALENTINA, *METADATA_CREATORS])
    _run_prepare(drafts_path, output_dir, real_kg)

    with ZenodoRecordCache(tmp_path / CACHE_FILENAME) as cache:
        assert cache.get("https://zenodo.org/api", "20420559") == (record, False)

    log_path = apply_creator_name_patches(drafts_path, output_dir)

    mock_fetch.assert_called_once()
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
        expected_payload,
    )
    mock_publish.assert_called_once_with(
        "https://zenodo.org/api",
        "20420559",
        "secret-token",
        "changes-metadata-manager/1.0.0",
    )
    assert json.loads(log_path.read_text()) == [
        {"record_id": 20420559, "status": "patched"}
    ]
    with ZenodoRecordCache(tmp_path / CACHE_FILENAME) as cache:
        assert cache.get("https://zenodo.org/api", "20420559") is None

    apply_creator_name_patches(drafts_path, output_dir)

    assert mock_create.call_count == 1
    assert mock_update.call_count == 1
    assert mock_publish.call_count == 1
    assert mock_sleep.call_args_list == [call(2), call(2)]


@patch("changes_metadata_manager.patch.creator_names.time.sleep")
@patch("changes_metadata_manager.patch.creator_names.fetch_record")
def test_prepare_uses_entity_ids_from_uploaded_zip(
    mock_fetch, mock_sleep, tmp_path, real_kg
):
    current_creators = [
        ALICE,
        FEDERICA,
        FRANCESCA,
        MARIA,
        *METADATA_CREATORS,
    ]
    drafts_path = _write_drafts(
        tmp_path,
        [
            _draft(
                20437073,
                folder_names=(
                    "S6-74a-ISPC_Linum_usitatissimum_L",
                    "S6-74b-ISPC-Orchis_morio_L",
                    "S6-74c-DBC_ButomusUmbellatusL",
                    "S6-74d-ISPC_Daphne_mezereum_L",
                    "S6-74e-ISPC_Primula_veris_L",
                ),
            )
        ],
    )
    output_dir = tmp_path / "prepared"
    mock_fetch.return_value = (
        _record("74a", "dchoo", current_creators),
        False,
    )

    manifest_path = _run_prepare(drafts_path, output_dir, real_kg)

    assert json.loads(manifest_path.read_text()) == [
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
            "payload_file": "20437073.yaml",
        }
    ]
    expected_payload = _expected_payload(
        [ALICE, FEDERICA, FRANCESCA, MARIA, RACHELE, *METADATA_CREATORS]
    )
    expected_payload["metadata"]["identifiers"] = [
        {
            "identifier": ("https://w3id.org/changes/4/aldrovandi/itm/74a/ob00/1"),
            "scheme": "url",
        }
    ]
    assert yaml.safe_load((output_dir / "20437073.yaml").read_text()) == (
        expected_payload
    )


@patch("changes_metadata_manager.patch.creator_names.time.sleep")
@patch("changes_metadata_manager.patch.creator_names.fetch_record")
def test_prepare_reports_blocked_and_correct_records(
    mock_fetch, mock_sleep, tmp_path, real_kg
):
    unrelated_creators = deepcopy(METADATA_CREATORS)
    unrelated_creators[0]["role"]["id"] = "researcher"
    expected_creators = [VALENTINA, *METADATA_CREATORS]
    drafts_path = _write_drafts(
        tmp_path,
        [
            _draft(20420559),
            _draft(20436931, folder_names=("S6-105-Test",)),
            _draft(20420560),
        ],
    )
    output_dir = tmp_path / "prepared"
    mock_fetch.side_effect = [
        (_record("40", "raw", METADATA_CREATORS), True),
        (_record("105", "raw", unrelated_creators), False),
        (_record("40", "raw", expected_creators), False),
    ]

    manifest_path = _run_prepare(drafts_path, output_dir, real_kg)

    assert json.loads(manifest_path.read_text()) == [
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
        {
            "record_id": 20420560,
            "entity_ids": ["40"],
            "stage": "raw",
            "missing_creators": [],
            "status": "already_correct",
        },
    ]
    assert {path.name for path in output_dir.iterdir()} == {MANIFEST_FILENAME}


@patch("changes_metadata_manager.patch.creator_names.time.sleep")
@patch("changes_metadata_manager.patch.creator_names.fetch_record")
def test_prepare_does_not_cache_http_errors(mock_fetch, mock_sleep, tmp_path, real_kg):
    drafts_path = _write_drafts(tmp_path, [_draft(20420559)])
    output_dir = tmp_path / "prepared"
    mock_fetch.side_effect = requests.HTTPError("500 Server Error")

    manifest_path = _run_prepare(drafts_path, output_dir, real_kg)
    second_manifest_path = _run_prepare(drafts_path, output_dir, real_kg)

    expected_manifest = [
        {
            "record_id": 20420559,
            "status": "error",
            "error": "500 Server Error",
        }
    ]
    assert json.loads(manifest_path.read_text()) == expected_manifest
    assert json.loads(second_manifest_path.read_text()) == expected_manifest
    assert mock_fetch.call_count == 2
    assert mock_sleep.call_args_list == [call(2), call(2)]
    assert "secret-token" not in second_manifest_path.read_text()


def test_prepare_rejects_unmanaged_output_files(tmp_path):
    drafts_path = _write_drafts(tmp_path, [_draft(20420559)])
    output_dir = tmp_path / "prepared"
    output_dir.mkdir()
    unrelated_path = output_dir / "notes.txt"
    unrelated_path.write_text("keep me")

    with pytest.raises(ValueError, match="Output directory contains unmanaged files"):
        prepare_creator_name_patches(drafts_path, DATA_DIR / "kg.ttl", output_dir)

    assert unrelated_path.read_text() == "keep me"


@patch("changes_metadata_manager.patch.creator_names.time.sleep")
@patch("changes_metadata_manager.patch.prepared_updates.publish_draft")
@patch("changes_metadata_manager.patch.prepared_updates.update_draft")
@patch("changes_metadata_manager.patch.prepared_updates.create_edit_draft")
def test_apply_logs_errors_and_continues(
    mock_create, mock_update, mock_publish, mock_sleep, tmp_path
):
    drafts_path = _write_drafts(tmp_path, [_draft(20420559), _draft(20436931)])
    output_dir = tmp_path / "prepared"
    output_dir.mkdir()
    payload = _expected_payload([VALENTINA, *METADATA_CREATORS])
    manifest = [
        {
            "record_id": 20420559,
            "status": "would_patch",
            "payload_file": "20420559.yaml",
        },
        {
            "record_id": 20436931,
            "status": "would_patch",
            "payload_file": "20436931.yaml",
        },
    ]
    (output_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest))
    for entry in manifest:
        (output_dir / entry["payload_file"]).write_text(
            yaml.safe_dump(payload, sort_keys=False)
        )
    with ZenodoRecordCache(tmp_path / CACHE_FILENAME) as cache:
        cache.set("https://zenodo.org/api", "20420559", {"id": 1}, False)
        cache.set("https://zenodo.org/api", "20436931", {"id": 2}, False)
    mock_create.side_effect = [requests.HTTPError("500 Server Error"), {}]

    log_path = apply_creator_name_patches(drafts_path, output_dir)

    assert json.loads(log_path.read_text()) == [
        {
            "record_id": 20420559,
            "status": "error",
            "error": "500 Server Error",
        },
        {"record_id": 20436931, "status": "patched"},
    ]
    assert mock_create.call_count == 2
    mock_update.assert_called_once_with(
        "https://zenodo.org/api",
        "20436931",
        "secret-token",
        "changes-metadata-manager/1.0.0",
        payload,
    )
    mock_publish.assert_called_once_with(
        "https://zenodo.org/api",
        "20436931",
        "secret-token",
        "changes-metadata-manager/1.0.0",
    )
    assert mock_sleep.call_args_list == [call(2), call(2)]
    with ZenodoRecordCache(tmp_path / CACHE_FILENAME) as cache:
        assert cache.get("https://zenodo.org/api", "20420559") is None
        assert cache.get("https://zenodo.org/api", "20436931") is None
    assert "secret-token" not in log_path.read_text()

    apply_creator_name_patches(drafts_path, output_dir)

    assert mock_create.call_count == 2
    assert mock_update.call_count == 1
    assert mock_publish.call_count == 1
