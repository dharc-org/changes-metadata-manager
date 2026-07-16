# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import argparse
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import cast

import requests
from piccione.upload.on_zenodo import text_to_html
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)

from changes_metadata_manager.folder_metadata_builder import load_kg
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
    CC0_DISCLAIMER,
    build_rights,
    extract_license_for_entity_stage,
)

console = Console()

REQUEST_DELAY = 2
DEFAULT_USER_AGENT = "changes-metadata-manager/1.0.0"


def _current_content_license(metadata: dict) -> str | None:
    if "rights" not in metadata:
        return None
    for right in metadata["rights"]:
        if "title" not in right or "en" not in right["title"]:
            continue
        title = right["title"]["en"]
        if "(Content license)" in title:
            if "link" not in right:
                continue
            link = right["link"]
            if "zero" in link:
                return "cc0-1.0"
            if "by-nc-sa" in link:
                return "cc-by-nc-sa-4.0"
            if "by-nc" in link:
                return "cc-by-nc-4.0"
            if "by-sa" in link:
                return "cc-by-sa-4.0"
            if "by" in link:
                return "cc-by-4.0"
    return None


def _has_cc0_disclaimer(metadata: dict) -> bool:
    if "additional_descriptions" not in metadata:
        return False
    for description in metadata["additional_descriptions"]:
        if "D. Lgs. 42/2004" in description["description"]:
            return True
    return False


def _rebuild_additional_descriptions(
    current: list[dict], correct_license: str | None
) -> list[dict]:
    rebuilt = [
        deepcopy(description)
        for description in current
        if "D. Lgs. 42/2004" not in description["description"]
    ]
    if correct_license == "cc0-1.0":
        rebuilt.append(
            {
                "description": text_to_html(CC0_DISCLAIMER),
                "type": {"id": "notes"},
            }
        )
    return rebuilt


def _payload_with_license(
    record: dict, correct_license: str | None
) -> ZenodoUpdatePayload:
    payload = build_zenodo_update_payload(record)
    metadata = payload["metadata"]
    current_descriptions = (
        cast("list[dict]", metadata["additional_descriptions"])
        if "additional_descriptions" in metadata
        else []
    )
    metadata["rights"] = build_rights(correct_license)
    metadata["additional_descriptions"] = _rebuild_additional_descriptions(
        current_descriptions, correct_license
    )
    return payload


