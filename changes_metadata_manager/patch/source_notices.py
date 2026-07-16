# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import cast

import requests
from piccione.upload.on_zenodo import text_to_html
from rdflib import Graph
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)

from changes_metadata_manager.folder_metadata_builder import load_kg
from changes_metadata_manager.patch.prepared_updates import (
    CACHE_FILENAME,
    MANIFEST_FILENAME,
    REQUEST_DELAY,
    apply_prepared_updates,
    extract_package_context,
    prepare_output_directory,
    write_payload,
)
from changes_metadata_manager.zenodo_api import ZenodoRecordCache, fetch_record
from changes_metadata_manager.zenodo_metadata import (
    ZenodoUpdatePayload,
    build_zenodo_update_payload,
    extract_content_license,
    extract_entity_id,
    extract_stage,
    zenodo_payload_differences,
)
from changes_metadata_manager.zenodo_upload import (
    EXTERNAL_SOURCE_NOTICE,
    RESTRICTED_NOTICE,
    _atomic_write_json,
    select_missing_files_notice,
)

console = Console()

OLD_NOTICE_HTML = text_to_html(RESTRICTED_NOTICE)
NEW_NOTICE_HTML = text_to_html(EXTERNAL_SOURCE_NOTICE)


def _classify_notice(record: dict) -> tuple[str, str | None]:
    descriptions = record["metadata"]["additional_descriptions"]
    old_notices = [
        item
        for item in descriptions
        if item["type"]["id"] == "notes" and item["description"] == OLD_NOTICE_HTML
    ]
    new_notices = [
        item
        for item in descriptions
        if item["type"]["id"] == "notes" and item["description"] == NEW_NOTICE_HTML
    ]
    if len(old_notices) == 1 and not new_notices:
        return "would_patch", None
    if len(new_notices) == 1 and not old_notices:
        return "already_correct", None
    if not old_notices and not new_notices:
        return "blocked", "Expected source notice not found"
    return "blocked", "Unexpected source notice state"


def _payload_with_source_notice(record: dict) -> ZenodoUpdatePayload:
    payload = build_zenodo_update_payload(record)
    descriptions = cast("list[dict]", payload["metadata"]["additional_descriptions"])
    for item in descriptions:
        if item["type"]["id"] == "notes" and item["description"] == OLD_NOTICE_HTML:
            item["description"] = NEW_NOTICE_HTML
            return payload
    raise ValueError("Expected source notice not found")


def _source_notice_candidates(
    kg: Graph, drafts: list[dict]
) -> list[tuple[dict, list[str], str]]:
    candidates: list[tuple[dict, list[str], str]] = []
    for draft in drafts:
        if draft["status"] == "failed":
            continue
        config_path = Path(draft["config_file"])
        config, entity_ids, stage = extract_package_context(config_path)
        notice = select_missing_files_notice(
            kg, entity_ids, stage, extract_content_license(config)
        )
        if notice == EXTERNAL_SOURCE_NOTICE:
            candidates.append((draft, entity_ids, stage))
    return candidates


def prepare_source_notice_patches(
    drafts_path: Path, kg_path: Path, output_dir: Path
) -> Path:
    prepare_output_directory(output_dir)
    console.print(f"Loading KG from {kg_path}...")
    kg = load_kg(kg_path)
    with open(drafts_path) as file:
        drafts = json.load(file)

    candidates = _source_notice_candidates(kg, drafts)
    manifest_path = output_dir / MANIFEST_FILENAME
    manifest: list[dict] = []
    stats: Counter[str] = Counter()
    _atomic_write_json(manifest_path, manifest)
    cache_path = drafts_path.parent / CACHE_FILENAME

    console.print(f"Checking {len(candidates)} candidate records...")
    with (
        ZenodoRecordCache(cache_path) as cache,
        Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
        ) as progress,
    ):
        task = progress.add_task("Auditing", total=len(candidates))
        for draft, entity_ids, packaged_stage in candidates:
            record_id = str(draft["draft_id"])
            log_entry = {
                "record_id": draft["draft_id"],
                "entity_ids": entity_ids,
                "stage": packaged_stage,
            }
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

                remote_stage = extract_stage(record)
                if remote_stage != packaged_stage:
                    raise ValueError(
                        f"Package stage {packaged_stage} does not match remote stage "
                        f"{remote_stage}"
                    )
                remote_entity_id = extract_entity_id(record)
                if remote_entity_id not in entity_ids:
                    raise ValueError(
                        f"Remote entity {remote_entity_id} not found in package entities"
                    )

                remote_status, reason = _classify_notice(record)
                if has_edit_draft:
                    log_entry["status"] = "blocked"
                    log_entry["reason"] = "An edit draft already exists"
                elif remote_status == "blocked":
                    log_entry["status"] = "blocked"
                    log_entry["reason"] = reason
                elif remote_status == "already_correct":
                    log_entry["status"] = "already_correct"
                else:
                    payload = _payload_with_source_notice(record)
                    payload_differences = zenodo_payload_differences(
                        payload, record, {"additional_descriptions"}
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


def apply_source_notice_patches(drafts_path: Path, output_dir: Path) -> Path:
    return apply_prepared_updates(drafts_path, output_dir)


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Patch external source notices on affected Zenodo records"
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
        prepare_source_notice_patches(args.drafts_json, args.kg_path, args.output_dir)
    else:
        apply_source_notice_patches(args.drafts_json, args.output_dir)
