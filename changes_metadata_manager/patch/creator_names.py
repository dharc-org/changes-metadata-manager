# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import argparse
import json
import re
import time
from collections import Counter
from copy import deepcopy
from pathlib import Path

import requests
from rdflib import Graph
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)

from changes_metadata_manager.folder_metadata_builder import (
    BASE_URI,
    load_kg,
)
from changes_metadata_manager.zenodo_api import (
    ZenodoRecordCache,
    fetch_record,
)
from changes_metadata_manager.zenodo_metadata import (
    ZenodoUpdatePayload,
    build_zenodo_update_payload,
    extract_stage,
    zenodo_payload_differences,
)
from changes_metadata_manager.zenodo_upload import (
    CREATORS_LOOKUP_PATH,
    _atomic_write_json,
    build_creators_for_entity_stage,
    build_metadata_creators,
    load_creators_lookup,
    merge_creators,
)
from changes_metadata_manager.patch.prepared_updates import (
    CACHE_FILENAME,
    MANIFEST_FILENAME,
    REQUEST_DELAY,
    apply_prepared_updates,
    extract_package_entity_ids,
    prepare_output_directory,
    write_payload,
)

console = Console()
ACTIVITY_ENTITY_PATTERN = re.compile(rf"^{re.escape(BASE_URI)}/act/([^/]+)/")


def _creator_orcid(creator: dict) -> str:
    identifiers = creator["person_or_org"]["identifiers"]
    orcids = [
        identifier["identifier"]
        for identifier in identifiers
        if identifier["scheme"] == "orcid"
    ]
    if len(orcids) != 1:
        raise ValueError(f"Expected one ORCID for creator: {creator}")
    return orcids[0]


def _creator_signature(creator: dict) -> tuple[str, str, str, str, tuple[str, ...]]:
    person = creator["person_or_org"]
    affiliations = tuple(sorted(item["name"] for item in creator["affiliations"]))
    return (
        person["type"],
        person["family_name"],
        person["given_name"],
        creator["role"]["id"],
        affiliations,
    )


def _creators_by_orcid(
    creators: list[dict],
) -> dict[str, tuple[str, str, str, str, tuple[str, ...]]]:
    creators_by_orcid = {
        _creator_orcid(creator): _creator_signature(creator) for creator in creators
    }
    if len(creators_by_orcid) != len(creators):
        raise ValueError("Duplicate creator ORCID")
    return creators_by_orcid


def _classify_creators(
    current_creators: list[dict],
    expected_creators: list[dict],
) -> tuple[str, set[str]]:
    current = _creators_by_orcid(current_creators)
    expected = _creators_by_orcid(expected_creators)
    missing_orcids = expected.keys() - current.keys()

    if current == expected:
        return "already_correct", set()

    expected_without_missing = {
        orcid: signature
        for orcid, signature in expected.items()
        if orcid not in missing_orcids
    }
    if missing_orcids and current == expected_without_missing:
        return "would_patch", missing_orcids

    return "blocked", missing_orcids


def _entity_ids(kg: Graph) -> set[str]:
    entity_ids: set[str] = set()
    for subject in kg.subjects():
        match = ACTIVITY_ENTITY_PATTERN.match(str(subject))
        if match:
            entity_ids.add(match.group(1))
    return entity_ids


def _payload_with_creators(
    record: dict, expected_creators: list[dict]
) -> ZenodoUpdatePayload:
    payload = build_zenodo_update_payload(record)
    payload["metadata"]["creators"] = deepcopy(expected_creators)
    return payload


