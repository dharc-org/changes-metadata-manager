import argparse
import csv
import re
import unicodedata
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


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")

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
CRMDIG = "http://www.cidoc-crm.org/extensions/crmdig/"
AAT = "http://vocab.getty.edu/aat/"

P70I = URIRef(f"{CRM}P70i_is_documented_in")
P3_HAS_NOTE = URIRef(f"{CRM}P3_has_note")
P14_CARRIED_OUT_BY = URIRef(f"{CRM}P14_carried_out_by")
P1_IS_IDENTIFIED_BY = URIRef(f"{CRM}P1_is_identified_by")
P190_HAS_SYMBOLIC_CONTENT = URIRef(f"{CRM}P190_has_symbolic_content")
P74_HAS_RESIDENCE = URIRef(f"{CRM}P74_has_current_or_former_residence")
P32_USED_GENERAL_TECHNIQUE = URIRef(f"{CRM}P32_used_general_technique")
P16_USED_SPECIFIC_OBJECT = URIRef(f"{CRM}P16_used_specific_object")
E21_PERSON = URIRef(f"{CRM}E21_Person")
RDF_TYPE = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
L23_USED_SOFTWARE = URIRef(f"{CRMDIG}L23_used_software_or_firmware")

AAT_TECHNIQUE_LABELS: dict[str, str] = {
    f"{AAT}300266792": "digital photography",
    f"{AAT}300429747": "optical scanning",
}

SLUG_LABELS: dict[str, str] = {
    "3df_zephyr": "3DF Zephyr",
    "adobe_photoshop_2023": "Adobe Photoshop 2023",
    "agisoft_metashape": "Agisoft Metashape",
    "artec_eva": "Artec Eva",
    "artec_leo": "Artec Leo",
    "artec_spider": "Artec Spider",
    "artec_studio_14": "Artec Studio 14",
    "artec_studio_15": "Artec Studio 15",
    "artec_studio_16": "Artec Studio 16",
    "artec_studio_19": "Artec Studio 19",
    "aton": "ATON",
    "blender": "Blender",
    "canon_eos_6d": "Canon EOS 6D",
    "chad-ap": "CHAD-AP",
    "cloudcompare": "CloudCompare",
    "gestaltor": "Gestaltor",
    "gimp": "GIMP",
    "heritrace": "HERITRACE",
    "instalod": "InstaLOD",
    "instant_meshes": "Instant Meshes",
    "lente_24-70_f2_8_l": "Canon EF 24-70mm f/2.8L",
    "meshlab": "MeshLab",
    "metashape": "Agisoft Metashape",
    "microscopio_digitale_bresciani": "Microscopio Digitale Bresciani",
    "modo": "Modo",
    "morph-kgc": "Morph-KGC",
    "nextcloud": "Nextcloud",
    "nikkor_35mm": "Nikkor 35mm",
    "nikkor_50mm": "Nikkor 50mm",
    "nikon_d3300": "Nikon D3300",
    "nikon_d5200": "Nikon D5200",
    "nikon_d5600": "Nikon D5600",
    "nikon_d7200": "Nikon D7200",
    "nikon_d750": "Nikon D750",
    "panasonic_dmc-lx100": "Panasonic DMC-LX100",
    "sony_alpha_6100": "Sony Alpha 6100",
    "sony_alpha_7_i": "Sony Alpha 7 I",
    "substance_3d_painter": "Substance 3D Painter",
    "substance_painter": "Substance Painter",
    "zbrush": "ZBrush",
}


def _format_slug(slug: str) -> str:
    return SLUG_LABELS[slug]


def load_creators_lookup(path: Path) -> dict[str, dict]:
    with open(path) as f:
        data = yaml.safe_load(f)
    return {
        creator["name_in_rdf"]: {
            "family_name": creator["family_name"],
            "given_name": creator["given_name"],
            "affiliation": creator["affiliation"],
            "orcid": creator["orcid"],
        }
        for creator in data["creators"]
    }


