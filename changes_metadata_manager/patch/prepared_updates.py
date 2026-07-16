# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import json
import os
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import cast

import requests
import yaml
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)

from changes_metadata_manager.folder_metadata_builder import extract_id_from_folder_name
from changes_metadata_manager.zenodo_api import (
    ZenodoRecordCache,
    create_edit_draft,
    publish_draft,
    update_draft,
)
from changes_metadata_manager.zenodo_metadata import (
    ZenodoUpdatePayload,
    extract_stage_from_filenames,
)
from changes_metadata_manager.zenodo_upload import _atomic_write_json

console = Console()

CACHE_FILENAME = "creator_names_cache.sqlite3"
MANIFEST_FILENAME = "manifest.json"
APPLY_LOG_FILENAME = "apply_log.json"
PREPARE_STATUSES = {"would_patch", "already_correct", "blocked", "error"}
REQUEST_DELAY = 2


def write_payload(path: Path, payload: ZenodoUpdatePayload) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as file:
        yaml.safe_dump(payload, file, sort_keys=False, allow_unicode=True)
    os.replace(tmp_path, path)


def load_manifest(path: Path) -> list[dict]:
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


def prepare_output_directory(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_names = {path.name for path in output_dir.iterdir()}
    if not existing_names:
        return
    if MANIFEST_FILENAME not in existing_names:
        raise ValueError(f"Output directory contains unmanaged files: {output_dir}")

    manifest = load_manifest(output_dir / MANIFEST_FILENAME)
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


def load_package_config(config_path: Path) -> dict:
    with open(config_path) as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError(f"Invalid package config: {config_path}")
    return config


def _package_archive_path(config: dict, config_path: Path) -> Path:
    archive_paths = config["files"]
    if len(archive_paths) != 1:
        raise ValueError(f"Expected one package archive in config: {config_path}")
    return Path(archive_paths[0])


def _extract_archive_entity_ids(archive_path: Path) -> list[str]:
    with zipfile.ZipFile(archive_path) as archive:
        folder_names = {name.split("/", 1)[0] for name in archive.namelist()}
    return sorted(
        {extract_id_from_folder_name(folder_name) for folder_name in folder_names}
    )


def extract_package_entity_ids(config_path: Path) -> list[str]:
    config = load_package_config(config_path)
    return _extract_archive_entity_ids(_package_archive_path(config, config_path))


def extract_package_context(config_path: Path) -> tuple[dict, list[str], str]:
    config = load_package_config(config_path)
    archive_path = _package_archive_path(config, config_path)
    stage = extract_stage_from_filenames([archive_path.name])
    return config, _extract_archive_entity_ids(archive_path), stage


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
        required_fields = {"zenodo_url", "access_token", "user_agent", "status"}
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


def apply_prepared_updates(drafts_path: Path, output_dir: Path) -> Path:
    manifest = load_manifest(output_dir / MANIFEST_FILENAME)
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
