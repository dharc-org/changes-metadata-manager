# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import argparse
import csv
import json
import os
import tempfile
import time
from pathlib import Path

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)

from changes_metadata_manager.zenodo_api import fetch_latest_published_record
from changes_metadata_manager.zenodo_metadata import LICENSE_URI_TO_ZENODO

CSV_FIELDNAMES = [
    "Numero su DMP",
    "Caso di studio",
    "Autore/i",
    "Tipo",
    "Titolo",
    "Data pubblicazione",
    "DOI",
    "URL",
    "Repository",
    "Licenza",
    "Note",
]
REQUEST_DELAY = 0.5


def _format_creators(metadata: dict) -> str:
    creators: list[str] = []
    for creator in metadata["creators"]:
        person = creator["person_or_org"]
        orcid = next(
            identifier["identifier"]
            for identifier in person["identifiers"]
            if identifier["scheme"] == "orcid"
        )
        creators.append(
            f"{person['family_name']}, {person['given_name']} [orcid:{orcid}]"
        )
    return "; ".join(creators)


def _format_licenses(metadata: dict) -> str:
    licenses: list[str] = []
    for right in metadata["rights"]:
        short_name = LICENSE_URI_TO_ZENODO[right["link"]]
        context = right["title"]["en"].rsplit(" (", maxsplit=1)[1].removesuffix(")")
        licenses.append(f"{short_name} ({context})")
    return "; ".join(licenses)


def _build_row(record: dict) -> dict[str, str]:
    metadata = record["metadata"]
    return {
        "Numero su DMP": "",
        "Caso di studio": "Aldrovandi",
        "Autore/i": _format_creators(metadata),
        "Tipo": metadata["resource_type"]["title"]["en"],
        "Titolo": metadata["title"],
        "Data pubblicazione": metadata["publication_date"],
        "DOI": record["pids"]["doi"]["identifier"],
        "URL": record["links"]["self_html"],
        "Repository": metadata["publisher"],
        "Licenza": _format_licenses(metadata),
        "Note": "",
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    descriptor, temporary_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(descriptor, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary_path, path)


def export_zenodo_csv(drafts_path: Path, output_path: Path | None = None) -> Path:
    with open(drafts_path) as file:
        drafts = json.load(file)

    records = [draft for draft in drafts if draft["draft_id"]]
    rows: list[dict[str, str]] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    ) as progress:
        task = progress.add_task("Fetching published records", total=len(records))
        for draft in records:
            record_id = str(draft["draft_id"])
            progress.update(task, description=f"Fetching record {record_id}")
            record = fetch_latest_published_record(
                draft["zenodo_url"].rstrip("/"),
                record_id,
                draft["access_token"],
                draft["user_agent"],
            )
            rows.append(_build_row(record))
            progress.advance(task)
            time.sleep(REQUEST_DELAY)

    if output_path is None:
        destination = drafts_path.parent / "doi_table.csv"
    else:
        destination = output_path
    _write_csv(destination, rows)
    print(f"DOI table written to {destination}")
    return destination


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Export published Zenodo records to the DMP CSV format"
    )
    parser.add_argument("drafts_json", type=Path, help="Path to drafts.json")
    parser.add_argument("--output", type=Path, help="Output CSV path")
    args = parser.parse_args()
    export_zenodo_csv(args.drafts_json, args.output)


if __name__ == "__main__":  # pragma: no cover
    main()
