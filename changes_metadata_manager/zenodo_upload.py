import argparse
import re
import zipfile
from collections import defaultdict
from datetime import date
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


class LiteralBlockDumper(yaml.SafeDumper):
    pass


def _literal_str_representer(dumper: yaml.SafeDumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


LiteralBlockDumper.add_representer(str, _literal_str_representer)

CREATORS_LOOKUP_PATH = Path(__file__).parent.parent / "data" / "creators_lookup.yaml"

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
P14_CARRIED_OUT_BY = URIRef(f"{CRM}P14_carried_out_by")
P1_IS_IDENTIFIED_BY = URIRef(f"{CRM}P1_is_identified_by")
P190_HAS_SYMBOLIC_CONTENT = URIRef(f"{CRM}P190_has_symbolic_content")
E21_PERSON = URIRef(f"{CRM}E21_Person")
RDF_TYPE = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")


def load_creators_lookup(path: Path) -> dict[str, dict]:
    with open(path) as f:
        data = yaml.safe_load(f)
    return {
        creator["name_in_rdf"]: {
            "name": creator["name"],
            "affiliation": creator["affiliation"],
            "orcid": creator["orcid"],
        }
        for creator in data["creators"]
    }


def build_creators_for_entity_stage(
    graph: Graph, entity_id: str, stage: str, creators_lookup: dict[str, dict]
) -> list[dict]:
    author_names = extract_authors_for_entity_stage(graph, entity_id, stage)
    return [creators_lookup[name] for name in sorted(author_names) if name in creators_lookup]


def extract_authors_for_entity_stage(graph: Graph, entity_id: str, stage: str) -> set[str]:
    steps = STAGE_STEPS[stage]
    authors = set()
    for step in steps:
        act_uri = URIRef(f"{BASE_URI}/act/{entity_id}/{step}/1")
        for _, _, actor_uri in graph.triples((act_uri, P14_CARRIED_OUT_BY, None)):
            if (actor_uri, RDF_TYPE, E21_PERSON) not in graph:
                continue
            for _, _, apl_uri in graph.triples((actor_uri, P1_IS_IDENTIFIED_BY, None)):
                for _, _, name in graph.triples((apl_uri, P190_HAS_SYMBOLIC_CONTENT, None)):
                    authors.add(str(name))
    return authors


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


STAGES = ("raw", "rawp", "dcho", "dchoo")


def create_stage_zip(
    entity_id: str,
    stage: str,
    folders: list[tuple[str, str, dict]],
    root: Path,
    licensed_stages: set[tuple[str, str]],
    output_dir: Path,
) -> Path | None:
    zip_path = output_dir / f"{entity_id}-{stage}.zip"
    has_files = False
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for sala_name, folder_name, stages_dict in folders:
            stage_name_in_folder = None
            for name in stages_dict:
                if name.lower() == stage:
                    stage_name_in_folder = name
                    break
            if stage_name_in_folder is None:
                continue
            stage_dir = root / sala_name / folder_name / stage_name_in_folder
            has_license = (entity_id, stage) in licensed_stages
            for file_path in stage_dir.iterdir():
                if not file_path.is_file():
                    continue
                if has_license or file_path.name in ("meta.jsonld", "prov.jsonld"):
                    arc_name = f"{folder_name}/{stage_name_in_folder}/{file_path.name}"
                    zf.write(file_path, arc_name)
                    has_files = True
    if not has_files:
        zip_path.unlink()
        return None
    return zip_path


def extract_entity_title(graph: Graph, entity_id: str) -> str:
    item_uri = URIRef(f"{BASE_URI}/itm/{entity_id}/ob00/1")
    for s, p, o in graph.triples((item_uri, P3_HAS_NOTE, None)):
        note = str(o)
        return note.split("\n")[0].strip()
    return f"Entity {entity_id}"


LICENSE_URI_TO_ZENODO = {
    "https://creativecommons.org/publicdomain/zero/1.0/": "cc-zero",
    "https://creativecommons.org/licenses/by/4.0/": "cc-by-4.0",
    "https://creativecommons.org/licenses/by-nc/4.0/": "cc-by-nc-4.0",
    "https://creativecommons.org/licenses/by-sa/4.0/": "cc-by-sa-4.0",
    "https://creativecommons.org/licenses/by-nc-sa/4.0/": "cc-by-nc-sa-4.0",
}

STAGE_DESCRIPTIONS = {
    "raw": "Contains raw acquisition data (photos/scans).",
    "rawp": "Contains processed raw model from photogrammetry/scanning.",
    "dcho": "Contains refined Digital Cultural Heritage Object with geometry corrections.",
    "dchoo": "Contains optimized 3D model ready for web visualization.",
}

PROPAGATED_FIELDS = (
    'zenodo_url', 'access_token', 'user_agent', 'upload_type',
    'keywords', 'license', 'access_right', 'publication_date',
    'language', 'version', 'communities', 'grants', 'related_identifiers',
    'contributors', 'subjects', 'notes',
    'references', 'locations', 'dates', 'method',
)


def extract_license_for_entity_stage(graph: Graph, entity_id: str, stage: str) -> str | None:
    steps = STAGE_STEPS[stage]
    for step in steps:
        lic_uri = URIRef(f"{BASE_URI}/lic/{entity_id}/{step}/1")
        for _, _, license_url in graph.triples((lic_uri, P70I, None)):
            zenodo_license = LICENSE_URI_TO_ZENODO.get(str(license_url))
            if zenodo_license:
                return zenodo_license
    return None


def build_enhanced_description(entity_id: str, stage: str, title: str) -> str:
    parts = [
        f"Digitization data for entity {entity_id} ({stage.upper()} stage) from the Aldrovandi collection.",
        f"Object: {title}",
        STAGE_DESCRIPTIONS[stage],
        "Includes metadata (meta.jsonld) and provenance (prov.jsonld) files.",
    ]
    return "\n".join(parts) + "\n"


def build_entity_uri(entity_id: str) -> str:
    return f"{BASE_URI}/itm/{entity_id}/ob00/1"


def generate_zenodo_config(
    entity_id: str,
    stage: str,
    zip_path: Path,
    title: str,
    base_config: dict,
    creators: list[dict],
    license: str | None = None,
    entity_uri: str | None = None,
) -> dict:
    config = {
        "title": f"{title} - {stage.upper()} - Aldrovandi collection",
        "description": build_enhanced_description(entity_id, stage, title),
        "files": [str(zip_path.absolute())],
        "creators": creators,
        "publication_date": date.today().isoformat(),
    }
    if license:
        config["license"] = license
    for field in PROPAGATED_FIELDS:
        if field in base_config and field not in config:
            config[field] = base_config[field]
    if entity_uri:
        alternate_id = {
            "identifier": entity_uri,
            "relation": "isAlternateIdentifier",
            "scheme": "url",
        }
        existing = config.get("related_identifiers", [])
        config["related_identifiers"] = existing + [alternate_id]
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

    creators_lookup = load_creators_lookup(CREATORS_LOOKUP_PATH)

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
        task = progress.add_task("Creating stage packages", total=len(entity_groups) * len(STAGES))

        for entity_id, folders in entity_groups.items():
            title = extract_entity_title(kg, entity_id)
            for stage in STAGES:
                progress.update(task, description=f"Entity {entity_id} - {stage}")
                zip_path = create_stage_zip(entity_id, stage, folders, root, licensed_stages, zips_dir)
                if zip_path is None:
                    progress.advance(task)
                    continue
                creators = build_creators_for_entity_stage(kg, entity_id, stage, creators_lookup)
                license = extract_license_for_entity_stage(kg, entity_id, stage)
                entity_uri = build_entity_uri(entity_id)
                config = generate_zenodo_config(entity_id, stage, zip_path, title, base_config, creators, license, entity_uri)
                config_path = configs_dir / f"{entity_id}-{stage}.yaml"
                with open(config_path, "w") as f:
                    yaml.dump(config, f, Dumper=LiteralBlockDumper, default_flow_style=False, allow_unicode=True, sort_keys=False)
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
