<!--
SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>

SPDX-License-Identifier: CC-BY-4.0
-->

# CHANGES Metadata Manager

Generate RDF metadata and provenance snapshots for the Aldrovandi Digital Twin.

- [Get started](01-getting-started.md)
- [View on GitHub](https://github.com/dharc-org/changes-metadata-manager)

## RDF metadata extraction

Filters triples from a knowledge graph by object and processing stage, producing `meta.ttl` files validated against SHACL shapes.

## Provenance snapshots

Generates PROV-O compliant provenance in TriG format, following the OpenCitations Data Model.

## Zenodo archival

Packages digitized objects into ZIP archives with InvenioRDM-compatible metadata and uploads them to Zenodo.

## SharePoint integration

Syncs folder structures from SharePoint via [piccione](https://github.com/opencitations/piccione), allowing metadata generation without local file copies.