def patch_drafts(
    drafts_path: Path,
    kg_path: Path,
    *,
    dry_run: bool = False,
) -> None:
    console.print(f"Loading KG from {kg_path}...")
    kg = load_kg(kg_path)

    with open(drafts_path) as file:
        drafts = json.load(file)

    stats = {
        "patched": 0,
        "blocked": 0,
        "skipped_correct": 0,
        "skipped_failed": 0,
        "skipped_no_kg_license": 0,
        "errors": 0,
    }
    patch_log: list[dict] = []
    entries_to_check = []
    for entry in drafts:
        if entry["status"] == "failed":
            stats["skipped_failed"] += 1
        else:
            entries_to_check.append(entry)

    console.print(f"Checking {len(entries_to_check)} records...")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    ) as progress:
        task = progress.add_task("Patching", total=len(entries_to_check))

        for entry in entries_to_check:
            record_id = entry["draft_id"]
            record_id_text = str(record_id)
            log_entry = {"record_id": record_id}
            progress.update(task, description=f"Record {record_id}")

            if entry["status"] not in ("published", "uploaded"):
                log_entry["status"] = "blocked"
                log_entry["reason"] = f"Unsupported record status: {entry['status']}"
                patch_log.append(log_entry)
                stats["blocked"] += 1
                progress.advance(task)
                continue

            zenodo_url = entry["zenodo_url"].rstrip("/")
            access_token = entry["access_token"]
            user_agent = (
                entry["user_agent"] if "user_agent" in entry else DEFAULT_USER_AGENT
            )
            is_published = entry["status"] == "published"

            try:
                record, has_edit_draft = fetch_record(
                    zenodo_url, record_id_text, access_token, user_agent
                )
                stage = extract_stage(record)
                entity_id = extract_entity_id(record)
                correct_license = extract_license_for_entity_stage(kg, entity_id, stage)
                if correct_license is None:
                    stats["skipped_no_kg_license"] += 1
                    progress.advance(task)
                    continue

                zenodo_metadata = record["metadata"]
                current_license = _current_content_license(zenodo_metadata)
                needs_rights_fix = correct_license != current_license
                needs_disclaimer_fix = (
                    correct_license == "cc0-1.0"
                ) != _has_cc0_disclaimer(zenodo_metadata)

                if not needs_rights_fix and not needs_disclaimer_fix:
                    stats["skipped_correct"] += 1
                    progress.advance(task)
                    continue

                log_entry.update(
                    {
                        "entity_id": entity_id,
                        "stage": stage,
                        "old_license": current_license,
                        "new_license": correct_license,
                        "rights_changed": needs_rights_fix,
                        "disclaimer_changed": needs_disclaimer_fix,
                    }
                )

                if is_published and has_edit_draft:
                    log_entry["status"] = "blocked"
                    log_entry["reason"] = "An edit draft already exists"
                elif not is_published and not has_edit_draft:
                    log_entry["status"] = "blocked"
                    log_entry["reason"] = "Draft not found for unpublished record"
                else:
                    payload = _payload_with_license(record, correct_license)
                    payload_differences = zenodo_payload_differences(
                        payload,
                        record,
                        {"rights", "additional_descriptions"},
                    )
                    if payload_differences:
                        log_entry["status"] = "blocked"
                        log_entry["reason"] = (
                            "Remote metadata cannot be preserved in an update payload"
                        )
                        log_entry["differences"] = payload_differences
                    elif dry_run:
                        console.print(
                            f"  [cyan]DRY RUN[/cyan] {record_id}: "
                            f"{current_license} → {correct_license}"
                        )
                        log_entry["status"] = "dry_run"
                    else:
                        draft_record = (
                            create_edit_draft(
                                zenodo_url,
                                record_id_text,
                                access_token,
                                user_agent,
                            )
                            if is_published
                            else record
                        )
                        payload = _payload_with_license(draft_record, correct_license)
                        payload_differences = zenodo_payload_differences(
                            payload,
                            draft_record,
                            {"rights", "additional_descriptions"},
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
                                record_id_text,
                                access_token,
                                user_agent,
                                payload,
                            )
                            if is_published:
                                publish_draft(
                                    zenodo_url,
                                    record_id_text,
                                    access_token,
                                    user_agent,
                                )
                            log_entry["status"] = "patched"
            except (requests.RequestException, ValueError) as exc:
                log_entry["status"] = "error"
                log_entry["error"] = str(exc)
                console.print(f"\n[red][FAILED][/red] Record {record_id}: {exc}")

            patch_log.append(log_entry)
            if log_entry["status"] in ("patched", "dry_run"):
                stats["patched"] += 1
            elif log_entry["status"] == "blocked":
                stats["blocked"] += 1
            elif log_entry["status"] == "error":
                stats["errors"] += 1
            progress.advance(task)
            time.sleep(REQUEST_DELAY)

    log_path = drafts_path.parent / "patch_license_log.json"
    with open(log_path, "w") as file:
        json.dump(patch_log, file, indent=2)

    console.print()
    console.print("[bold]Results:[/bold]")
    console.print(f"  Patched: {stats['patched']}")
    console.print(f"  Blocked: {stats['blocked']}")
    console.print(f"  Already correct: {stats['skipped_correct']}")
    console.print(f"  Skipped (failed): {stats['skipped_failed']}")
    console.print(f"  Skipped (no KG license): {stats['skipped_no_kg_license']}")
    console.print(f"  Errors: {stats['errors']}")
    console.print(f"  Log: {log_path}")


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Patch license metadata on Zenodo records"
    )
    parser.add_argument("drafts_json", type=Path, help="Path to drafts.json")
    parser.add_argument("kg_path", type=Path, help="Path to knowledge graph (kg.ttl)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show changes without applying"
    )
    args = parser.parse_args()
    patch_drafts(args.drafts_json, args.kg_path, dry_run=args.dry_run)