def prepare_creator_name_patches(
    drafts_path: Path,
    kg_path: Path,
    output_dir: Path,
    *,
    creators_lookup_path: Path = CREATORS_LOOKUP_PATH,
) -> Path:
    prepare_output_directory(output_dir)
    console.print(f"Loading KG from {kg_path}...")
    kg = load_kg(kg_path)
    kg_entity_ids = _entity_ids(kg)
    creators_lookup = load_creators_lookup(creators_lookup_path)
    with open(drafts_path) as file:
        drafts = json.load(file)

    records = [draft for draft in drafts if draft["status"] != "failed"]
    manifest_path = output_dir / MANIFEST_FILENAME
    manifest: list[dict] = []
    stats: Counter[str] = Counter()
    _atomic_write_json(manifest_path, manifest)
    cache_path = drafts_path.parent / CACHE_FILENAME

    console.print(f"Checking {len(records)} records...")
    with (
        ZenodoRecordCache(cache_path) as cache,
        Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
        ) as progress,
    ):
        task = progress.add_task("Auditing", total=len(records))
        for draft in records:
            record_id = str(draft["draft_id"])
            log_entry = {"record_id": draft["draft_id"]}
            progress.update(task, description=f"Record {record_id}")

            if draft["status"] != "published":
                log_entry["status"] = "blocked"
                log_entry["reason"] = f"Unsupported record status: {draft['status']}"
                manifest.append(log_entry)
                stats["blocked"] += 1
                _atomic_write_json(manifest_path, manifest)
                progress.advance(task)
                continue

            cache_hit = False
            try:
                zenodo_url = draft["zenodo_url"].rstrip("/")
                cached_record = cache.get(zenodo_url, record_id)
                if cached_record is None:
                    record, has_edit_draft = fetch_record(
                        zenodo_url,
                        record_id,
                        draft["access_token"],
                        draft["user_agent"],
                    )
                    cache.set(zenodo_url, record_id, record, has_edit_draft)
                else:
                    record, has_edit_draft = cached_record
                    cache_hit = True
                stage = extract_stage(record)
                entity_ids = extract_package_entity_ids(Path(draft["config_file"]))
                missing_entity_ids = set(entity_ids).difference(kg_entity_ids)
                if missing_entity_ids:
                    missing_ids = ", ".join(sorted(missing_entity_ids))
                    raise ValueError(
                        f"No KG activities found for entities: {missing_ids}"
                    )
                expected_creators = merge_creators(
                    build_creators_for_entity_stage(
                        kg, entity_ids, stage, creators_lookup
                    ),
                    build_metadata_creators(kg, entity_ids, creators_lookup),
                )
                remote_status, missing_orcids = _classify_creators(
                    record["metadata"]["creators"], expected_creators
                )
                missing_creators = [
                    {
                        "name": (
                            f"{creator['person_or_org']['given_name']} "
                            f"{creator['person_or_org']['family_name']}"
                        ),
                        "orcid": _creator_orcid(creator),
                    }
                    for creator in expected_creators
                    if _creator_orcid(creator) in missing_orcids
                ]
                log_entry.update(
                    {
                        "entity_ids": entity_ids,
                        "stage": stage,
                        "missing_creators": missing_creators,
                    }
                )

                if has_edit_draft:
                    log_entry["status"] = "blocked"
                    log_entry["reason"] = "An edit draft already exists"
                elif remote_status == "blocked":
                    log_entry["status"] = "blocked"
                    log_entry["reason"] = (
                        "Creator differences are not limited to missing creators"
                    )
                elif remote_status == "already_correct":
                    log_entry["status"] = "already_correct"
                else:
                    payload = _payload_with_creators(record, expected_creators)
                    payload_differences = zenodo_payload_differences(
                        payload, record, {"creators"}
                    )
                    if payload_differences:
                        log_entry["status"] = "blocked"
                        log_entry["reason"] = (
                            "Remote metadata cannot be preserved in an update payload"
                        )
                        log_entry["differences"] = payload_differences
                    else:
                        payload_file = f"{record_id}.yaml"
                        write_payload(output_dir / payload_file, payload)
                        log_entry["status"] = "would_patch"
                        log_entry["payload_file"] = payload_file
            except (requests.RequestException, ValueError) as exc:
                log_entry["status"] = "error"
                log_entry["error"] = str(exc)
                console.print(f"\n[red][FAILED][/red] Record {record_id}: {exc}")

            manifest.append(log_entry)
            stats[log_entry["status"]] += 1
            _atomic_write_json(manifest_path, manifest)
            progress.advance(task)
            if not cache_hit:
                time.sleep(REQUEST_DELAY)

    console.print()
    console.print("[bold]Results:[/bold]")
    for status in ("would_patch", "already_correct", "blocked", "error"):
        console.print(f"  {status}: {stats[status]}")
    console.print(f"  Manifest: {manifest_path}")
    return manifest_path


def apply_creator_name_patches(drafts_path: Path, output_dir: Path) -> Path:
    return apply_prepared_updates(drafts_path, output_dir)


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Patch missing creators on affected Zenodo records"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser(
        "prepare", help="Audit records and prepare update payloads"
    )
    prepare_parser.add_argument("drafts_json", type=Path, help="Path to drafts.json")
    prepare_parser.add_argument(
        "kg_path", type=Path, help="Path to knowledge graph (kg.ttl)"
    )
    prepare_parser.add_argument(
        "output_dir", type=Path, help="Directory for prepared payloads"
    )

    apply_parser = subparsers.add_parser(
        "apply", help="Apply and publish prepared update payloads"
    )
    apply_parser.add_argument("drafts_json", type=Path, help="Path to drafts.json")
    apply_parser.add_argument(
        "output_dir", type=Path, help="Directory containing prepared payloads"
    )

    args = parser.parse_args()
    if args.command == "prepare":
        prepare_creator_name_patches(args.drafts_json, args.kg_path, args.output_dir)
    else:
        apply_creator_name_patches(args.drafts_json, args.output_dir)
