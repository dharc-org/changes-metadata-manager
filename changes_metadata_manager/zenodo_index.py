# SPDX-FileCopyrightText: 2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import argparse
import csv
import json
import time
from datetime import date
from html import escape
from pathlib import Path

import yaml
from rich.progress import track

from changes_metadata_manager.zenodo_api import (
    REQUEST_TIMEOUT,
    fetch_latest_published_record,
    request_with_retry,
)
from changes_metadata_manager.zenodo_metadata import extract_entity_id, extract_stage
from changes_metadata_manager.zenodo_upload import (
    STAGE_DESCRIPTIONS,
    STAGE_TITLE_NAMES,
    LiteralBlockDumper,
)


def build_index(records: list[dict]) -> list[dict]:
    objects: dict[str, dict] = {}
    for record in records:
        metadata = record["metadata"]
        entity_id = extract_entity_id(record)
        stage = extract_stage(record)
        suffix = f" - {STAGE_TITLE_NAMES[stage]} - Aldrovandi Digital Twin"
        title = metadata["title"].removesuffix(suffix)
        uri = next(
            item["identifier"]
            for item in metadata["identifiers"]
            if item["identifier"].endswith(f"/itm/{entity_id}/ob00/1")
        )
        if entity_id not in objects:
            objects[entity_id] = {
                "id": entity_id,
                "uri": uri,
                "title": title,
                "stages": {},
            }
        entry = objects[entity_id]
        if stage in entry["stages"]:
            raise ValueError(f"Multiple records for object {entity_id}, stage {stage}")
        entry["stages"][stage] = {
            "doi": record["pids"]["doi"]["identifier"],
            "url": record["links"]["self_html"],
            "title": metadata["title"],
            "resource_type": metadata["resource_type"]["id"],
        }
    return sorted(
        objects.values(), key=lambda item: (item["title"].casefold(), item["id"])
    )


def build_description(objects: list[dict]) -> str:
    stages = "".join(
        f"- <strong>{escape(label)}</strong>: {escape(STAGE_DESCRIPTIONS[stage])}.\n"
        for stage, label in STAGE_TITLE_NAMES.items()
    )
    introduction = (
        "The Aldrovandi Digital Twin is the 3D reconstruction of "
        '"The Other Renaissance: Ulisse Aldrovandi and the Wonders of the World", '
        "an exhibition held at the Palazzo Poggi Museum in Bologna from December 2022 "
        f"to May 2023. This page lists the {len(objects)} objects of the exhibition "
        "that have data on Zenodo, with a link to each dataset.\n\n"
        "An object can have up to four datasets, one for each step of its "
        f"digitisation:\n\n{stages}\n\n"
        "Licences vary from one dataset to another, so check the linked record "
        "before reusing its files. Where we had no permission to publish the files "
        "of an object, its datasets contain only metadata and provenance. "
        "The list below is also available as "
        "<code>index.csv</code>, free to reuse "
        "under CC0.\n\n"
        "<strong>Exhibits</strong>\n\n"
    )
    entries = []
    for item in objects:
        links = [
            f'<a href="https://doi.org/{escape(item["stages"][stage]["doi"], quote=True)}">'
            f"{escape(label)}</a>"
            for stage, label in STAGE_TITLE_NAMES.items()
            if stage in item["stages"]
        ]
        entries.append(
            f"- <strong>{escape(item['title'])}</strong> "
            f'(<a href="{escape(item["uri"], quote=True)}">{escape(item["id"])}</a>): '
            + "; ".join(links)
            + "\n"
        )
    return introduction + "".join(entries) + "\n\n"


def fetch_index_records(drafts: list[dict]) -> list[dict]:
    endpoints: dict[str, list[dict]] = {}
    for draft in drafts:
        if draft["draft_id"]:
            endpoints.setdefault(draft["zenodo_url"].rstrip("/"), []).append(draft)
    records = []
    for endpoint, entries in endpoints.items():
        for start in track(
            range(0, len(entries), 25), description="Reading record batches"
        ):
            batch = entries[start : start + 25]
            ids = " OR ".join(str(entry["draft_id"]) for entry in batch)
            response = request_with_retry(
                "GET",
                f"{endpoint}/records",
                params={"q": f"recid:({ids})", "size": 25, "all_versions": "false"},
                headers={
                    "Accept": "application/vnd.inveniordm.v1+json",
                    "User-Agent": batch[0]["user_agent"],
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            hits = {
                str(record["id"]): record for record in response.json()["hits"]["hits"]
            }
            for draft in batch:
                record_id = str(draft["draft_id"])
                if record_id in hits:
                    records.append(hits[record_id])
                else:
                    records.append(
                        fetch_latest_published_record(
                            endpoint,
                            record_id,
                            draft["access_token"],
                            draft["user_agent"],
                        )
                    )
            time.sleep(0.5)
    return records


def generate_index(drafts_path: Path, output_dir: Path) -> Path:
    drafts = json.loads(drafts_path.read_text())
    records = fetch_index_records(drafts)
    if not records:
        raise ValueError("The upload register contains no record IDs")
    objects = build_index(records)
    creators: dict[str, dict] = {}
    for record in records:
        for creator in record["metadata"]["creators"]:
            person = creator["person_or_org"]
            creators[person["name"]] = {
                key: creator[key]
                for key in ("person_or_org", "affiliations")
                if key in creator
            }
    metadata = {
        "title": "Aldrovandi Digital Twin: index of the digitised objects",
        "resource_type": {"id": "dataset"},
        "creators": [creators[name] for name in sorted(creators)],
        "publication_date": date.today().isoformat(),
        "publisher": "Zenodo",
        "rights": [{"id": "cc0-1.0"}],
        "description": build_description(objects),
        "related_identifiers": [
            {
                "identifier": stage["doi"],
                "scheme": "doi",
                "relation_type": {"id": "references"},
                "resource_type": {"id": stage["resource_type"]},
            }
            for item in objects
            for stage in item["stages"].values()
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "index.csv"
    with index_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "object_id",
                "object_uri",
                "object_title",
                "stage",
                "record_title",
                "doi",
                "url",
            ]
        )
        for item in objects:
            for stage in STAGE_TITLE_NAMES:
                if stage in item["stages"]:
                    record = item["stages"][stage]
                    writer.writerow(
                        [
                            item["id"],
                            item["uri"],
                            item["title"],
                            stage,
                            record["title"],
                            record["doi"],
                            record["url"],
                        ]
                    )
    source = next(draft for draft in drafts if draft["draft_id"])
    config = {
        **metadata,
        "access": {"record": "public", "files": "public"},
        "files": [str(index_path.resolve())],
        **{key: source[key] for key in ("zenodo_url", "access_token", "user_agent")},
    }
    config_path = output_dir / "record.yaml"
    with config_path.open("w", encoding="utf-8") as file:
        config_path.chmod(0o600)
        yaml.dump(
            config, file, Dumper=LiteralBlockDumper, allow_unicode=True, sort_keys=False
        )
    print(f"{len(objects)} objects, {len(records)} records: {index_path}")
    print(f"Upload configuration: {config_path}")
    return index_path


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Generate an Aldrovandi index and Zenodo record metadata"
    )
    parser.add_argument("drafts_json", type=Path)
    parser.add_argument("--output", type=Path, default=Path("zenodo_output_index"))
    args = parser.parse_args()
    generate_index(args.drafts_json, args.output)


if __name__ == "__main__":  # pragma: no cover
    main()
