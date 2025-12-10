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


def process_all_folders(
    output_dir: Path,
    structure_path: Path = STRUCTURE_PATH,
    kg_path: Path = KG_PATH,
) -> dict:
    structure = load_sharepoint_structure(structure_path)
    kg = load_kg(kg_path)

    for sala_name, sala_items in structure["structure"].items():
        sala_dir = output_dir / sala_name
        sala_dir.mkdir(parents=True, exist_ok=True)

        for folder_name, subfolders in sala_items.items():
            nr = extract_nr_from_folder_name(folder_name)
            folder_dir = sala_dir / folder_name

            existing_stages = [
                s for s in subfolders.keys()
                if s.lower() in STAGE_STEPS
            ]

            if not existing_stages:
                raise ValueError(f"No valid stage subfolders in {folder_name}")

            for stage_name in existing_stages:
                stage_key = stage_name.lower()
                stage_dir = folder_dir / stage_name
                stage_dir.mkdir(parents=True, exist_ok=True)

                metadata = extract_metadata_for_stage(kg, nr, stage_key)
                if len(metadata) == 0:
                    raise ValueError(f"No metadata for {folder_name}/{stage_name} (NR={nr})")

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


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Process SharePoint structure and generate metadata/provenance files"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="data/output",
        help="Output directory for generated files",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    process_all_folders(output_dir=Path(args.output))
    print(f"\nProcessing complete:")


if __name__ == "__main__":
    main()