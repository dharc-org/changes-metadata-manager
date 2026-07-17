<!--
SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>

SPDX-License-Identifier: CC-BY-4.0
-->

# Zenodo upload

The Zenodo upload module has two subcommands: `prepare` builds ZIP archives and YAML configuration files, and `upload` sends them to Zenodo through piccione's InvenioRDM integration.

## Preparing packages

```bash
uv run python -m changes_metadata_manager.zenodo_upload prepare \
    <root_directory> <zenodo_config> [options]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `root_directory` | Yes | Root directory with `Sala*/Folder/Stage/` structure |
| `zenodo_config` | Yes | Path to the base Zenodo configuration YAML (see below) |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--output`, `-o` | `zenodo_output` | Output directory for ZIPs and configs |

### What it produces

The command creates two subdirectories under the output path:

- `zips/`: one ZIP per Zenodo group and stage (e.g., `S1-01-CNR_CartaNautica-raw.zip`)
- `configs/`: one YAML per Zenodo group and stage, ready for piccione

Each ZIP preserves the original folder names and includes:

- `meta.ttl` and `prov.trig` (always included)
- Data files (3D models, textures, scans) only for stages that have a license assigned in the knowledge graph

The `prepare` command follows the same grouping used by the records published on Zenodo. Numeric IDs with an alphabetic suffix are packaged under their base number: the `27` ZIP contains the folders for `27a` through `27f`, and the `74` ZIP contains the folders for `74a` through `74e`.

### Base configuration file

The base Zenodo config (`zenodo_config.yaml`) provides fields that apply to every record. Here is a trimmed example:

```yaml
zenodo_url: https://zenodo.org/api
access_token: YOUR_TOKEN
user_agent: changes-metadata-manager/1.0.0

language: ita
version: "1.0.0"
community: project-changes

keywords:
  - PNRR CHANGES
  - digital cultural heritage
  - CHAD-AP

related_identifiers:
  - identifier: "10.3724/2096-7004.di.2024.0061"
    relation: isdocumentedby
    resource_type: publication-article

locations:
  - lat: 44.49702
    lon: 11.35261
    place: "Bologna, Italy"
    description: "Palazzo Poggi Museum, University of Bologna"

notes: |
  Funding and project context.

method: |
  Description of the acquisition workflow.
```

Fields like `keywords`, `related_identifiers`, `locations`, `notes`, and `method` are propagated into each per-entity config. The `prepare` command fills in the rest automatically: title, description, creators (with ORCID and roles), license, resource type, and an identifier linking back to the entity URI.

### Creator roles

Creators are assigned DataCite roles based on their contribution:

- **researcher**: people who performed the digitization (steps 00-04, 06)
- **datacurator**: people who authored the metadata (step 05)

Metadata authors from step 05 appear on every record, regardless of stage. The creator list is resolved against `data/creators_lookup.yaml`, which maps RDF names to structured fields (`family_name`, `given_name`, `affiliation`, `orcid`).

### License handling

Each record gets two license entries in the `rights` field:

1. A CC0 license for the metadata files (`meta.ttl`, `prov.trig`), always present
2. A content license for the data files, taken from the knowledge graph (typically CC-BY 4.0 or CC-BY-NC 4.0)

When a stage has no content license, the generated record contains metadata and provenance files only. Its note is selected from the knowledge graph:

- If the activity defining that stage exists, the note states that the holding institution did not grant permission to publish the digital object files.
- If the defining activity is absent, the note states that the digital object came from an existing platform or was provided directly by colleagues without formal permission to republish the original files.

## Uploading to Zenodo

```bash
uv run python -m changes_metadata_manager.zenodo_upload upload \
    <configs_dir> [--publish]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `configs_dir` | Yes | Directory containing YAML config files (typically `zenodo_output/configs`) |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--publish` | False | Publish records after uploading. Without this flag, records are created as drafts. |

The upload command iterates over all YAML files in the directory (sorted alphabetically) and calls piccione's `on_zenodo` module for each one. Each config points to its ZIP file and contains the full InvenioRDM metadata, so no further input is needed.

A `drafts.json` file is written after every successful upload, regardless of `--publish`. Each entry tracks the record status (`uploaded`, `published`, or `failed`), the draft ID, and Zenodo credentials. A 2-second pause between each upload keeps request rates within Zenodo's API limits.

### Resume after interruption

Both `upload` and `publish-drafts` support automatic resume. If the process is interrupted (crash, network failure, manual stop), re-running the same command picks up where it left off: records already completed are skipped, and previously failed records are retried.

State is persisted to `drafts.json` atomically after each record, so even a hard crash loses at most one in-progress upload.

If an upload fails, the error is recorded in `drafts.json` and the batch continues with the remaining configs. A summary at the end reports how many succeeded, were skipped, and failed.

## Publishing drafts

To publish records that were previously uploaded as drafts:

```bash
uv run python -m changes_metadata_manager.zenodo_upload publish-drafts \
    <drafts_file>
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `drafts_file` | Yes | Path to `drafts.json` produced by a previous `upload` run |

This reads the saved draft IDs and publishes each one through the Zenodo API. Already-published records are skipped, and records that failed during a previous publish attempt are retried.

## Exporting the DMP CSV

Generate the CSV table for the Data Management Plan from the current published
metadata on Zenodo:

```bash
uv run python -m changes_metadata_manager.export_zenodo_csv \
    <drafts_file> [--output <csv_file>]
```

`drafts.json` provides the initial record IDs, Zenodo endpoint, and credentials.
Each ID is resolved through Zenodo's `versions/latest` endpoint. Titles, creators,
resource types, publication dates, DOIs, URLs, publishers, and licenses are read
from the latest published versions. The default output path is `doi_table.csv`
next to `drafts.json`.

The export stops without replacing an existing CSV if any tracked record cannot
be retrieved from the public record endpoint. Entries for failed uploads, which
have no record ID, are skipped.

## Full workflow

A typical run looks like this:

```bash
# 1. Generate metadata and provenance
uv run python -m changes_metadata_manager.folder_metadata_builder /data/aldrovandi

# 2. Package everything for Zenodo
uv run python -m changes_metadata_manager.zenodo_upload prepare \
    /data/aldrovandi zenodo_config.yaml

# 3. Upload as drafts
uv run python -m changes_metadata_manager.zenodo_upload upload zenodo_output/configs

# 4. Review drafts on Zenodo, then publish
uv run python -m changes_metadata_manager.zenodo_upload publish-drafts zenodo_output/drafts.json

# 5. Export the published metadata for the DMP
uv run python -m changes_metadata_manager.export_zenodo_csv zenodo_output/drafts.json
```

Alternatively, pass `--publish` at step 3 to upload and publish in one go:

```bash
uv run python -m changes_metadata_manager.zenodo_upload upload zenodo_output/configs --publish
```
