import argparse
import json
import re
from pathlib import Path

from rdflib import Graph, URIRef

from aldrovandi_provenance.generate_provenance import generate_provenance_snapshots


BASE_URI = "https://w3id.org/changes/4/aldrovandi"
STRUCTURE_PATH = Path("data/sharepoint_structure.json")
KG_PATH = Path("data/kg.ttl")
RESP_AGENT = "https://orcid.org/0000-0000-0000-0000"  # TODO: replace with actual URI
PRIMARY_SOURCE = "https://example.org/primary-source"  # TODO: replace with actual URI

STAGE_STEPS = {
    "raw": ["00"],
    "rawp": ["00", "01"],
    "dcho": ["00", "01", "02"],
    "dchoo": ["00", "01", "02", "03", "04", "05", "06"],
}


def load_kg(path: Path) -> Graph:
    graph = Graph()
    graph.parse(path, format="turtle")
    return graph


def extract_nr_from_folder_name(folder_name: str) -> int:
    match = re.match(r"S\d+-(\d+)-", folder_name)
    if not match:
        raise ValueError(f"Cannot extract NR from folder name: {folder_name}")
    return int(match.group(1))


def extract_metadata_for_stage(graph: Graph, nr: int, stage: str) -> Graph:
    result = Graph()
    for prefix, namespace in graph.namespace_manager.namespaces():
        result.namespace_manager.bind(prefix, namespace)

    steps = STAGE_STEPS[stage]

    for s, p, o in graph:
        s_str = str(s)
        step_match = re.search(rf"/{nr}/(\d{{2}})/1$", s_str)
        if step_match:
            step = step_match.group(1)
            if step in steps:
                result.add((s, p, o))
                if isinstance(o, URIRef):
                    for s2, p2, o2 in graph.triples((o, None, None)):
                        result.add((s2, p2, o2))
            continue

        ob_match = re.search(rf"/{nr}/ob\d+/1$", s_str)
        if ob_match:
            result.add((s, p, o))
            if isinstance(o, URIRef):
                for s2, p2, o2 in graph.triples((o, None, None)):
                    result.add((s2, p2, o2))

    return result


def load_sharepoint_structure(structure_path: Path) -> dict:
    with open(structure_path) as f:
        return json.load(f)


def scan_folder_structure(root_path: Path) -> dict:
    structure = {}
    for sala_dir in root_path.iterdir():
        sala_name = sala_dir.name
        structure[sala_name] = {}
        for folder_dir in sala_dir.iterdir():
            folder_name = folder_dir.name
            structure[sala_name][folder_name] = {}
            for stage_dir in folder_dir.iterdir():
                stage_name = stage_dir.name
                files = [f.name for f in stage_dir.iterdir() if f.is_file()]
                structure[sala_name][folder_name][stage_name] = {"_files": files}
    return {"structure": structure}


def process_all_folders(
    root: Path,
    kg_path: Path = KG_PATH,
    structure_path: Path | None = None,
) -> None:
    if structure_path is not None:
        structure = load_sharepoint_structure(structure_path)
    else:
        structure = scan_folder_structure(root)
    kg = load_kg(kg_path)

    for sala_name, sala_items in structure["structure"].items():
        for folder_name, subfolders in sala_items.items():
            nr = extract_nr_from_folder_name(folder_name)

            existing_stages = [
                s for s in subfolders.keys()
                if s.lower() in STAGE_STEPS
            ]

            for stage_name in existing_stages:
                stage_key = stage_name.lower()
                stage_dir = root / sala_name / folder_name / stage_name

                metadata = extract_metadata_for_stage(kg, nr, stage_key)

                meta_path = stage_dir / "meta.ttl"
                metadata.serialize(destination=str(meta_path), format="turtle")

                prov_path = stage_dir / "prov.nq"
                generate_provenance_snapshots(
                    input_directory=str(stage_dir),
                    output_file=str(prov_path),
                    output_format="nquads",
                    agent_orcid=RESP_AGENT,
                    primary_source=PRIMARY_SOURCE,
                )

            print(f"Processed {folder_name} (NR={nr}): {len(existing_stages)} stages")


def parse_arguments():  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Generate metadata and provenance files for folder structure"
    )
    parser.add_argument(
        "root",
        type=Path,
        help="Root directory containing Sala/Folder/Stage structure",
    )
    parser.add_argument(
        "--structure",
        "-s",
        type=Path,
        default=None,
        help="SharePoint JSON structure file (optional, for development)",
    )
    return parser.parse_args()


def main():  # pragma: no cover
    args = parse_arguments()
    process_all_folders(root=args.root, structure_path=args.structure)
    print("\nProcessing complete")


if __name__ == "__main__":  # pragma: no cover
    main()