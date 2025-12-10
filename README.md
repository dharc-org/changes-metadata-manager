# Aldrovandi Provenance

[![Tests](https://github.com/dharc-org/aldrovandi-provenance/actions/workflows/run-tests.yml/badge.svg)](https://github.com/dharc-org/aldrovandi-provenance/actions/workflows/run-tests.yml)
[![Coverage](https://byob.yarr.is/arcangelo7/badges/dharc-org-aldrovandi-provenance-coverage-master)](https://dharc-org.github.io/aldrovandi-provenance/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Repo Size](https://img.shields.io/github/repo-size/dharc-org/aldrovandi-provenance)](https://github.com/dharc-org/aldrovandi-provenance)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-ISC-blue.svg)](LICENSE)

This repository contains tools for managing provenance information for cultural heritage data using the CHAD-AP (Cultural Heritage Acquisition and Digitisation Application Profile) model.

## Overview

The project provides tools for generating provenance snapshots from RDF data, conforming to the [CHAD-AP specification](https://dharc-org.github.io/chad-ap/current/chad-ap.html).

The provenance model implemented in this project is based on the OpenCitations Data Model:

> Daquino, Marilena; Massari, Arcangelo; Peroni, Silvio; Shotton, David (2018). The OpenCitations Data Model. figshare. Online resource. [https://doi.org/10.6084/m9.figshare.3443876.v8](https://doi.org/10.6084/m9.figshare.3443876.v8)

The primary feature is generating provenance snapshots from RDF data in various formats, where:
- Provenance information is organized into named graphs
- Each subject in the input data receives its own provenance graph 
- Snapshot entities are created to represent the state of cultural heritage objects
- Provenance metadata includes generation time and responsible agent information

## Installation

Requirements:
- Python 3.10+
- uv (recommended for development)

### Using uv

If uv is not already installed, please follow the installation instructions at [https://docs.astral.sh/uv/getting-started/installation/](https://docs.astral.sh/uv/getting-started/installation/)

```bash
# Clone the repository
git clone https://github.com/dharc-org/aldrovandi-provenance.git
cd aldrovandi-provenance

# Install dependencies with uv
uv sync
```

## Usage

### Building folder metadata

The `folder_metadata_builder.py` script processes a folder structure and generates metadata and provenance files for each stage.

Prerequisites:
- A folder structure with the format `<root>/Sala*/Folder/Stage/`
- Knowledge graph in Turtle format (`data/kg.ttl`)

Usage:

```bash
python -m aldrovandi_provenance.folder_metadata_builder <root_directory>
```

The script scans the folder structure and generates for each stage:
- `meta.ttl`: Metadata extracted from the knowledge graph
- `prov.nq`: Provenance snapshots for the metadata

Supported stages: raw, rawp, dcho, dchoo.

### Development: SharePoint structure extraction

During development, when the local folder structure is not available, you can use SharePoint as the source of the folder structure.

Configuration:

```bash
cp .env.example .env
```

Edit `.env` with your SharePoint credentials:
- `SHAREPOINT_SITE_URL`: SharePoint site URL
- `SHAREPOINT_FEDAUTH`: FedAuth cookie (from browser DevTools)
- `SHAREPOINT_RTFA`: rtFa cookie (from browser DevTools)

Extract the structure:

```bash
python -m aldrovandi_provenance.sharepoint_extractor [-o OUTPUT_FILE]
```

This outputs a JSON file (default: `data/sharepoint_structure.json`) containing the folder hierarchy.

Then run the metadata builder with the `--structure` flag:

```bash
python -m aldrovandi_provenance.folder_metadata_builder <root_directory> --structure data/sharepoint_structure.json
```

When using `--structure`, the script uses the JSON file to determine the folder hierarchy instead of scanning the filesystem.

## Development

### Running Tests

```bash
pytest -xvs tests/
```
