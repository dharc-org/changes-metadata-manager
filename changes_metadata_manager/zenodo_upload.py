import argparse
import re
import zipfile
from collections import defaultdict
from pathlib import Path

import yaml
from rdflib import Graph, URIRef
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from piccione.upload.on_zenodo import main as piccione_upload

from changes_metadata_manager.folder_metadata_builder import (
    BASE_URI,
    FOLDER_TO_ID,
    KG_PATH,
    SKIP_FOLDERS,
    STAGE_STEPS,
    extract_id_from_folder_name,
    load_kg,
    load_structure,
    scan_folder_structure,
)


STEP_TO_STAGE = {
    "00": "raw",
    "01": "rawp",
    "02": "dcho",
    "03": "dchoo",
    "04": "dchoo",
    "05": "dchoo",
    "06": "dchoo",
}

CRM = "http://www.cidoc-crm.org/cidoc-crm/"
P70I = URIRef(f"{CRM}P70i_is_documented_in")
P3_HAS_NOTE = URIRef(f"{CRM}P3_has_note")


def extract_licensed_entity_stages(graph: Graph) -> set[tuple[str, str]]:
    pattern = re.compile(rf"^{re.escape(BASE_URI)}/lic/([^/]+)/(\d{{2}})/1$")
    licensed = set()
    for s, p, o in graph.triples((None, P70I, None)):
        match = pattern.match(str(s))
        if match:
            entity_id, step = match.groups()
            stage = STEP_TO_STAGE.get(step)
            if stage:
                licensed.add((entity_id, stage))
    return licensed


def group_folders_by_entity(structure: dict) -> dict[str, list[tuple[str, str, dict]]]:
    groups = defaultdict(list)
    for sala_name, sala_items in structure["structure"].items():
        for folder_name, subfolders in sala_items.items():
            if folder_name in SKIP_FOLDERS:
                continue
            entity_id = extract_id_from_folder_name(folder_name)
            # Special IDs (ptb, vetrina_1_alto_n_1, etc.) are kept as-is.
            # Letter-suffixed IDs (27a, 74b) are grouped by stripping the suffix.
            if entity_id in FOLDER_TO_ID.values():
                base_id = entity_id
            else:
                base_id = entity_id.rstrip("abcdefghijklmnopqrstuvwxyz")
            groups[base_id].append((sala_name, folder_name, subfolders))
    return dict(groups)


def create_entity_zip(
    entity_id: str,
    folders: list[tuple[str, str, dict]],
    root: Path,
    licensed_stages: set[tuple[str, str]],
    output_dir: Path,
) -> Path:
    zip_path = output_dir / f"{entity_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for sala_name, folder_name, stages_dict in folders:
            for stage_name in stages_dict:
                stage_key = stage_name.lower()
                if stage_key not in STAGE_STEPS:
                    continue
                stage_dir = root / sala_name / folder_name / stage_name
                has_license = (entity_id, stage_key) in licensed_stages
                for file_path in stage_dir.iterdir():
                    if not file_path.is_file():
                        continue
                    if has_license or file_path.name in ("meta.jsonld", "prov.jsonld"):
                        arc_name = f"{folder_name}/{stage_name}/{file_path.name}"
                        zf.write(file_path, arc_name)
    return zip_path


def extract_entity_title(graph: Graph, entity_id: str) -> str:
    item_uri = URIRef(f"{BASE_URI}/itm/{entity_id}/ob00/1")
    for s, p, o in graph.triples((item_uri, P3_HAS_NOTE, None)):
        note = str(o)
        return note.split("\n")[0].strip()
    return f"Entity {entity_id}"


def generate_zenodo_config(
    entity_id: str,
    zip_path: Path,
    title: str,
    base_config: dict,
) -> dict:
    config = {
        "zenodo_url": base_config["zenodo_url"],
        "access_token": base_config["access_token"],
        "user_agent": base_config["user_agent"],
        "title": f"{title} - Aldrovandi collection",
        "upload_type": "dataset",
        "creators": base_config["creators"],
        "keywords": base_config["keywords"],
        "description": f"Digitization data for entity {entity_id} from the Aldrovandi collection.\n\nThis dataset contains metadata (meta.jsonld) and provenance (prov.jsonld) files for each processing stage (raw, rawp, dcho, dchoo).",
        "files": [str(zip_path.absolute())],
    }
    return config


def prepare_all(
    root: Path,
    zenodo_base_config_path: Path,
    output_dir: Path,
    kg_path: Path = KG_PATH,
    structure_path: Path | None = None,
) -> None:
    if structure_path is not None:
        structure = load_structure(structure_path)
    else:
        structure = scan_folder_structure(root)

    kg = load_kg(kg_path)
    licensed_stages = extract_licensed_entity_stages(kg)
    entity_groups = group_folders_by_entity(structure)

    with open(zenodo_base_config_path) as f:
        base_config = yaml.safe_load(f)

    zips_dir = output_dir / "zips"
    configs_dir = output_dir / "configs"
    zips_dir.mkdir(parents=True, exist_ok=True)
    configs_dir.mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    ) as progress:
        task = progress.add_task("Creating entity packages", total=len(entity_groups))

        for entity_id, folders in entity_groups.items():
            progress.update(task, description=f"Entity {entity_id}")
            zip_path = create_entity_zip(entity_id, folders, root, licensed_stages, zips_dir)
            title = extract_entity_title(kg, entity_id)
            config = generate_zenodo_config(entity_id, zip_path, title, base_config)
            config_path = configs_dir / f"{entity_id}.yaml"
            with open(config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
            progress.advance(task)


def upload_all(configs_dir: Path, publish: bool = False) -> None:
    config_files = sorted(configs_dir.glob("*.yaml"))
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    ) as progress:
        task = progress.add_task("Uploading to Zenodo", total=len(config_files))
        for config_file in config_files:
            progress.update(task, description=f"Uploading {config_file.stem}")
            piccione_upload(str(config_file), publish=publish)
            progress.advance(task)


def parse_arguments():  # pragma: no cover
    parser = argparse.ArgumentParser(description="Prepare and upload Zenodo packages")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="Create zips and YAML configs")
    prepare_parser.add_argument("root", type=Path, help="Root directory with Sala/Folder/Stage structure")
    prepare_parser.add_argument("zenodo_config", type=Path, help="Base Zenodo configuration YAML")
    prepare_parser.add_argument("--output", "-o", type=Path, default=Path("zenodo_output"), help="Output directory")
    prepare_parser.add_argument("--structure", "-s", type=Path, default=None, help="Structure JSON file")

    upload_parser = subparsers.add_parser("upload", help="Upload to Zenodo")
    upload_parser.add_argument("configs_dir", type=Path, help="Directory containing YAML configs")
    upload_parser.add_argument("--publish", action="store_true", help="Publish after upload")

    return parser.parse_args()


def main():  # pragma: no cover
    args = parse_arguments()
    if args.command == "prepare":
        prepare_all(
            root=args.root,
            zenodo_base_config_path=args.zenodo_config,
            output_dir=args.output,
            structure_path=args.structure,
        )
    elif args.command == "upload":
        upload_all(configs_dir=args.configs_dir, publish=args.publish)


if __name__ == "__main__":  # pragma: no cover
    main()
