import argparse
import json
import re
from pathlib import Path

from rdflib import Graph, URIRef

from changes_metadata_manager.generate_provenance import generate_provenance_snapshots


BASE_URI = "https://w3id.org/changes/4/aldrovandi"
STRUCTURE_PATH = Path("data/sharepoint_structure.json")
KG_PATH = Path("data/kg.ttl")
RESP_AGENT = "https://w3id.org/changes/4/agent/morph-kgc-changes-metadata/1.0.1"
PRIMARY_SOURCE = "https://doi.org/10.5281/zenodo.18190642"

STAGE_STEPS = {
    "raw": ["00"],
    "rawp": ["00", "01"],
    "dcho": ["00", "01", "02"],
    "dchoo": ["00", "01", "02", "03", "04", "05", "06"],
}

SKIP_FOLDERS = {
    "S1-CNR_SoffittoSala1",
}

FOLDER_TO_ID = {
    "S3-PT-DICAM_VetrinaMatriciXilografiche": "ptb",
    "S3-PT-DICAM_Matrice Xilografica Fiore": "ptb_1",
    "S3-PT-DICAM_Matrice Xilografica Pianta": "ptb_2",
    "S3-PT-DICAM_Matrice Xilografica Serpente": "ptb_3",
    "S3-VS6-DBC_Matrice 1 egizia": "ptb_4",
    "S5-s.n.-DBC_Busto di Ulisse Aldrovandi": "s_n",
    "S4-ManicoColtelloZoomorfo": 50,
    "S5-CNR-AAltoCentro_TestamentoUlisseAldrovandi": "a_alto_centro",
    "S5-B alto destra 1-FICLIT_Mammuthus1": "b_alto_destra_1",
    "S5-B alto destra 1-FICLIT_Mammuthus2": "b_alto_destra_2",
}


def load_kg(path: Path) -> Graph:
    graph = Graph()
    graph.parse(path, format="turtle")
    return graph


def extract_id_from_folder_name(folder_name: str) -> int | str:
    if folder_name in FOLDER_TO_ID:
        return FOLDER_TO_ID[folder_name]
    match = re.match(r"S\d+-(\d+)[a-z]? ?[-_]", folder_name)
    if not match:
        raise ValueError(f"Cannot extract ID from folder name: {folder_name}")
    return int(match.group(1))


def extract_metadata_for_stage(graph: Graph, nr: int | str, stage: str) -> Graph:
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
            if folder_name in SKIP_FOLDERS:
                continue
            nr = extract_id_from_folder_name(folder_name)

            existing_stages = [
                s for s in subfolders.keys()
                if s.lower() in STAGE_STEPS
            ]

            for stage_name in existing_stages:
                stage_key = stage_name.lower()
                stage_dir = root / sala_name / folder_name / stage_name
                stage_dir.mkdir(parents=True, exist_ok=True)

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