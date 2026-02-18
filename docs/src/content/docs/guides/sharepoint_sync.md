---
title: SharePoint sync
description: Sync the folder structure from SharePoint using piccione
---

When the local folder structure is not available, you can pull it from SharePoint using [piccione](https://github.com/opencitations/piccione).

## Configuration

Create a YAML file with your SharePoint credentials:

```yaml
site_url: https://liveunibo.sharepoint.com/sites/PE5-Spoke4-CaseStudyAldrovandi
fedauth: <FedAuth_cookie_value>
rtfa: <rtFa_cookie_value>
folders:
  - /Shared Documents/Sala1
  - /Shared Documents/Sala2
  - /Shared Documents/Sala3
  - /Shared Documents/Sala4
  - /Shared Documents/Sala5
  - /Shared Documents/Sala6
```

The `fedauth` and `rtfa` values are authentication cookies. You can extract them from your browser's developer tools after logging into SharePoint. Open the Network tab, find a request to the SharePoint site, and look for the `FedAuth` and `rtFa` cookies in the request headers.

These cookies expire after some time, so you may need to refresh them periodically.

## Syncing structure only

If you only need the folder hierarchy (no actual files), use the `--structure-only` flag:

```bash
uv run python -m piccione.download.from_sharepoint config.yaml /output/dir --structure-only
```

This produces a `structure.json` file describing the full directory tree. You can then pass it to the metadata builder:

```bash
uv run python -m changes_metadata_manager.folder_metadata_builder /output/dir \
    --structure /output/dir/structure.json
```

## Syncing structure and files

To download the actual files as well:

```bash
uv run python -m piccione.download.from_sharepoint config.yaml /output/dir
```

This creates a local copy of the folder tree with all files. You can then run the metadata builder directly on it without the `--structure` flag.
