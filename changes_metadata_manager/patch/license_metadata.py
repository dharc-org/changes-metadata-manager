# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelomas@gmail.com>
#
# SPDX-License-Identifier: ISC

import argparse
import json
import re
import time
from pathlib import Path

import requests
import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from piccione.upload.on_zenodo import build_inveniordm_payload, update_draft_metadata

from changes_metadata_manager.folder_metadata_builder import load_kg
from changes_metadata_manager.zenodo_upload import (
    CC0_DISCLAIMER,
    LiteralBlockDumper,
    build_rights,
    extract_license_for_entity_stage,
)

console = Console()

STAGE_PATTERN = re.compile(r"-(raw|rawp|dcho|dchoo)\.yaml$")
ENTITY_URI_PATTERN = re.compile(r"/itm/([^/]+)/ob\d+/\d+$")


def _extract_stage_from_config_path(config_file: str) -> str:
    m = STAGE_PATTERN.search(config_file)
    assert m, f"Cannot extract stage from config path: {config_file}"
    return m.group(1)


def _extract_entity_id_from_config(config: dict) -> str:
    for entry in config["identifiers"]:
        m = ENTITY_URI_PATTERN.search(entry["identifier"])
        if m:
            return m.group(1)
    raise ValueError(f"No entity URI found in identifiers: {config['identifiers']}")


def _fetch_record_metadata(zenodo_url: str, draft_id: str, access_token: str, user_agent: str) -> dict:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": user_agent,
        "Accept": "application/vnd.inveniordm.v1+json",
    }
    response = requests.get(f"{zenodo_url}/records/{draft_id}/draft", headers=headers, timeout=30)
    if response.status_code == 404:
        response = requests.get(f"{zenodo_url}/records/{draft_id}", headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()["metadata"]


def _current_content_license(metadata: dict) -> str | None:
    for right in metadata.get("rights", []):
        title = right.get("title", {}).get("en", "")
        if "(Content license)" in title:
            link = right.get("link", "")
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
    for desc in metadata.get("additional_descriptions", []):
        if "D. Lgs. 42/2004" in desc.get("description", ""):
            return True
    return False


def _rebuild_additional_descriptions(
    current: list[dict], correct_license: str | None
) -> list[dict]:
    rebuilt = [d for d in current if "D. Lgs. 42/2004" not in d.get("description", "")]
    if correct_license == "cc0-1.0":
        rebuilt.append({
            "description": CC0_DISCLAIMER,
            "type": {"id": "notes"},
        })
    return rebuilt


def patch_drafts(
    drafts_path: Path,
    kg_path: Path,
    *,
    dry_run: bool = False,
) -> None:
    console.print(f"Loading KG from {kg_path}...")
    kg = load_kg(kg_path)

    with open(drafts_path) as f:
        drafts = json.load(f)

    stats = {"patched": 0, "skipped_correct": 0, "skipped_failed": 0, "errors": 0}
    patch_log: list[dict] = []

    entries_to_check = []
    for entry in drafts:
        if entry.get("status") == "failed":
            stats["skipped_failed"] += 1
            continue
        stage = _extract_stage_from_config_path(entry["config_file"])
        entries_to_check.append((entry, stage))

    console.print(f"Checking {len(entries_to_check)} drafts...")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    ) as progress:
        task = progress.add_task("Patching", total=len(entries_to_check))

        for entry, stage in entries_to_check:
            config_path = Path(entry["config_file"])
            draft_id = entry["draft_id"]
            zenodo_url = entry["zenodo_url"]
            access_token = entry["access_token"]
            user_agent = entry.get("user_agent", "changes-metadata-manager/1.0.0")
            progress.update(task, description=f"Draft {draft_id}")

            try:
                zenodo_metadata = _fetch_record_metadata(zenodo_url, str(draft_id), access_token, user_agent)

                entity_id = _extract_entity_id_from_config(zenodo_metadata)

                correct_license = extract_license_for_entity_stage(kg, entity_id, stage)
                current_license = _current_content_license(zenodo_metadata)

                needs_rights_fix = correct_license != current_license
                needs_disclaimer_fix = (correct_license == "cc0-1.0") != _has_cc0_disclaimer(zenodo_metadata)

                if not needs_rights_fix and not needs_disclaimer_fix:
                    stats["skipped_correct"] += 1
                    progress.advance(task)
                    continue

                new_rights = build_rights(correct_license)
                new_additional = _rebuild_additional_descriptions(
                    zenodo_metadata.get("additional_descriptions", []), correct_license
                )

                log_entry = {
                    "draft_id": draft_id,
                    "config_file": entry["config_file"],
                    "entity_id": entity_id,
                    "stage": stage,
                    "old_license": current_license,
                    "new_license": correct_license,
                    "rights_changed": needs_rights_fix,
                    "disclaimer_changed": needs_disclaimer_fix,
                }

                if dry_run:
                    console.print(f"  [cyan]DRY RUN[/cyan] {draft_id}: {current_license} → {correct_license}")
                    log_entry["status"] = "dry_run"
                    patch_log.append(log_entry)
                    stats["patched"] += 1
                    progress.advance(task)
                    continue

                with open(config_path) as f:
                    config = yaml.safe_load(f)

                config["rights"] = new_rights
                config["additional_descriptions"] = new_additional

                access = config["access"]
                payload = build_inveniordm_payload(config, access)
                update_draft_metadata(zenodo_url, access_token, str(draft_id), payload, user_agent)

                with open(config_path, "w") as f:
                    yaml.dump(config, f, Dumper=LiteralBlockDumper, default_flow_style=False, allow_unicode=True, sort_keys=False)

                log_entry["status"] = "patched"
                stats["patched"] += 1
                patch_log.append(log_entry)
            except Exception as exc:
                stats["errors"] += 1
                print(f"\n[FAILED] Draft {draft_id}: {exc}")

            progress.advance(task)
            time.sleep(2)

    log_path = drafts_path.parent / "patch_license_log.json"
    with open(log_path, "w") as f:
        json.dump(patch_log, f, indent=2)

    console.print()
    console.print(f"[bold]Results:[/bold]")
    console.print(f"  Patched: {stats['patched']}")
    console.print(f"  Already correct: {stats['skipped_correct']}")
    console.print(f"  Skipped (failed): {stats['skipped_failed']}")
    console.print(f"  Errors: {stats['errors']}")
    console.print(f"  Log: {log_path}")


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description="Patch license metadata on Zenodo drafts")
    parser.add_argument("drafts_json", type=Path, help="Path to drafts.json")
    parser.add_argument("kg_path", type=Path, help="Path to knowledge graph (kg.ttl)")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    args = parser.parse_args()
    patch_drafts(args.drafts_json, args.kg_path, dry_run=args.dry_run)
