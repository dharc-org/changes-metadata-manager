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

from changes_metadata_manager.folder_metadata_builder import BASE_URI, load_kg
from changes_metadata_manager.zenodo_api import (
    create_edit_draft,
    fetch_record,
    publish_draft,
    update_draft,
)
from changes_metadata_manager.zenodo_metadata import (
    ZenodoUpdatePayload,
    build_zenodo_update_payload,
    extract_entity_id,
    extract_stage,
    zenodo_payload_differences,
)
from changes_metadata_manager.zenodo_upload import (
    CREATORS_LOOKUP_PATH,
    _atomic_write_json,
    build_creators_for_entity_stage,
    build_metadata_creators,
    entity_group_id,
    load_creators_lookup,
    merge_creators,
)

console = Console()

REQUEST_DELAY = 2
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


def _entity_ids_by_group(kg: Graph) -> dict[str, list[str]]:
    grouped_ids: dict[str, set[str]] = {}
    for subject in kg.subjects():
        match = ACTIVITY_ENTITY_PATTERN.match(str(subject))
        if not match:
            continue
        entity_id = match.group(1)
        group_id = entity_group_id(entity_id)
        if group_id not in grouped_ids:
            grouped_ids[group_id] = set()
        grouped_ids[group_id].add(entity_id)
    return {
        group_id: sorted(entity_ids) for group_id, entity_ids in grouped_ids.items()
    }


def _payload_with_creators(
    record: dict, expected_creators: list[dict]
) -> ZenodoUpdatePayload:
    payload = build_zenodo_update_payload(record)
    payload["metadata"]["creators"] = deepcopy(expected_creators)
    return payload


def patch_creator_names(
    drafts_path: Path,
    kg_path: Path,
    *,
    apply: bool = False,
    creators_lookup_path: Path = CREATORS_LOOKUP_PATH,
) -> Path:
    console.print(f"Loading KG from {kg_path}...")
    kg = load_kg(kg_path)
    entity_ids_by_group = _entity_ids_by_group(kg)
    creators_lookup = load_creators_lookup(creators_lookup_path)
    with open(drafts_path) as file:
        drafts = json.load(file)

    records = [draft for draft in drafts if draft["status"] != "failed"]
    log_path = drafts_path.parent / "patch_creator_names_log.json"
    patch_log: list[dict] = []
    stats: Counter[str] = Counter()
    _atomic_write_json(log_path, patch_log)

    console.print(f"Checking {len(records)} records...")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    ) as progress:
        task = progress.add_task("Auditing", total=len(records))
        for draft in records:
            record_id = str(draft["draft_id"])
            log_entry = {"record_id": draft["draft_id"]}
            progress.update(task, description=f"Record {record_id}")

            if draft["status"] != "published":
                log_entry["status"] = "blocked"
                log_entry["reason"] = f"Unsupported record status: {draft['status']}"
                patch_log.append(log_entry)
                stats["blocked"] += 1
                _atomic_write_json(log_path, patch_log)
                progress.advance(task)
                continue

            try:
                zenodo_url = draft["zenodo_url"].rstrip("/")
                record, has_edit_draft = fetch_record(
                    zenodo_url,
                    record_id,
                    draft["access_token"],
                    draft["user_agent"],
                )
                stage = extract_stage(record)
                primary_entity_id = extract_entity_id(record)
                group_id = entity_group_id(primary_entity_id)
                if group_id not in entity_ids_by_group:
                    raise ValueError(
                        f"No KG activities found for entity {primary_entity_id}"
                    )
                entity_ids = entity_ids_by_group[group_id]
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
                    elif not apply:
                        log_entry["status"] = "would_patch"
                    else:
                        draft_record = create_edit_draft(
                            zenodo_url,
                            record_id,
                            draft["access_token"],
                            draft["user_agent"],
                        )
                        draft_status, draft_missing_orcids = _classify_creators(
                            draft_record["metadata"]["creators"], expected_creators
                        )
                        if (
                            draft_status != "would_patch"
                            or draft_missing_orcids != missing_orcids
                        ):
                            log_entry["status"] = "blocked"
                            log_entry["reason"] = (
                                "Created edit draft no longer matches the audited record"
                            )
                        else:
                            payload = _payload_with_creators(
                                draft_record, expected_creators
                            )
                            payload_differences = zenodo_payload_differences(
                                payload, draft_record, {"creators"}
                            )
                            if payload_differences:
                                log_entry["status"] = "blocked"
                                log_entry["reason"] = (
                                    "Edit draft metadata cannot be preserved in an "
                                    "update payload"
                                )
                                log_entry["differences"] = payload_differences
                            else:
                                update_draft(
                                    zenodo_url,
                                    record_id,
                                    draft["access_token"],
                                    draft["user_agent"],
                                    payload,
                                )
                                publish_draft(
                                    zenodo_url,
                                    record_id,
                                    draft["access_token"],
                                    draft["user_agent"],
                                )
                                log_entry["status"] = "patched"
            except (requests.RequestException, ValueError) as exc:
                log_entry["status"] = "error"
                log_entry["error"] = str(exc)
                console.print(f"\n[red][FAILED][/red] Record {record_id}: {exc}")

            patch_log.append(log_entry)
            stats[log_entry["status"]] += 1
            _atomic_write_json(log_path, patch_log)
            progress.advance(task)
            time.sleep(REQUEST_DELAY)

    console.print()
    console.print("[bold]Results:[/bold]")
    for status in ("would_patch", "patched", "already_correct", "blocked", "error"):
        console.print(f"  {status}: {stats[status]}")
    console.print(f"  Log: {log_path}")
    return log_path


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Patch missing creators on affected Zenodo records"
    )
    parser.add_argument("drafts_json", type=Path, help="Path to drafts.json")
    parser.add_argument("kg_path", type=Path, help="Path to knowledge graph (kg.ttl)")
    parser.add_argument(
        "--apply", action="store_true", help="Apply and publish the audited changes"
    )
    args = parser.parse_args()
    patch_creator_names(args.drafts_json, args.kg_path, apply=args.apply)
