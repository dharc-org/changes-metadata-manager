---
title: Folder metadata builder
description: Generate RDF metadata and provenance files from the knowledge graph
---

The folder metadata builder is the main entry point. It scans a folder hierarchy, extracts RDF triples from the knowledge graph for each object and stage, validates the output against SHACL shapes, and generates provenance snapshots.

## Usage

```bash
uv run python -m changes_metadata_manager.folder_metadata_builder <root_directory> [options]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `root_directory` | Yes | Root directory containing `Sala*/Folder/Stage/` |

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--structure`, `-s` | None | Path to a SharePoint JSON structure file. When provided, the script reads the folder hierarchy from this file instead of scanning the filesystem. |
| `--no-validate` | False | Skip SHACL validation of the generated metadata. By default, each `meta.ttl` is validated against the shapes in `data/shapes-chadap.ttl`. |
| `--merge-provenance` | None | Output path for a merged provenance file. When set, all individual `prov.trig` files are combined into a single TriG file at the given path. |

## How it works

The builder walks through every folder matching the `Sala*/Folder/Stage/` pattern and, for each one:

1. **Extracts the object identifier** from the folder name. Folder names follow patterns like `S1-01-CNR_CartaNautica`, where the numeric part after the sala prefix (`01`) is the object NR. A mapping table (`FOLDER_TO_ID`) handles non-standard names.

2. **Filters the knowledge graph**. The input graph (`data/kg.ttl`) contains triples for all objects and all processing steps. The builder selects only the triples that belong to the current object and the steps associated with the current stage. Stages are cumulative: `dcho` includes steps 00, 01, and 02, so its metadata contains everything from `raw` and `rawp` as well.

3. **Writes `meta.ttl`**. The filtered triples are serialized as Turtle and written to the stage folder.

4. **Validates against SHACL shapes**. Unless `--no-validate` is passed, the output is checked against `data/shapes-chadap.ttl` using pyshacl. Validation errors are reported but do not stop the process.

5. **Generates `prov.trig`**. For each subject in the metadata, a provenance snapshot is created as a named graph. The snapshot records who created the entity, when, and from what source. See [Architecture](/changes-metadata-manager/reference/architecture/) for details on the provenance model.

## Stage-to-step mapping

Each stage includes triples from one or more processing steps:

| Stage | Steps included | What it contains |
|-------|---------------|------------------|
| `raw` | 00 | Original acquisition data |
| `rawp` | 00, 01 | Raw + initial processing |
| `dcho` | 00, 01, 02 | Everything up to the refined model |
| `dchoo` | 00, 01, 02, 03, 04, 05, 06 | Full pipeline including optimization and metadata authoring |

## Skipped folders

Some folders are excluded from processing because they do not follow the standard structure:

- `S1-CNR_SoffittoSala1`
- `S5-B basso-DICAM_FanoneBalenaAlto`
- `materials`
- `sala 4`
- `_files`

## Examples

Generate metadata for a local folder tree:

```bash
uv run python -m changes_metadata_manager.folder_metadata_builder /data/aldrovandi
```

Use a SharePoint structure file and skip validation:

```bash
uv run python -m changes_metadata_manager.folder_metadata_builder /data/aldrovandi \
    --structure data/structure.json \
    --no-validate
```

Generate everything and also produce a single merged provenance file:

```bash
uv run python -m changes_metadata_manager.folder_metadata_builder /data/aldrovandi \
    --structure data/structure.json \
    --merge-provenance /data/aldrovandi/provenance_all.trig
```
