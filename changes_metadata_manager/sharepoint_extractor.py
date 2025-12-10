import argparse
import json
import os
import time
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv


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
            wait_time = 2 ** attempt
            time.sleep(wait_time)
            continue
        resp.raise_for_status()
        return resp
    raise Exception(f"Rate limited after {max_retries} retries for {url}")


def get_folder_contents(client, site_url, folder_path):
    api_url = f"{site_url}/_api/web/GetFolderByServerRelativeUrl('{folder_path}')"

    folders_resp = request_with_retry(client, f"{api_url}/Folders")
    folders_data = folders_resp.json()["d"]["results"]

    files_resp = request_with_retry(client, f"{api_url}/Files")
    files_data = files_resp.json()["d"]["results"]

    return folders_data, files_data


def get_folder_structure(client, site_url, folder_path, sala_name, depth=0):
    result = {}

    folder_name = folder_path.split("/")[-1]
    if depth <= 1:
        print(f"[{sala_name}] {'  ' * depth}{folder_name}")

    folders, files = get_folder_contents(client, site_url, folder_path)

    for folder in folders:
        name = folder["Name"]
        if name.startswith("_") or name == "Forms":
            continue
        subfolder_path = folder["ServerRelativeUrl"]
        result[name] = get_folder_structure(client, site_url, subfolder_path, sala_name, depth + 1)

    file_list = [f["Name"] for f in files]
    if file_list:
        result["_files"] = file_list

    return result


def process_sala(client, sala_name, site_url, docs_folder):
    sala_path = f"{docs_folder}/{sala_name}"
    print(f"[{sala_name}] Starting...")
    structure = get_folder_structure(client, site_url, sala_path, sala_name)
    print(f"[{sala_name}] Done")
    return sala_name, structure


def extract_all_sale(client, site_url, sale_names):
    site_relative_url = "/" + "/".join(site_url.split("/")[3:])
    docs_folder = f"{site_relative_url}/Shared Documents"

    print(f"Extracting {len(sale_names)} sale sequentially...")

    results = []
    for sala in sale_names:
        result = process_sala(client, sala, site_url, docs_folder)
        results.append(result)

    structure = {sala_name: sala_structure for sala_name, sala_structure in results}
    return sort_structure(structure)


def main():  # pragma: no cover
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "-o", default="data/sharepoint_structure.json")
    args = parser.parse_args()

    load_dotenv()

    site_url = os.getenv("SHAREPOINT_SITE_URL")
    if not site_url:
        raise ValueError("SHAREPOINT_SITE_URL must be set in .env")

    fedauth = os.getenv("SHAREPOINT_FEDAUTH")
    rtfa = os.getenv("SHAREPOINT_RTFA")
    if not fedauth or not rtfa:
        raise ValueError("SHAREPOINT_FEDAUTH and SHAREPOINT_RTFA must be set in .env")

    headers = {
        "Cookie": f"FedAuth={fedauth}; rtFa={rtfa}",
        "Accept": "application/json;odata=verbose",
    }

    sale = ["Sala1", "Sala2", "Sala3", "Sala4", "Sala5", "Sala6"]

    with httpx.Client(headers=headers) as client:
        structure = extract_all_sale(client, site_url, sale)

    output = {
        "site_url": site_url,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "structure": structure,
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nStructure saved to {args.output}")


if __name__ == "__main__": # pragma: no cover
    main()
