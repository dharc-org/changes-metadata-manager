---
title: Zenodo upload
description: Package and upload digitized objects to Zenodo
---

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

- `zips/`: one ZIP per entity and stage (e.g., `S1-01-CNR_CartaNautica-raw.zip`)
- `configs/`: one YAML per entity and stage, ready for piccione

Each ZIP preserves the original folder names and includes:

- `meta.ttl` and `prov.trig` (always included)
- Data files (3D models, textures, scans) only for stages that have a license assigned in the knowledge graph

For grouped entities (e.g., objects 98a, 98b, 98c), all variants go into a single ZIP.

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

- **datacollector**: people who performed the digitization (steps 00-04, 06)
- **datacurator**: people who authored the metadata (step 05)

Metadata authors from step 05 appear on every record, regardless of stage. The creator list is resolved against `data/creators_lookup.yaml`, which maps RDF names to structured fields (`family_name`, `given_name`, `affiliation`, `orcid`).

### License handling

Each record gets two license entries in the `rights` field:

1. A CC0 license for the metadata files (`meta.ttl`, `prov.trig`), always present
2. A content license for the data files, taken from the knowledge graph (typically CC-BY 4.0 or CC-BY-NC 4.0)

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

## Full workflow

A typical run looks like this:

```bash
# 1. Generate metadata and provenance
uv run python -m changes_metadata_manager.folder_metadata_builder /data/aldrovandi

# 2. Package everything for Zenodo
uv run python -m changes_metadata_manager.zenodo_upload prepare \
    /data/aldrovandi zenodo_config.yaml

# 3. Upload as drafts (review before publishing)
uv run python -m changes_metadata_manager.zenodo_upload upload zenodo_output/configs

# 4. Or upload and publish directly
uv run python -m changes_metadata_manager.zenodo_upload upload zenodo_output/configs --publish
```