def _format_creator(creator_data: dict, role: str) -> dict:
    return {
        "person_or_org": {
            "type": "personal",
            "family_name": creator_data["family_name"],
            "given_name": creator_data["given_name"],
            "identifiers": [{"scheme": "orcid", "identifier": creator_data["orcid"]}],
        },
        "role": {"id": role},
        "affiliations": [{"name": creator_data["affiliation"]}],
    }


METADATA_STEP = "05"


def _extract_actor_names(graph: Graph, act_uri: URIRef) -> set[str]:
    names = set()
    for _, _, actor_uri in graph.triples((act_uri, P14_CARRIED_OUT_BY, None)):
        assert (actor_uri, RDF_TYPE, E21_PERSON) in graph
        for _, _, apl_uri in graph.triples((actor_uri, P1_IS_IDENTIFIED_BY, None)):
            for _, _, name in graph.triples((apl_uri, P190_HAS_SYMBOLIC_CONTENT, None)):
                names.add(str(name))
    return names


def extract_authors_for_entity_stage(graph: Graph, entity_id: str, stage: str) -> set[str]:
    steps = [s for s in STAGE_STEPS[stage] if s != METADATA_STEP]
    authors = set()
    for step in steps:
        authors |= _extract_actor_names(graph, URIRef(f"{BASE_URI}/act/{entity_id}/{step}/1"))
    return authors


def extract_metadata_authors(graph: Graph, entity_id: str) -> set[str]:
    return _extract_actor_names(graph, URIRef(f"{BASE_URI}/act/{entity_id}/05/1"))


def build_creators_for_entity_stage(
    graph: Graph, entity_id: str, stage: str, creators_lookup: dict[str, dict]
) -> list[dict]:
    author_names = extract_authors_for_entity_stage(graph, entity_id, stage)
    return [
        _format_creator(creators_lookup[name], "researcher")
        for name in sorted(author_names)
        if name in creators_lookup
    ]


def build_metadata_creators(
    graph: Graph, entity_id: str, creators_lookup: dict[str, dict]
) -> list[dict]:
    author_names = extract_metadata_authors(graph, entity_id)
    return [
        _format_creator(creators_lookup[name], "datacurator")
        for name in sorted(author_names)
        if name in creators_lookup
    ]


def merge_creators(digitization_creators: list[dict], metadata_creators: list[dict]) -> list[dict]:
    seen_orcids: set[str] = set()
    merged: list[dict] = []
    for creator in digitization_creators:
        orcid = creator["person_or_org"]["identifiers"][0]["identifier"]
        seen_orcids.add(orcid)
        merged.append(creator)
    for creator in metadata_creators:
        orcid = creator["person_or_org"]["identifiers"][0]["identifier"]
        if orcid not in seen_orcids:
            seen_orcids.add(orcid)
            merged.append(creator)
    return merged


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
    title: str,
) -> tuple[Path, bool] | None:
    sala_name = folders[0][0]
    sala_slug = slugify(sala_name)
    title_slug = slugify(title)
    zip_path = output_dir / f"{sala_slug}-{title_slug}-{stage}.zip"
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
                if has_license or file_path.name in ("meta.ttl", "prov.trig"):
                    arc_name = f"{folder_name}/{stage_name_in_folder}/{file_path.name}"
                    zf.write(file_path, arc_name)
                    has_files = True
    if not has_files:
        zip_path.unlink()
        return None
    return zip_path, (entity_id, stage) in licensed_stages


def _get_label(graph: Graph, uri: URIRef) -> str | None:
    for _, _, apl_uri in graph.triples((uri, P1_IS_IDENTIFIED_BY, None)):
        for _, _, name in graph.triples((apl_uri, P190_HAS_SYMBOLIC_CONTENT, None)):
            return str(name)
    return None


