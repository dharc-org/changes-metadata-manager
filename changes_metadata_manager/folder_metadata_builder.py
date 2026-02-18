import argparse
import re
from pathlib import Path

import pyshacl
from rdflib import Dataset, Graph, URIRef
from rdflib.namespace import DCTERMS
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from changes_metadata_manager.generate_provenance import generate_provenance_snapshots


BASE_URI = "https://w3id.org/changes/4/aldrovandi"
KG_PATH = Path("data/kg.ttl")
SHAPES_PATH = Path("data/shapes-chadap.ttl")
RESP_AGENT = "https://w3id.org/changes/4/agent/morph-kgc-changes-metadata/1.0.1"
PRIMARY_SOURCE = "https://doi.org/10.5281/zenodo.18190642"
CC0 = URIRef("https://creativecommons.org/publicdomain/zero/1.0/")

STAGE_STEPS = {
    "raw": ["00"],
    "rawp": ["00", "01"],
    "dcho": ["00", "01", "02"],
    "dchoo": ["00", "01", "02", "03", "04", "05", "06"],
}

SKIP_FOLDERS = {
    "S1-CNR_SoffittoSala1",
    "S5-B basso-DICAM_FanoneBalenaAlto",
    "materials",
    "sala 4",
    "_files",
}

FOLDER_TO_ID = {
    "S3-PT-DICAM_VetrinaMatriciXilografiche": "ptb",
    "S3-PT-DICAM_Matrice Xilografica Fiore": "ptb_1",
    "S3-PT-DICAM_Matrice Xilografica Pianta": "ptb_2",
    "S3-PT-DICAM_Matrice Xilografica Serpente": "ptb_3",
    "S3-VS6-DBC_Matrice 1 egizia": "ptb_4",
    "S5-s.n.-DBC_Busto di Ulisse Aldrovandi": "s_n",
    "S4-ManicoColtelloZoomorfo": "50",
    "S5-CNR-AAltoCentro_TestamentoUlisseAldrovandi": "a_alto_centro",
    "S5-B alto destra 1-FICLIT_Mammuthus1": "b_alto_destra_1",
    "S5-B alto destra 1-FICLIT_Mammuthus2": "b_alto_destra_2",
    "S5-B basso-DICAM_FanoneBalenaBasso": "b_basso",
    "S5-A_alto_sinistra_1-FICLIT_Medaglia-Archeologico": "a_alto_sinistra_1",
    "S5-A alto sinistra\xa0- 2-FICLIT_MedagliaCommemorativa": "a_alto_sinistra_2",
    "S5-A alto sinistra 3- DBC_Calchi in gesso": "a_alto_sinistra_3",
    "S5-B alto centro 1-FICLIT_HarpactocarcinusPunctulatus": "b_alto_centro_1",
    "S5-B alto centro 2-DBC_Harpactocarcinus sp": "b_alto_centro_2",
    "S5-B alto centro - 3-FICLIT_LophoraninaAldrovandi": "b_alto_centro_3",
    "S5-B alto sinistra - 1-FICLIT_Carbonifero": "b_alto_sinistra_1",
    "S5-B alto sinistra 2-CNR_Miocene": "b_alto_sinistra_2",
    "S5-B alto sinistra 3-FICLIT_DentiDiPesci": "b_alto_sinistra_3",
    "S5-B alto destra 3-FICLIT_Hippopotamus": "b_alto_destra_3",
    # Vetrina 1
    "S5-Vetrina 1 alto N - 3-FICLIT_SonaglioThevetiaPeruviana": "vetrina_1_alto_n_3",
    "S5-Vetrina 1 alto N 1-FICLIT_CollanaMesoamericana": "vetrina_1_alto_n_1",
    "S5-Vetrina 1 alto N-2-DBC_Bambù_lavorato": "vetrina_1_alto_n_2",
    "S5-Vetrina 1 alto N-2-t-TavolettaConBambù": "vetrina_1_alto_n_2_t",
    "S5-Vetrina 1 alto S-1-FICLIT-Statuetta ushabti in faïence": "vetrina_1_alto_s_1",
    "S5-Vetrina 1 alto S-10-DICAM_GemmaInDiasproGialloConCinocefaloeIscrizione": "vetrina_1_alto_s_10",
    "S5-Vetrina 1 alto S-11-DICAM_GemmaInDiasproConScorpione": "vetrina_1_alto_s_11",
    "S5-Vetrina 1 alto S-12-DICAM_GemmaInDiasproNeroConIscrizioneAraba": "vetrina_1_alto_s_12",
    "S5-Vetrina 1 alto S-14-FICLIT_PuntaFrecciaNeolitico": "vetrina_1_alto_s_14",
    "S5-Vetrina 1 alto S-15-DBC_Corno_lavorato": "vetrina_1_alto_s_15",
    "S5-Vetrina 1 alto S-16-DBC_Ascia_di_giadeite": "vetrina_1_alto_s_16",
    "S5-Vetrina 1 alto S-3-DICAM_ScarabeoInStileEgizio": "vetrina_1_alto_s_3",
    "S5-Vetrina 1 alto S-4-DICAM_GemmaInAgataConCapraPressoAlbero": "vetrina_1_alto_s_4",
    "S5-Vetrina 1 alto S-5-DICAM_GemmaInAgataconMascheraDellaCommediaDell’Arte": "vetrina_1_alto_s_5",
    "S5-Vetrina 1 alto S-6-DICAM_GemmaInAgataConSerapideInTrono": "vetrina_1_alto_s_6",
    "S5-Vetrina 1 alto S-7-DICAM_GemmaInAgataConUccello": "vetrina_1_alto_s_7",
    "S5-Vetrina 1 alto S-8-DICAM_GemmaInAgataConMercurioeFontana": "vetrina_1_alto_s_8",
    "S5-Vetrina 1 alto S-9-DICAM_GemmainPastaVitreaStratificataconFiguraAppoggiataAunBastone": "vetrina_1_alto_s_9",
    "S5-Vetrina 1 basso-DICAM_Carapaci": "vetrina_1_basso",
    "S5-vetrina_1_alto_s_2-FICLIT_Lucerna fittile a volute con spalla decorata": "vetrina_1_alto_s_2",
    "S5-vetrina_1_alto_s_13-FICLIT_Sferule di avorio e calcare": "vetrina_1_alto_s_13",
    # Vetrina 2
    "S5-Vetrina 2 ALTO N 3-FICLIT_SezioneDenteDiElefante": "vetrina_2_alto_n_3",
    "S5-Vetrina 2 alto N - 1-DICAM_Calcoli": "vetrina_2_alto_n_1",
    "S5-Vetrina 2 alto N - 3 - t-DICAM_MatriceElefante": "vetrina_2_alto_n_3_t",
    "S5-Vetrina 2 alto N-1-t1-DBC_Tavoletta_con_calcolo_1": "vetrina_2_alto_n_1_t1",
    "S5-Vetrina 2 alto N-1-t2-DBC_Tavoletta_con_calcolo_2": "vetrina_2_alto_n_1_t2",
    "S5-Vetrina 2 alto S - 1 - t-DICAM_MatriceZanna": "vetrina_2_alto_s_1_t",
    "S5-Vetrina 2 alto S - 1-DICAM_ZanneDiElefante": "vetrina_2_alto_s_1",
    "S5-Vetrina 2 alto S - 2-DICAM_CornaDiBovidiECervidi": "vetrina_2_alto_s_2",
    "S5-Vetrina 2 alto S-2-t-DBC_Tavoletta_con_cervo": "vetrina_2_alto_s_2_t",
    "S5-Vetrina 2 basso t-DICAM_MatriceRinoceronte": "vetrina_2_basso_t",
    "S5-Vetrina 2 basso-DICAM_Alce": "vetrina_2_basso",
    "S5-Vetrina_2_alto_n2_BezoarGazzella": "vetrina_2_alto_n_2",
    "S5-Vetrina_2_alto_s_3_ghiandoleCastoroeCapra": "vetrina_2_alto_s_3",
    # Vetrina 3
    "S5-Vetrina 3 alto N - 1-DICAM_UovaDiStruzzo": "vetrina_3_alto_n_1",
    "S5-Vetrina 3 alto N - 3-DA_Graminacea Subfossile": "vetrina_3_alto_n_3",
    "S5-Vetrina 3 alto N-4- DA- Apice vegetativo di palma": "vetrina_3_alto_n_4",
    "S5-Vetrina 3 alto S-1-t-TavolettaConBaccelli": "vetrina_3_alto_s_1_t",
    "S5-Vetrina 3 alto S-2-t-DBC_Tavoletta_con_nido": "vetrina_3_alto_s_2_t",
    "S5-Vetrina 3 alto S-4-FICLIT_NidoDiPendolino": "vetrina_3_alto_s_4",
    "S5-Vetrina 3 alto sinistra-1-DA-BaccelloConSeme": "vetrina_3_alto_s_1",
    "S5-Vetrina 3 basso-DICAM_Preparati di terre e Terre sigillate": "vetrina_3_basso",
    "S5-Vetrina_3_alto_n2_uovamostruosedipolloefagiano": "vetrina_3_alto_n_2",
    "S5-vetrina_3_alto_s_3_nidipreparativegetali": "vetrina_3_alto_s_3",
    # Vetrina 4
    "S5-Vetrina 4 alto N - 10-DICAM_Echinoidifossilin.10": "vetrina_4_alto_n_10",
    "S5-Vetrina 4 alto N - 11-DICAM_EchinoidiFossilin.11": "vetrina_4_alto_n_11",
    "S5-Vetrina 4 alto N - 7-DICAM_EchinoidiFossilin.7": "vetrina_4_alto_n_7",
    "S5-Vetrina 4 alto N - 8-DICAM_EchinoidiFossilin.8": "vetrina_4_alto_n_8",
    "S5-Vetrina 4 alto N - 9-FICLIT_EchinoidiFossilin.9": "vetrina_4_alto_n_9",
    "S5-Vetrina 4 alto N-1-DBC_Conoclypeus_conoideus": "vetrina_4_alto_n_1",
    "S5-Vetrina 4 alto N-2-DBC_Dollaro_di_mare": "vetrina_4_alto_n_2",
    "S5-Vetrina 4 alto N-3-DBC_Clypeaster_marginatus": "vetrina_4_alto_n_3",
    "S5-Vetrina 4 alto N-4-DBC_Mazettia_pareti": "vetrina_4_alto_n_4",
    "S5-Vetrina 4 alto N-5-DBC_Discoidea sp": "vetrina_4_alto_n_5",
    "S5-Vetrina 4 alto N-6-DBC_Macropneustes_sp": "vetrina_4_alto_n_6",
    "S5-Vetrina 4 alto S-1-DBC_Calcare a coralli lavorati": "vetrina_4_alto_s_1",
    "S5-Vetrina 4 alto S-10-DBC_Productus_geinitzianus": "vetrina_4_alto_s_10",
    "S5-Vetrina 4 alto S-11-DBC_Stephanoceras_bayleanus": "vetrina_4_alto_s_11",
    "S5-Vetrina 4 alto S-12-DBC_Tellina_planata": "vetrina_4_alto_s_12",
    "S5-Vetrina 4 alto S-13-DBC_Glossus_humanus": "vetrina_4_alto_s_13",
    "S5-Vetrina 4 alto S-2-DBC_Coralli": "vetrina_4_alto_s_2",
    "S5-Vetrina 4 alto S-3-DBC_Lumachella_a_Helicidi": "vetrina_4_alto_s_3",
    "S5-Vetrina 4 alto S-4-DBC_Calcare_a_lumachella": "vetrina_4_alto_s_4",
    "S5-Vetrina 4 alto S-5-DBC_Dentalium_elephantinum": "vetrina_4_alto_s_5",
    "S5-Vetrina 4 alto S-6-DBC_Glycymeris_glycymeris": "vetrina_4_alto_s_6",
    "S5-Vetrina 4 alto S-7-DBC_Bivalvi_indet": "vetrina_4_alto_s_7",
    "S5-Vetrina 4 alto S-8-DBC_Lytoceras_sp": "vetrina_4_alto_s_8",
    "S5-Vetrina 4 alto S-9-DBC_Megalodon_sp": "vetrina_4_alto_s_9",
    "S5-Vetrina 4 basso-FICLIT_Campioni di rocce levigate": "vetrina_4_basso",
    # Vetrina 5
    "S5-Vetrina 5 alto N  - t-DICAM_MatriceBotroide1": "vetrina_5_alto_n_t",
    "S5-Vetrina 5 alto N-DICAM_Botroide1": "vetrina_5_alto_n",
    "S5-Vetrina 5 alto S - 1-DICAM_Botroide2": "vetrina_5_alto_s_1",
    "S5-Vetrina 5 alto S - 2 - t-DICAM_MatriceBotroide2": "vetrina_5_alto_s_2_t",
    "S5-Vetrina 5 alto S-2-DICAM_Botroide_triorchites": "vetrina_5_alto_s_2",
    "S5-Vetrina 5 basso t-DICAM_MatriceBotroide3": "vetrina_5_basso_t",
    "S5-Vetrina 5 basso-DICAM_Botroide3": "vetrina_5_basso",
    # Vetrina 6
    "S5-Vetrina 6 alto N-1-DBC_Bufo sp., Rospo": "vetrina_6_alto_n_1",
    "S5-Vetrina 6 alto N-1-t-TavolettaBufo": "vetrina_6_alto_n_1_t",
    "S5-Vetrina 6 alto N-2-DBC_Cordylus sp., lucertola": "vetrina_6_alto_n_2",
    "S5-Vetrina 6 alto N-2-t-TavolettaConLucertola": "vetrina_6_alto_n_2_t",
    "S5-Vetrina 6 alto S - 2 - t-DICAM_MatricePesce12_Pesce": "vetrina_6_alto_s_2_t",
    "S5-Vetrina 6 basso 2-ScheletroDiDelfino": "vetrina_6_basso_2",
    "S5-Vetrina 6 basso 2-t-TavolettaConDelfino": "vetrina_6_basso_2_t",
    "S5-Vetrina 6 basso-DBC_Scapola di balena": "vetrina_6_basso",
    "S5-vetrina_6_alto_s_1_Chamaleo": "vetrina_6_alto_s_1",
    "S5-vetrina_6_alto_s_1_Scincus_Pescedellesabbie": "vetrina_6_alto_s_1",
    # Vetrina 7
    "S5-Vetrina 7 alto N - 1 - t-DICAM_MatricePesce6_PesceForca": "vetrina_7_alto_n_1_t",
    "S5-Vetrina 7 alto N 1-FICLIT_PesceForca": "vetrina_7_alto_n_1",
    "S5-Vetrina 7 alto N 2-FICLIT_PesceScatola": "vetrina_7_alto_n_2",
    "S5-Vetrina 7 alto S - 1 - t-DICAM_MatricePesce11_PesceSpada": "vetrina_7_alto_s_1_t",
    "S5-Vetrina 7 alto S - 3 - t-DICAM_MatricePesce10_PesceVolante": "vetrina_7_alto_s_3_t",
    "S5-Vetrina 7 alto S - 3-FICLIT_PesceVolante": "vetrina_7_alto_s_3",
    "S5-Vetrina 7 alto S 2-FICLIT_SorcioMarino": "vetrina_7_alto_s_2",
    "S5-Vetrina 7 alto S-1-DA-Xiphias sp., Pesci spada": "vetrina_7_alto_s_1",
    "S5-Vetrina 7 basso  - t-DICAM_MatricePesce13_PescePalla2": "vetrina_7_basso_t",
    "S5-Vetrina 7 basso  - t-DICAM_MatricePesce9_PescePalla1": "vetrina_7_basso_t",
    "S5-Vetrina 7 basso-DICAM_PescePalla": "vetrina_7_basso",
    # Vetrina 8
    "S5-Vetrina 8 alto N - 1-FICLIT_ScazzoneMarino": "vetrina_8_alto_n_1",
    "S5-Vetrina 8 alto N - 3 - t-DICAM_MatricePesce4_Bocca1": "vetrina_8_alto_n_3_t",
    "S5-Vetrina 8 alto N - 3 - t-DICAM_MatricePesce8_Bocca2": "vetrina_8_alto_n_3_t",
    "S5-Vetrina 8 alto N - 3-DA-Apparato dentale di pesce cartilagineo (Elasmobrnchii)": "vetrina_8_alto_n_3",
    "S5-Vetrina 8 alto N-2-DA-Lophius piscatorius (Linnaeus, 1758), rana pescatrice": "vetrina_8_alto_n_2",
    "S5-Vetrina 8 alto S - 1 - t-DICAM_MatricePesce1_PesceChitarra": "vetrina_8_alto_s_1_t",
    "S5-Vetrina 8 alto S - 1-DA-Rhinobatos rhinobatos": "vetrina_8_alto_s_1",
    "S5-Vetrina 8 alto S - 2 - t-DICAM_MatricePesce2_Smeriglio": "vetrina_8_alto_s_2_t",
    "S5-Vetrina 8 alto S - 2-DA-Lamna nasus (Bonnaterre, 1788), smeriglio": "vetrina_8_alto_s_2",
    "S5-Vetrina 8 alto S - 3 - t-DICAM_MatricePesce3_RanaPescatrice": "vetrina_8_alto_s_3_t",
    "S5-Vetrina 8 alto S.3-DA-Lophius piscatorius (Linnaeus, 1758), apparato boccale rana pescatrice": "vetrina_8_alto_s_3",
    "S5-Vetrina 8 basso  - t1-DICAM_MatricePesce7_DentiPesceSega": "vetrina_8_basso_t1",
    "S5-Vetrina 8 basso  - t2-DICAM_MatricePesce5_PesceSega": "vetrina_8_basso_t2",
    "S5-Vetrina 8 basso-DA-Pesce Martello": "vetrina_8_basso",
    "S5-Vetrina 8 basso-DA-Preparati zoologici, Pescecane": "vetrina_8_basso",
    "S5-Vetrina 8 basso-DA-Preparati zoologici, pesce sega": "vetrina_8_basso",
    # Manoscritti
    "S5-Manoscritto-FICLIT_AdnotationesVariaePraesertimDeAnimalibus": "m1",
    "S5-Manoscritto-FICLIT_VulgataProverbia": "m2",
    "S5-Manoscritto-FICLIT_PandechionEpistemonicon": "m3",
    "S5-Manoscritto-FICLIT_LexiconRerumInanimatarum": "m4",
    "S5-Manoscritto-FICLIT_BibliothecaSecundumNominaAuthorum": "m5",
    "S5-Manoscritto-FICLIT_TheatrumBiblicumNaturale": "m6",
    "S5-Manoscritto-FICLIT_LibroDeiVisitatori": "m7",
    "S5-Manoscritto-FICLIT_DiscorsoNaturaleAldrovandi": "m8",
}


