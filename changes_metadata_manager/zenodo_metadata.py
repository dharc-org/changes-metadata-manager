# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>
#
# SPDX-License-Identifier: ISC

import re
from copy import deepcopy
from typing import NotRequired, TypedDict, cast

ENTITY_URI_PATTERN = re.compile(r"/itm/([^/]+)/ob\d+/\d+$")
STAGE_ARCHIVE_PATTERN = re.compile(r"-(raw|rawp|dcho|dchoo)\.zip$")


class ZenodoUpdatePayload(TypedDict):
    access: dict[str, object]
    files: dict[str, object]
    metadata: dict[str, object]
    custom_fields: NotRequired[dict[str, object]]


def _strip_vocabulary_titles(value: object) -> object:
    if isinstance(value, dict):
        if set(value) == {"id", "title"}:
            return {"id": value["id"]}
        return {str(key): _strip_vocabulary_titles(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_strip_vocabulary_titles(item) for item in value]
    return value


def build_zenodo_update_payload(record: dict) -> ZenodoUpdatePayload:
    remote_access = record["access"]
    access: dict[str, object] = {
        "record": remote_access["record"],
        "files": remote_access["files"],
    }
    if "embargo" in remote_access and remote_access["embargo"]["active"]:
        access["embargo"] = deepcopy(remote_access["embargo"])

    remote_files = record["files"]
    files: dict[str, object] = {"enabled": remote_files["enabled"]}
    for field in ("default_preview", "order"):
        if field in remote_files and remote_files[field] is not None:
            files[field] = deepcopy(remote_files[field])

    metadata = cast("dict[str, object]", _strip_vocabulary_titles(record["metadata"]))
    payload = ZenodoUpdatePayload(
        access=access,
        files=files,
        metadata=metadata,
    )
    if "custom_fields" in record:
        payload["custom_fields"] = deepcopy(record["custom_fields"])
    return payload


def extract_entity_id(record: dict) -> str:
    for identifier in record["metadata"]["identifiers"]:
        match = ENTITY_URI_PATTERN.search(identifier["identifier"])
        if match:
            return match.group(1)
    raise ValueError(
        f"No CHANGES entity URI found in identifiers: "
        f"{record['metadata']['identifiers']}"
    )


def extract_stage(record: dict) -> str:
    stages = {
        match.group(1)
        for filename in record["files"]["entries"]
        if (match := STAGE_ARCHIVE_PATTERN.search(filename))
    }
    if len(stages) != 1:
        raise ValueError(f"Expected one stage archive, found: {sorted(stages)}")
    return stages.pop()


def _value_differences(expected: object, actual: object, path: str) -> list[str]:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [path]
        differences: list[str] = []
        for key, value in expected.items():
            child_path = f"{path}/{key}"
            if key not in actual:
                differences.append(child_path)
            else:
                differences.extend(_value_differences(value, actual[key], child_path))
        return differences

    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return [path]
        differences = []
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            differences.extend(
                _value_differences(expected_item, actual_item, f"{path}/{index}")
            )
        return differences

    return [] if expected == actual else [path]


def zenodo_payload_differences(
    payload: ZenodoUpdatePayload,
    record: dict,
    ignored_metadata_fields: set[str],
) -> list[str]:
    expected_metadata = {
        key: value
        for key, value in payload["metadata"].items()
        if key not in ignored_metadata_fields
    }
    remote_metadata = {
        key: value
        for key, value in record["metadata"].items()
        if key not in ignored_metadata_fields
    }
    differences = [
        f"/metadata/{key}" for key in remote_metadata.keys() - expected_metadata.keys()
    ]
    differences.extend(
        _value_differences(expected_metadata, remote_metadata, "/metadata")
    )
    differences.extend(
        _value_differences(payload["access"], record["access"], "/access")
    )
    differences.extend(_value_differences(payload["files"], record["files"], "/files"))
    expected_custom_fields = (
        payload["custom_fields"] if "custom_fields" in payload else {}
    )
    remote_custom_fields = record["custom_fields"] if "custom_fields" in record else {}
    differences.extend(
        _value_differences(
            expected_custom_fields, remote_custom_fields, "/custom_fields"
        )
    )
    return sorted(differences)