def extract_keeper_info(graph: Graph, entity_id: str) -> tuple[str | None, str | None]:
    custody_uri = URIRef(f"{BASE_URI}/act/{entity_id}/ob08/1")
    for _, _, keeper_uri in graph.triples((custody_uri, P14_CARRIED_OUT_BY, None)):
        assert isinstance(keeper_uri, URIRef)
        keeper_name = _get_label(graph, keeper_uri)
        location_name = None
        for _, _, place_uri in graph.triples((keeper_uri, P74_HAS_RESIDENCE, None)):
            assert isinstance(place_uri, URIRef)
            location_name = _get_label(graph, place_uri)
        return keeper_name, location_name
    return None, None


def extract_entity_title(graph: Graph, entity_id: str) -> str:
    item_uri = URIRef(f"{BASE_URI}/itm/{entity_id}/ob00/1")
    for s, p, o in graph.triples((item_uri, P3_HAS_NOTE, None)):
        note = str(o)
        return note.split("\n")[0].strip()
    return f"Entity {entity_id}"


def extract_acquisition_technique(graph: Graph, entity_id: str) -> str | None:
    act_uri = URIRef(f"{BASE_URI}/act/{entity_id}/00/1")
    for _, _, technique_uri in graph.triples((act_uri, P32_USED_GENERAL_TECHNIQUE, None)):
        return AAT_TECHNIQUE_LABELS[str(technique_uri)]
    return None


def extract_devices(graph: Graph, entity_id: str) -> list[str]:
    act_uri = URIRef(f"{BASE_URI}/act/{entity_id}/00/1")
    devices = []
    for _, _, obj_uri in graph.triples((act_uri, P16_USED_SPECIFIC_OBJECT, None)):
        uri_str = str(obj_uri)
        if "/dev/" in uri_str:
            slug = uri_str.split("/dev/")[1].split("/")[0]
            devices.append(_format_slug(slug))
    return sorted(devices)


def extract_software_for_stage(graph: Graph, entity_id: str, stage: str) -> list[str]:
    steps = [s for s in STAGE_STEPS[stage] if s != METADATA_STEP]
    software: set[str] = set()
    for step in steps:
        act_uri = URIRef(f"{BASE_URI}/act/{entity_id}/{step}/1")
        for _, _, sfw_uri in graph.triples((act_uri, L23_USED_SOFTWARE, None)):
            uri_str = str(sfw_uri)
            slug = uri_str.split("/sfw/")[1].split("/")[0]
            software.add(_format_slug(slug))
    return sorted(software)


LICENSE_URI_TO_ZENODO = {
    "https://creativecommons.org/publicdomain/zero/1.0/": "cc0-1.0",
    "https://creativecommons.org/licenses/by/4.0/": "cc-by-4.0",
    "https://creativecommons.org/licenses/by-nc/4.0/": "cc-by-nc-4.0",
    "https://creativecommons.org/licenses/by-sa/4.0/": "cc-by-sa-4.0",
    "https://creativecommons.org/licenses/by-nc-sa/4.0/": "cc-by-nc-sa-4.0",
}

STAGE_TITLE_NAMES = {
    "raw": "Raw",
    "rawp": "Processed raw model",
    "dcho": "Digital Cultural Heritage Object",
    "dchoo": "Optimized Digital Cultural Heritage Object",
}

STAGE_DESCRIPTION_NAMES = {
    "raw": "Raw acquisition data",
    "rawp": "Processed raw model",
    "dcho": "Digital Cultural Heritage Object",
    "dchoo": "Optimized Digital Cultural Heritage Object",
}

STAGE_DESCRIPTIONS = {
    "raw": "This dataset contains the raw material generated during the acquisition phase.",
    "rawp": "This dataset contains the preliminary output from the photogrammetry or scanner software after initial data processing but without any interpolation or geometry corrections.",
    "dcho": "This dataset contains the version that includes interpolation, gap filling, and resolution of geometric issues, resulting in a refined and improved model.",
    "dchoo": "This dataset contains the version optimised for real-time online interaction.",
}

