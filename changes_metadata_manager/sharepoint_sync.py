import argparse
import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

console = Console()


def load_config(config_path):
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_site_relative_url(site_url):
    return "/" + "/".join(site_url.rstrip("/").split("/")[3:])


def sort_structure(obj):
    if isinstance(obj, dict):
        sorted_dict = {}
        for key in sorted(obj.keys(), key=lambda k: (k == "_files", k)):
            sorted_dict[key] = sort_structure(obj[key])
        return sorted_dict
    elif isinstance(obj, list):
        return sorted(obj)
    return obj


def request_with_retry(client, url, max_retries=5):  # pragma: no cover
    for attempt in range(max_retries):
        resp = client.get(url)
        if resp.status_code == 429:
            wait_time = 2**attempt
            time.sleep(wait_time)
            continue
        resp.raise_for_status()
        return resp
    raise Exception(f"Rate limited after {max_retries} retries for {url}")


@contextmanager
def stream_with_retry(client, url, max_retries=5):  # pragma: no cover
    for attempt in range(max_retries):
        with client.stream("GET", url) as resp:
            if resp.status_code == 429:
                wait_time = 2**attempt
                time.sleep(wait_time)
                continue
            if resp.status_code >= 400:
                resp.raise_for_status()
            yield resp
            return
    raise Exception(f"Rate limited after {max_retries} retries for {url}")


def get_folder_contents(client, site_url, folder_path):
    api_url = f"{site_url}/_api/web/GetFolderByServerRelativeUrl('{folder_path}')"

    folders_resp = request_with_retry(client, f"{api_url}/Folders")
    folders_data = folders_resp.json()["d"]["results"]

    files_resp = request_with_retry(client, f"{api_url}/Files")
    files_data = files_resp.json()["d"]["results"]

    return folders_data, files_data


def get_folder_structure(client, site_url, folder_path):
    result = {}

    folders, files = get_folder_contents(client, site_url, folder_path)

    for folder in folders:
        name = folder["Name"]
        if name.startswith("_") or name == "Forms":
            continue
        subfolder_path = folder["ServerRelativeUrl"]
        result[name] = get_folder_structure(client, site_url, subfolder_path)

    file_list = [f["Name"] for f in files]
    if file_list:
        result["_files"] = file_list

    return result


def process_folder(client, folder_path, site_url, progress, task_id):
    folder_name = folder_path.split("/")[-1]
    progress.update(task_id, description=f"Scanning {folder_name}...")
    structure = get_folder_structure(client, site_url, folder_path)
    progress.advance(task_id)
    return folder_name, folder_path, structure


def extract_structure(client, site_url, folders, progress):
    site_relative_url = get_site_relative_url(site_url)

    task_id = progress.add_task("Discovering...", total=len(folders))

    results = []
    for folder in folders:
        normalized = folder if folder.startswith("/") else "/" + folder
        folder_path = site_relative_url + normalized
        result = process_folder(client, folder_path, site_url, progress, task_id)
        results.append(result)

    structure = {name: folder_structure for name, _, folder_structure in results}
    folder_paths = {name: path for name, path, _ in results}
    return sort_structure(structure), folder_paths


def collect_files_from_structure(structure, folder_paths):
    files = []

    def traverse(node, current_path, base_server_path):
        for key, value in node.items():
            if key == "_files":
                for filename in value:
                    server_path = f"{base_server_path}/{current_path}/{filename}" if current_path else f"{base_server_path}/{filename}"
                    local_path = f"{current_path}/{filename}" if current_path else filename
                    files.append((server_path, local_path))
            elif isinstance(value, dict):
                new_path = f"{current_path}/{key}" if current_path else key
                traverse(value, new_path, base_server_path)

    for folder_name, folder_structure in structure.items():
        base_path = folder_paths[folder_name]
        traverse({folder_name: folder_structure}, "", base_path.rsplit("/", 1)[0])

    return files


def download_file(client, site_url, file_server_relative_url, local_path):
    url = f"{site_url}/_api/web/GetFileByServerRelativeUrl('{file_server_relative_url}')/$value"

    local_path.parent.mkdir(parents=True, exist_ok=True)

    with stream_with_retry(client, url) as response:
        with open(local_path, "wb") as f:
            for chunk in response.iter_bytes(chunk_size=8192):
                f.write(chunk)

    return local_path.stat().st_size


def download_all_files(client, site_url, structure, output_dir, folder_paths):
    files = collect_files_from_structure(structure, folder_paths)
    total = len(files)

    downloaded = 0
    skipped = 0
    failed = 0

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Downloading...", total=total)

        for server_path, local_rel_path in files:
            local_path = output_dir / local_rel_path
            progress.update(task_id, description=f"[cyan]{local_rel_path}")

            if local_path.exists():
                skipped += 1
                progress.advance(task_id)
                continue

            try:
                download_file(client, site_url, server_path, local_path)
                downloaded += 1
            except Exception as e:
                console.print(f"[red]Failed: {local_rel_path} ({e})")
                failed += 1

            progress.advance(task_id)

    console.print(f"Downloaded: {downloaded}, Skipped: {skipped}, Failed: {failed}")


def main():  # pragma: no cover
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--structure-only", action="store_true")
    parser.add_argument("--structure", type=Path, help="Path to existing structure JSON file")
    args = parser.parse_args()

    config = load_config(args.config)

    site_url = config["site_url"]
    fedauth = config["fedauth"]
    rtfa = config["rtfa"]
    folders = config["folders"]

    if args.structure:
        console.print("[bold blue][Phase 1][/] Loading structure from file...")
        with open(args.structure) as f:
            data = json.load(f)
        structure = data["structure"]
        folder_paths = data["folder_paths"]
        console.print(f"Loaded structure from {args.structure}")
    else:
        console.print("[bold blue][Phase 1][/] Discovering files...")
        json_headers = {
            "Cookie": f"FedAuth={fedauth}; rtFa={rtfa}",
            "Accept": "application/json;odata=verbose",
        }

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            with httpx.Client(headers=json_headers) as client:
                structure, folder_paths = extract_structure(client, site_url, folders, progress)

        args.output_dir.mkdir(parents=True, exist_ok=True)

        structure_file = args.output_dir / "structure.json"
        output = {
            "site_url": site_url,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "structure": structure,
            "folder_paths": folder_paths,
        }
        with open(structure_file, "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        console.print(f"Structure saved to {structure_file}")

    if args.structure_only:
        return

    console.print("[bold blue][Phase 2][/] Downloading files...")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    download_headers = {
        "Cookie": f"FedAuth={fedauth}; rtFa={rtfa}",
    }

    with httpx.Client(headers=download_headers, timeout=300) as client:
        download_all_files(client, site_url, structure, args.output_dir, folder_paths)


if __name__ == "__main__":  # pragma: no cover
    main()