def load_kg(path: Path) -> Graph:
    graph = Graph()
    graph.parse(path, format="turtle")
    return graph


def extract_id_from_folder_name(folder_name: str) -> str:
    if folder_name in FOLDER_TO_ID:
        return FOLDER_TO_ID[folder_name]
    match = re.match(r"S\d+-(\d+[a-z]?) ?[-_]", folder_name)
    if not match:
        raise ValueError(f"Cannot extract ID from folder name: {folder_name}")
    return match.group(1).lstrip("0") or "0"


def extract_metadata_for_stage(graph: Graph, nr: str, stage: str) -> Graph:
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


def validate_metadata(data_graph: Graph, shapes_graph: Graph) -> tuple[bool, str]:
    conforms, _, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes_graph,
    )
    return bool(conforms), str(results_text)


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
    shapes_path: Path = SHAPES_PATH,
    validate: bool = True,
) -> list[tuple[str, str]]:
    structure = scan_folder_structure(root)
    kg = load_kg(kg_path)
    shapes_graph = load_kg(shapes_path) if validate else None

    console = Console()
    validation_errors = []

    folders = [
        (sala_name, folder_name, subfolders)
        for sala_name, sala_items in structure["structure"].items()
        for folder_name, subfolders in sala_items.items()
        if folder_name not in SKIP_FOLDERS
    ]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    ) as progress:
        task = progress.add_task("Processing folders", total=len(folders))

        for sala_name, folder_name, subfolders in folders:
            nr = extract_id_from_folder_name(folder_name)
            progress.update(task, description=f"{folder_name}")

            existing_stages = [
                s for s in subfolders.keys()
                if s.lower() in STAGE_STEPS
            ]

            for stage_name in existing_stages:
                stage_key = stage_name.lower()
                stage_dir = root / sala_name / folder_name / stage_name
                stage_dir.mkdir(parents=True, exist_ok=True)

                metadata = extract_metadata_for_stage(kg, nr, stage_key)
                metadata.add((URIRef(""), DCTERMS.license, CC0))

                if shapes_graph is not None:
                    conforms, results_text = validate_metadata(metadata, shapes_graph)
                    if not conforms:
                        label = f"{folder_name}/{stage_name}"
                        validation_errors.append((label, results_text))

                meta_path = stage_dir / "meta.ttl"
                metadata.serialize(destination=str(meta_path), format="turtle")

                prov_path = stage_dir / "prov.trig"
                generate_provenance_snapshots(
                    input_directory=str(stage_dir),
                    output_file=str(prov_path),
                    output_format="trig",
                    agent_orcid=RESP_AGENT,
                    primary_source=PRIMARY_SOURCE,
                )

            progress.advance(task)

    if shapes_graph is not None:
        if validation_errors:
            console.print(f"\n[bold red]SHACL validation failed for {len(validation_errors)} stage(s):[/bold red]")
            for label, results_text in validation_errors:
                console.print(f"\n[bold yellow]{label}[/bold yellow]")
                console.print(results_text)
        else:
            console.print("\n[bold green]All metadata passed SHACL validation.[/bold green]")

    return validation_errors


def merge_provenance_files(root: Path, output_path: Path) -> None:
    merged = Dataset(default_union=True)
    for prov_file in sorted(root.rglob("prov.trig")):
        merged.parse(str(prov_file), format="trig")
    merged.serialize(destination=str(output_path), format="trig")


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
        "--no-validate",
        action="store_true",
        help="Skip SHACL validation",
    )
    parser.add_argument(
        "--merge-provenance",
        type=Path,
        default=None,
        help="Output path for merged provenance file (TriG format)",
    )
    return parser.parse_args()


def main():  # pragma: no cover
    args = parse_arguments()
    process_all_folders(root=args.root, validate=not args.no_validate)
    if args.merge_provenance:
        merge_provenance_files(args.root, args.merge_provenance)


if __name__ == "__main__":  # pragma: no cover
    main()