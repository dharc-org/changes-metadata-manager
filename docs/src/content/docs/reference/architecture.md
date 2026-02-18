---
title: Architecture
description: How the system processes metadata and generates provenance
---

## Overview

The CHANGES Metadata Manager sits between a knowledge graph and a set of folders representing digitized cultural heritage objects. It reads RDF triples from the graph, slices them by object and processing stage, writes the result to disk, and optionally packages everything for deposit on Zenodo.

The input knowledge graph (`data/kg.ttl`) is not produced by this tool. It comes from [morph-kgc-changes-metadata](https://github.com/dharc-org/morph-kgc-changes-metadata), which maps CSV spreadsheets into RDF following the [CHAD-AP ontology](https://dharc-org.github.io/chad-ap/current/chad-ap.html).

## Data flow

```
CSV spreadsheets
      |
      v
morph-kgc-changes-metadata  -->  data/kg.ttl
                                      |
                                      v
              folder_metadata_builder (this tool)
              |                       |
              v                       v
          meta.ttl               prov.trig
          (per stage)            (per stage)
              |                       |
              v                       v
          zenodo_upload.prepare
              |
              v
          ZIP + YAML config (per entity+stage)
              |
              v
          zenodo_upload.upload  -->  Zenodo
```

## Modules

### folder_metadata_builder

The main orchestrator. It:

1. Loads the knowledge graph once into memory
2. Walks the folder structure on disk
3. For each `Sala/Folder/Stage` combination, extracts the object NR from the folder name, selects the relevant processing steps, and filters the graph accordingly
4. Writes `meta.ttl` (the filtered triples) and runs SHACL validation
5. Calls `generate_provenance_snapshots()` to produce `prov.trig`

The folder-to-ID mapping is largely automatic (the NR is parsed from the folder name), but about 200 folders have non-standard names and are handled through a hardcoded lookup table.

### generate_provenance

Takes a directory containing RDF files, loads all of them into a single graph, and creates a provenance snapshot for each subject. Every snapshot is a named graph containing:

- `prov:specializationOf` pointing to the original entity
- `prov:generatedAtTime` with the current timestamp
- `prov:wasAttributedTo` linking to the responsible agent
- `prov:hadPrimarySource` linking to the data source
- `dcterms:description` with a creation note

The provenance model follows the [OpenCitations Data Model](https://doi.org/10.6084/m9.figshare.3443876.v8), which uses PROV-O named graphs to track entity history.

### zenodo_upload

Handles two tasks:

- **prepare**: walks the same folder structure, creates one ZIP per entity+stage (including data files only when a license exists), and writes a YAML config file for each. Creators are resolved from `data/creators_lookup.yaml` with roles assigned by step type.
- **upload**: reads the YAML configs and calls piccione's InvenioRDM module to create records on Zenodo.

## Key data files

| File | Purpose |
|------|---------|
| `data/kg.ttl` | Knowledge graph with all RDF triples |
| `data/shapes-chadap.ttl` | SHACL shapes for metadata validation |
| `data/creators_lookup.yaml` | Maps creator names from RDF to structured InvenioRDM fields (family name, given name, affiliation, ORCID) |
| `zenodo_config.yaml` | Base Zenodo record configuration |

## SHACL validation

Every `meta.ttl` file is validated against the CHAD-AP shapes using [pyshacl](https://github.com/RDFLib/pySHACL). The validation checks that the metadata conforms to the expected CIDOC-CRM patterns defined by the ontology. Validation failures are reported with details (focus node, path, message) but do not stop the pipeline, since some objects may legitimately have incomplete metadata.
