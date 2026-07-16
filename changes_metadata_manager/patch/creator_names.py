# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import argparse
import json
import os
import re
import tempfile
import time
import zipfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import cast

import requests
import yaml
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
    extract_id_from_folder_name,
    load_kg,
)
from changes_metadata_manager.zenodo_api import (
    ZenodoRecordCache,
    create_edit_draft,
    fetch_record,
    publish_draft,
    update_draft,
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

console = Console()

REQUEST_DELAY = 2
ACTIVITY_ENTITY_PATTERN = re.compile(rf"^{re.escape(BASE_URI)}/act/([^/]+)/")
CACHE_FILENAME = "creator_names_cache.sqlite3"
MANIFEST_FILENAME = "manifest.json"
APPLY_LOG_FILENAME = "apply_log.json"
PREPARE_STATUSES = {"would_patch", "already_correct", "blocked", "error"}


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


def _atomic_write_yaml(path: Path, payload: ZenodoUpdatePayload) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as file:
        yaml.safe_dump(payload, file, sort_keys=False, allow_unicode=True)
    os.replace(tmp_path, path)


def _load_manifest(path: Path) -> list[dict]:
    with open(path) as file:
        manifest = json.load(file)
    if not isinstance(manifest, list):
        raise ValueError(f"Invalid manifest: {path}")

    entries: list[dict] = []
    record_ids: set[str] = set()
    for item in manifest:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid manifest entry: {item}")
        if "record_id" not in item or "status" not in item:
            raise ValueError(f"Invalid manifest entry: {item}")
        record_id = str(item["record_id"])
        if record_id in record_ids:
            raise ValueError(f"Duplicate record in manifest: {record_id}")
        record_ids.add(record_id)
        if item["status"] not in PREPARE_STATUSES:
            raise ValueError(f"Invalid manifest status for record {record_id}")
        if item["status"] == "would_patch":
            expected_payload_file = f"{record_id}.yaml"
            if (
                "payload_file" not in item
                or item["payload_file"] != expected_payload_file
            ):
                raise ValueError(f"Invalid payload file for record {record_id}")
        elif "payload_file" in item:
            raise ValueError(f"Unexpected payload file for record {record_id}")
        entries.append(item)
    return entries


def _prepare_output_directory(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_names = {path.name for path in output_dir.iterdir()}
    if not existing_names:
        return
    if MANIFEST_FILENAME not in existing_names:
        raise ValueError(f"Output directory contains unmanaged files: {output_dir}")

    manifest = _load_manifest(output_dir / MANIFEST_FILENAME)
    managed_names = {MANIFEST_FILENAME, APPLY_LOG_FILENAME}
    managed_names.update(
        entry["payload_file"] for entry in manifest if "payload_file" in entry
    )
    unmanaged_names = existing_names - managed_names
    if unmanaged_names:
        names = ", ".join(sorted(unmanaged_names))
        raise ValueError(f"Output directory contains unmanaged files: {names}")

    for name in existing_names:
        path = output_dir / name
        if not path.is_file():
            raise ValueError(f"Managed output is not a file: {path}")
    for name in existing_names:
        (output_dir / name).unlink()


def _load_payloads(
    output_dir: Path, manifest: list[dict]
) -> dict[str, ZenodoUpdatePayload]:
    payloads: dict[str, ZenodoUpdatePayload] = {}
    for entry in manifest:
        if entry["status"] != "would_patch":
            continue
        record_id = str(entry["record_id"])
        payload_path = output_dir / entry["payload_file"]
        with open(payload_path) as file:
            payload = yaml.safe_load(file)
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid payload for record {record_id}")
        required_fields = {"access", "files", "metadata"}
        allowed_fields = required_fields | {"custom_fields"}
        if set(payload) - allowed_fields or not required_fields <= set(payload):
            raise ValueError(f"Invalid payload fields for record {record_id}")
        if any(not isinstance(payload[field], dict) for field in required_fields):
            raise ValueError(f"Invalid payload structure for record {record_id}")
        if "custom_fields" in payload and not isinstance(
            payload["custom_fields"], dict
        ):
            raise ValueError(f"Invalid payload structure for record {record_id}")
        payloads[record_id] = cast(ZenodoUpdatePayload, payload)
    return payloads


def _load_drafts_for_records(
    drafts_path: Path, record_ids: set[str]
) -> dict[str, dict]:
    with open(drafts_path) as file:
        drafts = json.load(file)
    if not isinstance(drafts, list):
        raise ValueError(f"Invalid drafts file: {drafts_path}")

    drafts_by_id: dict[str, dict] = {}
    for draft in drafts:
        if not isinstance(draft, dict) or "draft_id" not in draft:
            raise ValueError(f"Invalid draft entry: {draft}")
        record_id = str(draft["draft_id"])
        if record_id not in record_ids:
            continue
        if record_id in drafts_by_id:
            raise ValueError(f"Duplicate draft for record {record_id}")
        required_fields = {
            "zenodo_url",
            "access_token",
            "user_agent",
            "status",
        }
        if not required_fields <= set(draft):
            raise ValueError(f"Incomplete draft for record {record_id}")
        if draft["status"] != "published":
            raise ValueError(f"Record {record_id} is not published")
        drafts_by_id[record_id] = draft

    missing_ids = record_ids - drafts_by_id.keys()
    if missing_ids:
        ids = ", ".join(sorted(missing_ids))
        raise ValueError(f"Records missing from drafts file: {ids}")
    return drafts_by_id


def _load_apply_log(path: Path, record_ids: set[str]) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as file:
        apply_log = json.load(file)
    if not isinstance(apply_log, list):
        raise ValueError(f"Invalid apply log: {path}")

    entries: list[dict] = []
    attempted_ids: set[str] = set()
    for item in apply_log:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid apply log entry: {item}")
        if "record_id" not in item or "status" not in item:
            raise ValueError(f"Invalid apply log entry: {item}")
        record_id = str(item["record_id"])
        if record_id not in record_ids or record_id in attempted_ids:
            raise ValueError(f"Invalid record in apply log: {record_id}")
        if item["status"] not in {"patched", "error"}:
            raise ValueError(f"Invalid apply status for record {record_id}")
        attempted_ids.add(record_id)
        entries.append(item)
    return entries


def prepare_creator_name_patches(
    drafts_path: Path,
    kg_path: Path,
    output_dir: Path,
    *,
    creators_lookup_path: Path = CREATORS_LOOKUP_PATH,
) -> Path:
    _prepare_output_directory(output_dir)
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
                with open(draft["config_file"]) as file:
                    config = yaml.safe_load(file)
                with zipfile.ZipFile(config["files"][0]) as archive:
                    folder_names = {
                        name.split("/", 1)[0] for name in archive.namelist()
                    }
                entity_ids = sorted(
                    {extract_id_from_folder_name(name) for name in folder_names}
                )
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
                        _atomic_write_yaml(output_dir / payload_file, payload)
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
    manifest = _load_manifest(output_dir / MANIFEST_FILENAME)
    payloads = _load_payloads(output_dir, manifest)
    record_ids = set(payloads)
    drafts_by_id = _load_drafts_for_records(drafts_path, record_ids)
    log_path = output_dir / APPLY_LOG_FILENAME
    apply_log = _load_apply_log(log_path, record_ids)
    attempted_ids = {str(entry["record_id"]) for entry in apply_log}
    _atomic_write_json(log_path, apply_log)
    stats: Counter[str] = Counter()
    stats["skipped"] = len(attempted_ids)
    entries_to_apply = [
        entry
        for entry in manifest
        if entry["status"] == "would_patch"
        and str(entry["record_id"]) not in attempted_ids
    ]
    cache_path = drafts_path.parent / CACHE_FILENAME

    console.print(f"Applying {len(entries_to_apply)} prepared records...")
    with (
        ZenodoRecordCache(cache_path) as cache,
        Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
        ) as progress,
    ):
        task = progress.add_task("Applying", total=len(entries_to_apply))
        for entry in entries_to_apply:
            record_id = str(entry["record_id"])
            draft = drafts_by_id[record_id]
            zenodo_url = draft["zenodo_url"].rstrip("/")
            log_entry = {"record_id": entry["record_id"]}
            progress.update(task, description=f"Record {record_id}")
            cache.invalidate(zenodo_url, record_id)

            try:
                create_edit_draft(
                    zenodo_url,
                    record_id,
                    draft["access_token"],
                    draft["user_agent"],
                )
                update_draft(
                    zenodo_url,
                    record_id,
                    draft["access_token"],
                    draft["user_agent"],
                    payloads[record_id],
                )
                publish_draft(
                    zenodo_url,
                    record_id,
                    draft["access_token"],
                    draft["user_agent"],
                )
                log_entry["status"] = "patched"
            except requests.RequestException as exc:
                log_entry["status"] = "error"
                log_entry["error"] = str(exc)
                console.print(f"\n[red][FAILED][/red] Record {record_id}: {exc}")

            apply_log.append(log_entry)
            stats[log_entry["status"]] += 1
            _atomic_write_json(log_path, apply_log)
            progress.advance(task)
            time.sleep(REQUEST_DELAY)

    console.print()
    console.print("[bold]Results:[/bold]")
    for status in ("patched", "error", "skipped"):
        console.print(f"  {status}: {stats[status]}")
    console.print(f"  Log: {log_path}")
    return log_path


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
