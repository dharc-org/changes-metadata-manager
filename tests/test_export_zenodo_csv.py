# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import json
from unittest.mock import call, patch

import pytest
import requests

from changes_metadata_manager.export_zenodo_csv import export_zenodo_csv


def _draft(record_id: str) -> dict:
    return {
        "draft_id": record_id,
        "config_file": "/missing/stale-config.yaml",
        "title": "Stale local title",
        "zenodo_url": "https://zenodo.org/api",
        "access_token": "token",
        "user_agent": "agent",
        "status": "published",
        "doi": "stale-doi",
        "record_url": "stale-url",
    }


def _record(record_id: str, title: str, creators: list[dict]) -> dict:
    return {
        "metadata": {
            "title": title,
            "publication_date": "2026-07-17",
            "publisher": "Zenodo",
            "resource_type": {"id": "dataset", "title": {"en": "Dataset"}},
            "creators": creators,
            "rights": [
                {
                    "title": {
                        "en": "Creative Commons Zero v1.0 Universal (Metadata license)"
                    },
                    "link": ("https://creativecommons.org/publicdomain/zero/1.0/"),
                },
                {
                    "title": {
                        "en": "Creative Commons Attribution 4.0 International "
                        "(Content license)"
                    },
                    "link": "https://creativecommons.org/licenses/by/4.0/",
                },
            ],
        },
        "pids": {"doi": {"identifier": f"10.5281/zenodo.{record_id}"}},
        "links": {"self_html": f"https://zenodo.org/records/{record_id}"},
    }


GIRELLI = {
    "person_or_org": {
        "type": "personal",
        "family_name": "Girelli",
        "given_name": "Valentina Alena",
        "identifiers": [{"scheme": "orcid", "identifier": "0000-0001-9257-9803"}],
    }
}

MANGANELLI = {
    "person_or_org": {
        "type": "personal",
        "family_name": "Manganelli Del Fà",
        "given_name": "Rachele",
        "identifiers": [{"scheme": "orcid", "identifier": "0009-0007-4401-9323"}],
    }
}


@patch("changes_metadata_manager.export_zenodo_csv.time.sleep")
@patch("changes_metadata_manager.export_zenodo_csv.fetch_latest_published_record")
def test_exports_latest_remote_versions_in_drafts_order(
    mock_fetch, mock_sleep, tmp_path
):
    drafts_path = tmp_path / "drafts.json"
    drafts = [
        _draft("101"),
        {
            **_draft(""),
            "status": "failed",
            "zenodo_url": "",
            "access_token": "",
            "user_agent": "",
        },
        _draft("102"),
    ]
    drafts_path.write_text(json.dumps(drafts))
    mock_fetch.side_effect = [
        _record("201", "Corrected remote title A", [GIRELLI, MANGANELLI]),
        _record("202", "Corrected remote title B", [MANGANELLI]),
    ]

    csv_path = export_zenodo_csv(drafts_path)

    assert csv_path == tmp_path / "doi_table.csv"
    assert csv_path.read_text() == (
        "Numero su DMP,Caso di studio,Autore/i,Tipo,Titolo,Data pubblicazione,"
        "DOI,URL,Repository,Licenza,Note\n"
        ',Aldrovandi,"Girelli, Valentina Alena [orcid:0000-0001-9257-9803]; '
        'Manganelli Del Fà, Rachele [orcid:0009-0007-4401-9323]",Dataset,'
        "Corrected remote title A,2026-07-17,10.5281/zenodo.201,"
        "https://zenodo.org/records/201,Zenodo,"
        "cc0-1.0 (Metadata license); cc-by-4.0 (Content license),\n"
        ',Aldrovandi,"Manganelli Del Fà, Rachele '
        '[orcid:0009-0007-4401-9323]",Dataset,Corrected remote title B,'
        "2026-07-17,10.5281/zenodo.202,https://zenodo.org/records/202,"
        "Zenodo,cc0-1.0 (Metadata license); cc-by-4.0 (Content license),\n"
    )
    assert mock_fetch.call_args_list == [
        call("https://zenodo.org/api", "101", "token", "agent"),
        call("https://zenodo.org/api", "102", "token", "agent"),
    ]
    assert mock_sleep.call_args_list == [call(0.5), call(0.5)]


@patch("changes_metadata_manager.export_zenodo_csv.time.sleep")
@patch("changes_metadata_manager.export_zenodo_csv.fetch_latest_published_record")
def test_writes_to_requested_output(mock_fetch, mock_sleep, tmp_path):
    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps([_draft("101")]))
    mock_fetch.return_value = _record("201", "Remote title", [GIRELLI])
    output_path = tmp_path / "silvio.csv"

    result = export_zenodo_csv(drafts_path, output_path)

    assert result == output_path
    assert output_path.exists()
    mock_sleep.assert_called_once_with(0.5)


@patch("changes_metadata_manager.export_zenodo_csv.fetch_latest_published_record")
def test_http_error_preserves_existing_csv(mock_fetch, tmp_path):
    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps([_draft("404")]))
    output_path = tmp_path / "doi_table.csv"
    output_path.write_text("previous export\n")
    mock_fetch.side_effect = requests.HTTPError("404 Client Error")

    with pytest.raises(requests.HTTPError, match="404 Client Error"):
        export_zenodo_csv(drafts_path)

    assert output_path.read_text() == "previous export\n"