PROPAGATED_FIELDS = (
    "zenodo_url", "access_token", "user_agent",
    "subjects", "publication_date",
    "version", "community",
    "contributors", "funding",
    "references", "dates",
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


CC0_DISCLAIMER = (
    "No copyright or related rights are claimed in these digital reproductions. "
    "The files are released under CC0 1.0 Universal (Public Domain Dedication).\n"
    "\n"
    "Please note that the original works may qualify as cultural heritage assets "
    "under Italian law (D. Lgs. 42/2004). Consequently, although the digital "
    "reproductions are released under CC0, certain uses — and in particular "
    "commercial uses — may be subject to specific authorisations, restrictions, "
    "or fees pursuant to the applicable provisions governing the reproduction "
    "and publication of cultural heritage assets. Users are therefore responsible "
    "for ensuring compliance with Italian cultural heritage regulations before "
    "undertaking any commercial exploitation of the images."
)


CHAD_AP_URL = "https://w3id.org/dharc/ontology/chad-ap"

RESTRICTED_NOTICE = (
    "The digital object files are not included in this dataset "
    "because the holding institution did not grant permission for their publication. "
    "Only metadata and provenance files are provided."
)


def build_enhanced_description(
    stage: str,
    title: str,
    keeper_name: str | None = None,
    keeper_location: str | None = None,
) -> str:
    parts = [
        f'{STAGE_DESCRIPTION_NAMES[stage]} of "{title}" from the Aldrovandi Digital Twin.',
    ]
    if keeper_name:
        keeper_line = f"The original object is held by {keeper_name}"
        if keeper_location:
            keeper_line += f" ({keeper_location})"
        keeper_line += "."
        parts.append(keeper_line)
    parts.append(STAGE_DESCRIPTIONS[stage])
    parts.append(
        f"Includes metadata (meta.ttl) and provenance (prov.trig) files following the <a href=\"{CHAD_AP_URL}\">CHAD-AP</a> ontology.",
    )
    return " ".join(parts) + "\n"


WORKFLOW_DOI_URL = "https://doi.org/10.46298/transformations.14773"


def build_methods_description(
    graph: Graph,
    entity_id: str,
    stage: str,
) -> str:
    parts = [
        f'Acquisition and digitization followed the reproducible workflow documented in '
        f'<a href="{WORKFLOW_DOI_URL}">doi:10.46298/transformations.14773</a>.',
    ]
    technique = extract_acquisition_technique(graph, entity_id)
    devices = extract_devices(graph, entity_id)
    if technique:
        line = f"Data was acquired using {technique}"
        if devices:
            line += f" ({', '.join(devices)})"
        line += "."
        parts.append(line)
    software = extract_software_for_stage(graph, entity_id, stage)
    if software:
        parts.append(f"Processing software: {', '.join(software)}.")
    parts.append(
        f'Metadata follows the <a href="{CHAD_AP_URL}">Cultural Heritage Acquisition and '
        f"Digitisation Application Profile (CHAD-AP)</a> based on CIDOC-CRM.",
    )
    return "\n\n".join(parts) + "\n"


def build_entity_uri(entity_id: str) -> str:
    return f"{BASE_URI}/itm/{entity_id}/ob00/1"


LICENSE_INFO = {
    "cc0-1.0": {
        "title": "Creative Commons Zero v1.0 Universal",
        "link": "https://creativecommons.org/publicdomain/zero/1.0/",
    },
    "cc-by-4.0": {
        "title": "Creative Commons Attribution 4.0 International",
        "link": "https://creativecommons.org/licenses/by/4.0/",
    },
    "cc-by-nc-4.0": {
        "title": "Creative Commons Attribution Non Commercial 4.0 International",
        "link": "https://creativecommons.org/licenses/by-nc/4.0/",
    },
    "cc-by-sa-4.0": {
        "title": "Creative Commons Attribution Share Alike 4.0 International",
        "link": "https://creativecommons.org/licenses/by-sa/4.0/",
    },
    "cc-by-nc-sa-4.0": {
        "title": "Creative Commons Attribution Non Commercial Share Alike 4.0 International",
        "link": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    },
}


def build_rights(content_license: str | None) -> list[dict]:
    metadata_info = LICENSE_INFO["cc0-1.0"]
    rights = [{
        "title": {"en": f"{metadata_info['title']} (Metadata license)"},
        "description": {"en": "Applies to metadata files: meta.ttl, prov.trig"},
        "link": metadata_info["link"],
    }]
    if content_license and content_license in LICENSE_INFO:
        content_info = LICENSE_INFO[content_license]
        rights.append({
            "title": {"en": f"{content_info['title']} (Content license)"},
            "description": {"en": "Applies to all data files except meta.ttl and prov.trig"},
            "link": content_info["link"],
        })
    return rights


def generate_zenodo_config(
    stage: str,
    zip_path: Path,
    title: str,
    base_config: dict,
    creators: list[dict],
    methods_description: str,
    license: str | None = None,
    entity_uri: str | None = None,
    keeper_name: str | None = None,
    keeper_location: str | None = None,
    has_license: bool = True,
) -> dict:
    description = build_enhanced_description(stage, title, keeper_name, keeper_location)

    config: dict = {
        "title": f"{title} - {STAGE_TITLE_NAMES[stage]} - Aldrovandi Digital Twin",
        "description": description,
        "resource_type": {"id": "dataset"},
        "publisher": "Zenodo",
        "access": {"record": "public", "files": "public"},
        "files": [str(zip_path.absolute())],
        "creators": creators,
        "publication_date": date.today().isoformat(),
        "rights": build_rights(license),
    }

    additional_descriptions: list[dict] = [
        {
            "description": methods_description,
            "type": {"id": "methods"},
        },
        {
            "description": base_config["notes"],
            "type": {"id": "notes"},
        },
    ]
    if not has_license:
        additional_descriptions.append({
            "description": RESTRICTED_NOTICE,
            "type": {"id": "notes"},
        })
    if license == "cc0-1.0":
        additional_descriptions.append({
            "description": CC0_DISCLAIMER,
            "type": {"id": "notes"},
        })
    config["additional_descriptions"] = additional_descriptions

    config["locations"] = {
        "features": [
            {
                "geometry": {
                    "type": "Point",
                    "coordinates": [loc["lon"], loc["lat"]],
                },
                "place": loc["place"],
                "description": loc["description"],
            }
            for loc in base_config["locations"]
        ]
    }

    for field in PROPAGATED_FIELDS:
        if field in base_config and field not in config:
            config[field] = base_config[field]

    if "related_identifiers" in base_config:
        converted = []
        for ri in base_config["related_identifiers"]:
            entry: dict = {
                "identifier": ri["identifier"],
                "relation_type": {"id": ri["relation"]},
            }
            if "resource_type" in ri:
                entry["resource_type"] = {"id": ri["resource_type"]}
            if "scheme" in ri:
                entry["scheme"] = ri["scheme"]
            converted.append(entry)
        config["related_identifiers"] = converted

    if entity_uri:
        config["identifiers"] = [{"identifier": entity_uri, "scheme": "url"}]

    return config


def prepare_all(
    root: Path,
    zenodo_base_config_path: Path,
    output_dir: Path,
    kg_path: Path = KG_PATH,
) -> None:
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
            keeper_name, keeper_location = extract_keeper_info(kg, entity_id)
            sala_slug = slugify(folders[0][0])
            title_slug = slugify(title)
            metadata_creators = build_metadata_creators(kg, entity_id, creators_lookup)
            for stage in STAGES:
                progress.update(task, description=f"Entity {entity_id} - {stage}")
                result = create_stage_zip(entity_id, stage, folders, root, licensed_stages, zips_dir, title)
                if result is None:
                    progress.advance(task)
                    continue
                zip_path, has_license = result
                digitization_creators = build_creators_for_entity_stage(kg, entity_id, stage, creators_lookup)
                creators = merge_creators(digitization_creators, metadata_creators)
                license = extract_license_for_entity_stage(kg, entity_id, stage)
                entity_uri = build_entity_uri(entity_id)
                methods_description = build_methods_description(kg, entity_id, stage)
                config = generate_zenodo_config(stage, zip_path, title, base_config, creators, methods_description, license, entity_uri, keeper_name, keeper_location, has_license)
                config_path = configs_dir / f"{sala_slug}-{title_slug}-{stage}.yaml"
                with open(config_path, "w") as f:
                    yaml.dump(config, f, Dumper=LiteralBlockDumper, default_flow_style=False, allow_unicode=True, sort_keys=False)
                progress.advance(task)


def _extract_doi(record: dict) -> str:
    pids = record.get("pids", {})
    doi_info = pids.get("doi", {})
    return doi_info.get("identifier", "")


def _extract_record_url(record: dict) -> str:
    return record["links"]["self_html"]


LICENSE_TITLE_TO_SHORT: dict[str, str] = {
    info["title"]: short_name for short_name, info in LICENSE_INFO.items()
}


def _format_creators_for_table(config: dict) -> str:
    creators = config["creators"]
    parts: list[str] = []
    for c in creators:
        org = c["person_or_org"]
        orcid = org["identifiers"][0]["identifier"]
        parts.append(f"{org['family_name']}, {org['given_name']} [orcid:{orcid}]")
    return "; ".join(parts)


def _format_licenses_for_table(config: dict) -> str:
    parts: list[str] = []
    for right in config["rights"]:
        title_en = right["title"]["en"]
        for full_name, short_name in LICENSE_TITLE_TO_SHORT.items():
            if title_en.startswith(full_name):
                context = title_en.removeprefix(full_name).strip(" ()")
                parts.append(f"{short_name} ({context})")
                break
    return "; ".join(parts)


DOI_TABLE_FIELDNAMES = [
    "Numero su DMP",
    "Caso di studio",
    "Autore/i",
    "Tipo",
    "Titolo",
    "Data pubblicazione",
    "DOI",
    "URL",
    "Repository",
    "Licenza",
    "Note",
]


def upload_all(configs_dir: Path, publish: bool = False) -> Path:
    config_files = sorted(configs_dir.glob("*.yaml"))
    doi_table: list[dict[str, str]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    ) as progress:
        task = progress.add_task("Uploading to Zenodo", total=len(config_files))
        for config_file in config_files:
            progress.update(task, description=f"Uploading {config_file.stem}")
            record = piccione_upload(str(config_file), publish=publish)
            with open(config_file) as f:
                config = yaml.safe_load(f)
            row: dict[str, str] = {
                "Numero su DMP": "",
                "Caso di studio": "Aldrovandi",
                "Autore/i": _format_creators_for_table(config),
                "Tipo": "Dataset",
                "Titolo": config["title"],
                "Data pubblicazione": config["publication_date"],
                "DOI": _extract_doi(record),
                "URL": _extract_record_url(record),
                "Repository": "Zenodo",
                "Licenza": _format_licenses_for_table(config),
                "Note": "",
            }
            doi_table.append(row)
            progress.advance(task)

    csv_path = configs_dir.parent / "doi_table.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DOI_TABLE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(doi_table)
    print(f"DOI table written to {csv_path}")
    return csv_path


def parse_arguments():  # pragma: no cover
    parser = argparse.ArgumentParser(description="Prepare and upload Zenodo packages")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="Create zips and YAML configs")
    prepare_parser.add_argument("root", type=Path, help="Root directory with Sala/Folder/Stage structure")
    prepare_parser.add_argument("zenodo_config", type=Path, help="Base Zenodo configuration YAML")
    prepare_parser.add_argument("--output", "-o", type=Path, default=Path("zenodo_output"), help="Output directory")
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
        )
    elif args.command == "upload":
        upload_all(configs_dir=args.configs_dir, publish=args.publish)


if __name__ == "__main__":  # pragma: no cover
    main()
