# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelomas@gmail.com>
#
# SPDX-License-Identifier: ISC

import csv
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import yaml

import pytest
from rdflib import Graph, Literal, URIRef

from changes_metadata_manager.folder_metadata_builder import load_kg
from changes_metadata_manager.zenodo_upload import (
    AAT,
    BASE_URI,
    CC0_DISCLAIMER,
    RESTRICTED_NOTICE,
    E21_PERSON,
    P14_CARRIED_OUT_BY,
    P16_USED_SPECIFIC_OBJECT,
    P190_HAS_SYMBOLIC_CONTENT,
    P1_IS_IDENTIFIED_BY,
    P32_USED_GENERAL_TECHNIQUE,
    P3_HAS_NOTE,
    P70I,
    P74_HAS_RESIDENCE,
    RDF_TYPE,
    _atomic_write_json,
    _extract_doi,
    _extract_license_from_meta,
    _extract_record_url,
    _format_creators_for_table,
    _format_licenses_for_table,
    _write_doi_table,
    build_creators_for_entity_stage,
    build_enhanced_description,
    build_entity_uri,
    build_metadata_creators,
    build_methods_description,
    create_stage_zip,
    extract_acquisition_technique,
    extract_authors_for_entity_stage,
    extract_devices,
    extract_entity_title,
    extract_keeper_info,
    extract_license_for_entity_stage,
    extract_licensed_entity_stages,
    extract_metadata_authors,
    extract_software_for_stage,
    generate_zenodo_config,
    group_folders_by_entity,
    load_creators_lookup,
    merge_creators,
    publish_all_drafts,
    slugify,
    upload_all,
)


DATA_DIR = Path(__file__).parent.parent / "data"
REAL_KG_PATH = DATA_DIR / "kg.ttl"


@pytest.fixture(scope="module")
def real_kg():
    return load_kg(REAL_KG_PATH)


class TestExtractLicensedEntityStages:
    def test_returns_set_of_tuples(self, real_kg):
        result = extract_licensed_entity_stages(real_kg)
        assert isinstance(result, set)
        assert all(isinstance(item, tuple) and len(item) == 2 for item in result)

    def test_known_licensed_entity(self, real_kg):
        result = extract_licensed_entity_stages(real_kg)
        assert ("1", "dcho") in result
        assert ("1", "dchoo") in result

    def test_maps_steps_to_stages(self):
        g = Graph()
        g.add((URIRef(f"{BASE_URI}/lic/42/00/1"), P70I, URIRef("https://example.com/license")))
        g.add((URIRef(f"{BASE_URI}/lic/42/01/1"), P70I, URIRef("https://example.com/license")))
        g.add((URIRef(f"{BASE_URI}/lic/42/02/1"), P70I, URIRef("https://example.com/license")))
        g.add((URIRef(f"{BASE_URI}/lic/42/03/1"), P70I, URIRef("https://example.com/license")))
        result = extract_licensed_entity_stages(g)
        assert result == {("42", "raw"), ("42", "rawp"), ("42", "dcho"), ("42", "dchoo")}


class TestGroupFoldersByEntity:
    def test_groups_folders_by_entity_id(self):
        structure = {
            "structure": {
                "Sala1": {
                    "S1-01-Test": {"raw": {}, "dcho": {}},
                    "S1-02-Other": {"raw": {}},
                },
            }
        }
        result = group_folders_by_entity(structure)
        assert "1" in result
        assert "2" in result
        assert len(result["1"]) == 1
        assert result["1"][0][1] == "S1-01-Test"

    def test_groups_abc_variants(self):
        structure = {
            "structure": {
                "Sala6": {
                    "S6-98a-DA-Calchi facciali colorati, boscimani": {"raw": {}},
                    "S6-98b-DA-Calchi facciali colorati, boscimani": {"raw": {}},
                    "S6-98c-DA-Calchi facciali colorati, boscimani": {"raw": {}},
                },
            }
        }
        result = group_folders_by_entity(structure)
        assert "98" in result
        assert len(result["98"]) == 3

    def test_skips_skip_folders(self):
        structure = {
            "structure": {
                "Sala1": {
                    "S1-CNR_SoffittoSala1": {"raw": {}},
                    "materials": {"raw": {}},
                    "S1-01-Test": {"raw": {}},
                },
            }
        }
        result = group_folders_by_entity(structure)
        assert "1" in result
        folder_names = [f[1] for f in result["1"]]
        assert "S1-CNR_SoffittoSala1" not in folder_names
        assert "materials" not in folder_names


class TestSlugify:
    def test_simple_text(self):
        assert slugify("Carta nautica") == "carta-nautica"

    def test_accented_characters(self):
        assert slugify("Oggettò àccéntàto") == "oggetto-accentato"

    def test_special_characters(self):
        assert slugify("Test (object) #1") == "test-object-1"

    def test_multiple_spaces(self):
        assert slugify("Multiple   spaces   here") == "multiple-spaces-here"

    def test_leading_trailing_spaces(self):
        assert slugify("  trimmed  ") == "trimmed"


LICENSED_META_TTL = """\
@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .

<https://w3id.org/changes/4/aldrovandi/lic/1/00/1>
    crm:P70i_is_documented_in <https://creativecommons.org/publicdomain/zero/1.0/> .
"""

UNLICENSED_META_TTL = """\
@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .

<https://w3id.org/changes/4/aldrovandi/itm/1/ob00/1>
    crm:P3_has_note "Test object" .
"""


class TestExtractLicenseFromMeta:
    def test_returns_license_id_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stage_dir = Path(tmpdir)
            (stage_dir / "meta.ttl").write_text(LICENSED_META_TTL)
            assert _extract_license_from_meta(stage_dir) == "cc0-1.0"

    def test_returns_none_when_no_license(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stage_dir = Path(tmpdir)
            (stage_dir / "meta.ttl").write_text(UNLICENSED_META_TTL)
            assert _extract_license_from_meta(stage_dir) is None


class TestCreateStageZip:
    def test_includes_all_files_for_licensed_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            stage_dir = root / "Sala1" / "S1-01-Test" / "raw"
            stage_dir.mkdir(parents=True)
            (stage_dir / "meta.ttl").write_text(LICENSED_META_TTL)
            (stage_dir / "prov.trig").write_text("{}")
            (stage_dir / "photo.jpg").write_text("image")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [("Sala1", "S1-01-Test", {"raw": {}})]

            result = create_stage_zip("1", "raw", folders, root, output_dir, "Test Object")

            assert result is not None
            zip_path, license_id = result
            assert zip_path.name == "sala1-test-object-raw.zip"
            assert license_id == "cc0-1.0"
            with zipfile.ZipFile(zip_path) as zf:
                names = sorted(zf.namelist())
                assert names == ["S1-01-Test/raw/meta.ttl", "S1-01-Test/raw/photo.jpg", "S1-01-Test/raw/prov.trig"]

    def test_includes_only_metadata_for_unlicensed_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            stage_dir = root / "Sala1" / "S1-01-Test" / "raw"
            stage_dir.mkdir(parents=True)
            (stage_dir / "meta.ttl").write_text(UNLICENSED_META_TTL)
            (stage_dir / "prov.trig").write_text("{}")
            (stage_dir / "photo.jpg").write_text("image")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [("Sala1", "S1-01-Test", {"raw": {}})]

            result = create_stage_zip("1", "raw", folders, root, output_dir, "Test Object")

            assert result is not None
            zip_path, license_id = result
            assert license_id is None
            with zipfile.ZipFile(zip_path) as zf:
                names = sorted(zf.namelist())
                assert names == ["S1-01-Test/raw/meta.ttl", "S1-01-Test/raw/prov.trig"]

    def test_multiple_folders_grouped_entity_license(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"

            for variant in ["a", "b"]:
                stage_dir = root / "Sala6" / f"S6-98{variant}-Test" / "raw"
                stage_dir.mkdir(parents=True)
                (stage_dir / "meta.ttl").write_text(LICENSED_META_TTL)
                (stage_dir / "photo.jpg").write_text("image")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [
                ("Sala6", "S6-98a-Test", {"raw": {}}),
                ("Sala6", "S6-98b-Test", {"raw": {}}),
            ]

            result = create_stage_zip("98", "raw", folders, root, output_dir, "Test Masks")

            assert result is not None
            zip_path, license_id = result
            assert license_id == "cc0-1.0"
            with zipfile.ZipFile(zip_path) as zf:
                names = sorted(zf.namelist())
                assert names == [
                    "S6-98a-Test/raw/meta.ttl",
                    "S6-98a-Test/raw/photo.jpg",
                    "S6-98b-Test/raw/meta.ttl",
                    "S6-98b-Test/raw/photo.jpg",
                ]

    def test_multiple_folders_unlicensed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"

            for variant in ["a", "b"]:
                stage_dir = root / "Sala6" / f"S6-98{variant}-Test" / "raw"
                stage_dir.mkdir(parents=True)
                (stage_dir / "meta.ttl").write_text(UNLICENSED_META_TTL)

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [
                ("Sala6", "S6-98a-Test", {"raw": {}}),
                ("Sala6", "S6-98b-Test", {"raw": {}}),
            ]

            result = create_stage_zip("98", "raw", folders, root, output_dir, "Test Masks")

            assert result is not None
            zip_path, license_id = result
            assert license_id is None
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert names == ["S6-98a-Test/raw/meta.ttl", "S6-98b-Test/raw/meta.ttl"]

    def test_license_in_later_folder_includes_all_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"

            stage_dir_a = root / "Sala6" / "S6-98a-Test" / "raw"
            stage_dir_a.mkdir(parents=True)
            (stage_dir_a / "meta.ttl").write_text(UNLICENSED_META_TTL)
            (stage_dir_a / "photo.jpg").write_text("image_a")

            stage_dir_b = root / "Sala6" / "S6-98b-Test" / "raw"
            stage_dir_b.mkdir(parents=True)
            (stage_dir_b / "meta.ttl").write_text(LICENSED_META_TTL)
            (stage_dir_b / "photo.jpg").write_text("image_b")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [
                ("Sala6", "S6-98a-Test", {"raw": {}}),
                ("Sala6", "S6-98b-Test", {"raw": {}}),
            ]

            result = create_stage_zip("98", "raw", folders, root, output_dir, "Test Masks")

            assert result is not None
            zip_path, license_id = result
            assert license_id == "cc0-1.0"
            with zipfile.ZipFile(zip_path) as zf:
                names = sorted(zf.namelist())
                assert names == [
                    "S6-98a-Test/raw/meta.ttl",
                    "S6-98a-Test/raw/photo.jpg",
                    "S6-98b-Test/raw/meta.ttl",
                    "S6-98b-Test/raw/photo.jpg",
                ]

    def test_returns_none_for_missing_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            stage_dir = root / "Sala1" / "S1-01-Test" / "raw"
            stage_dir.mkdir(parents=True)
            (stage_dir / "meta.ttl").write_text(UNLICENSED_META_TTL)

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [("Sala1", "S1-01-Test", {"raw": {}})]

            result = create_stage_zip("1", "dcho", folders, root, output_dir, "Test Object")

            assert result is None
            assert not (output_dir / "sala1-test-object-dcho.zip").exists()


class TestExtractEntityTitle:
    def test_extracts_title_from_kg(self, real_kg):
        title = extract_entity_title(real_kg, ["1"])
        assert title == "Carta nautica"

    def test_returns_default_for_missing(self):
        g = Graph()
        title = extract_entity_title(g, ["nonexistent"])
        assert title == "Entity nonexistent"

    def test_takes_first_line(self):
        g = Graph()
        item_uri = URIRef(f"{BASE_URI}/itm/42/ob00/1")
        g.add((item_uri, P3_HAS_NOTE, Literal("First line\nSecond line")))
        title = extract_entity_title(g, ["42"])
        assert title == "First line"


class TestExtractAuthorsForEntityStage:
    def test_extracts_author_from_kg(self, real_kg):
        authors = extract_authors_for_entity_stage(real_kg, ["1"], "raw")
        assert authors == {"Federica Bonifazi"}

    def test_accumulates_authors_across_steps(self, real_kg):
        authors = extract_authors_for_entity_stage(real_kg, ["1"], "dchoo")
        assert "Federica Bonifazi" in authors
        assert len(authors) > 1

    def test_returns_empty_for_missing_entity(self, real_kg):
        authors = extract_authors_for_entity_stage(real_kg, ["nonexistent"], "raw")
        assert authors == set()

    def test_extracts_from_synthetic_graph(self):
        g = Graph()
        act_uri = URIRef(f"{BASE_URI}/act/42/00/1")
        actor_uri = URIRef(f"{BASE_URI}/per/42/1")
        apl_uri = URIRef(f"{BASE_URI}/apl/42/1")
        g.add((act_uri, P14_CARRIED_OUT_BY, actor_uri))
        g.add((actor_uri, RDF_TYPE, E21_PERSON))
        g.add((actor_uri, P1_IS_IDENTIFIED_BY, apl_uri))
        g.add((apl_uri, P190_HAS_SYMBOLIC_CONTENT, Literal("Test Author")))
        authors = extract_authors_for_entity_stage(g, ["42"], "raw")
        assert authors == {"Test Author"}


class TestExtractMetadataAuthors:
    def test_extracts_step_05_authors(self):
        g = Graph()
        act_uri = URIRef(f"{BASE_URI}/act/42/05/1")
        actor_uri = URIRef(f"{BASE_URI}/per/meta/1")
        apl_uri = URIRef(f"{BASE_URI}/apl/meta/1")
        g.add((act_uri, P14_CARRIED_OUT_BY, actor_uri))
        g.add((actor_uri, RDF_TYPE, E21_PERSON))
        g.add((actor_uri, P1_IS_IDENTIFIED_BY, apl_uri))
        g.add((apl_uri, P190_HAS_SYMBOLIC_CONTENT, Literal("Metadata Author")))
        authors = extract_metadata_authors(g, ["42"])
        assert authors == {"Metadata Author"}

    def test_returns_empty_for_missing_entity(self):
        g = Graph()
        authors = extract_metadata_authors(g, ["nonexistent"])
        assert authors == set()

    def test_extracts_from_real_kg(self, real_kg):
        authors = extract_metadata_authors(real_kg, ["1"])
        assert authors == {"Arcangelo Massari", "Arianna Moretti", "Sebastian Barzaghi"}


class TestLoadCreatorsLookup:
    def test_loads_creators_as_dict(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(
                "creators:\n"
                "  - name_in_rdf: Test Author\n"
                "    family_name: Author\n"
                "    given_name: Test\n"
                "    affiliation: Test Uni\n"
                "    orcid: 0000-0001-2345-6789\n"
            )
            f.flush()
            lookup = load_creators_lookup(Path(f.name))
        assert lookup == {
            "Test Author": {
                "family_name": "Author",
                "given_name": "Test",
                "affiliation": "Test Uni",
                "orcid": "0000-0001-2345-6789",
            }
        }


class TestBuildCreatorsForEntityStage:
    def test_builds_creators_with_researcher_role(self, real_kg):
        lookup = {
            "Federica Bonifazi": {
                "family_name": "Bonifazi",
                "given_name": "Federica",
                "affiliation": "CNR-ISPC",
                "orcid": "0009-0000-8466-5541",
            }
        }
        creators = build_creators_for_entity_stage(real_kg, ["1"], "raw", lookup)
        assert creators == [
            {
                "person_or_org": {
                    "type": "personal",
                    "family_name": "Bonifazi",
                    "given_name": "Federica",
                    "identifiers": [{"scheme": "orcid", "identifier": "0009-0000-8466-5541"}],
                },
                "role": {"id": "researcher"},
                "affiliations": [{"name": "CNR-ISPC"}],
            }
        ]

    def test_ignores_authors_not_in_lookup(self, real_kg):
        lookup = {}
        creators = build_creators_for_entity_stage(real_kg, ["1"], "raw", lookup)
        assert creators == []

    def test_sorts_authors_alphabetically(self):
        g = Graph()
        for name in ["Zeta Author", "Alpha Author"]:
            act_uri = URIRef(f"{BASE_URI}/act/42/00/1")
            actor_uri = URIRef(f"{BASE_URI}/per/{name}/1")
            apl_uri = URIRef(f"{BASE_URI}/apl/{name}/1")
            g.add((act_uri, P14_CARRIED_OUT_BY, actor_uri))
            g.add((actor_uri, RDF_TYPE, E21_PERSON))
            g.add((actor_uri, P1_IS_IDENTIFIED_BY, apl_uri))
            g.add((apl_uri, P190_HAS_SYMBOLIC_CONTENT, Literal(name)))
        lookup = {
            "Alpha Author": {
                "family_name": "Author",
                "given_name": "Alpha",
                "affiliation": "Uni",
                "orcid": "0000-0000-0000-0001",
            },
            "Zeta Author": {
                "family_name": "Author",
                "given_name": "Zeta",
                "affiliation": "Uni",
                "orcid": "0000-0000-0000-0002",
            },
        }
        creators = build_creators_for_entity_stage(g, ["42"], "raw", lookup)
        assert [c["person_or_org"]["given_name"] for c in creators] == ["Alpha", "Zeta"]


class TestBuildMetadataCreators:
    def test_builds_creators_with_datacurator_role(self):
        g = Graph()
        act_uri = URIRef(f"{BASE_URI}/act/42/05/1")
        actor_uri = URIRef(f"{BASE_URI}/per/meta/1")
        apl_uri = URIRef(f"{BASE_URI}/apl/meta/1")
        g.add((act_uri, P14_CARRIED_OUT_BY, actor_uri))
        g.add((actor_uri, RDF_TYPE, E21_PERSON))
        g.add((actor_uri, P1_IS_IDENTIFIED_BY, apl_uri))
        g.add((apl_uri, P190_HAS_SYMBOLIC_CONTENT, Literal("Metadata Author")))
        lookup = {
            "Metadata Author": {
                "family_name": "Author",
                "given_name": "Metadata",
                "affiliation": "Test Uni",
                "orcid": "0000-0001-2345-6789",
            }
        }
        creators = build_metadata_creators(g, ["42"], lookup)
        assert creators == [
            {
                "person_or_org": {
                    "type": "personal",
                    "family_name": "Author",
                    "given_name": "Metadata",
                    "identifiers": [{"scheme": "orcid", "identifier": "0000-0001-2345-6789"}],
                },
                "role": {"id": "datacurator"},
                "affiliations": [{"name": "Test Uni"}],
            }
        ]


class TestMergeCreators:
    def test_merges_without_duplicates(self):
        digitization = [
            {
                "person_or_org": {
                    "type": "personal",
                    "family_name": "Author",
                    "given_name": "Digit",
                    "identifiers": [{"scheme": "orcid", "identifier": "0000-0000-0000-0001"}],
                },
                "role": {"id": "researcher"},
                "affiliations": [{"name": "Uni"}],
            }
        ]
        metadata = [
            {
                "person_or_org": {
                    "type": "personal",
                    "family_name": "Author",
                    "given_name": "Meta",
                    "identifiers": [{"scheme": "orcid", "identifier": "0000-0000-0000-0002"}],
                },
                "role": {"id": "datacurator"},
                "affiliations": [{"name": "Uni"}],
            }
        ]
        merged = merge_creators(digitization, metadata)
        assert len(merged) == 2
        assert merged[0]["role"] == {"id": "researcher"}
        assert merged[1]["role"] == {"id": "datacurator"}

    def test_deduplicates_by_orcid(self):
        digitization = [
            {
                "person_or_org": {
                    "type": "personal",
                    "family_name": "Shared",
                    "given_name": "Author",
                    "identifiers": [{"scheme": "orcid", "identifier": "0000-0000-0000-0001"}],
                },
                "role": {"id": "researcher"},
                "affiliations": [{"name": "Uni"}],
            }
        ]
        metadata = [
            {
                "person_or_org": {
                    "type": "personal",
                    "family_name": "Shared",
                    "given_name": "Author",
                    "identifiers": [{"scheme": "orcid", "identifier": "0000-0000-0000-0001"}],
                },
                "role": {"id": "datacurator"},
                "affiliations": [{"name": "Uni"}],
            }
        ]
        merged = merge_creators(digitization, metadata)
        assert len(merged) == 1
        assert merged[0]["role"] == {"id": "researcher"}

    def test_empty_lists(self):
        assert merge_creators([], []) == []

    def test_only_metadata_creators(self):
        metadata = [
            {
                "person_or_org": {
                    "type": "personal",
                    "family_name": "Author",
                    "given_name": "Meta",
                    "identifiers": [{"scheme": "orcid", "identifier": "0000-0000-0000-0001"}],
                },
                "role": {"id": "datacurator"},
                "affiliations": [{"name": "Uni"}],
            }
        ]
        merged = merge_creators([], metadata)
        assert len(merged) == 1
        assert merged[0]["role"] == {"id": "datacurator"}


class TestBuildEntityUri:
    def test_builds_uri_for_numeric_id(self):
        result = build_entity_uri(["27"])
        assert result == "https://w3id.org/changes/4/aldrovandi/itm/27/ob00/1"

    def test_builds_uri_for_string_id(self):
        result = build_entity_uri(["ptb"])
        assert result == "https://w3id.org/changes/4/aldrovandi/itm/ptb/ob00/1"


SAMPLE_CREATOR = {
    "person_or_org": {
        "type": "personal",
        "family_name": "Author",
        "given_name": "Test",
        "identifiers": [{"scheme": "orcid", "identifier": "0000-0001-2345-6789"}],
    },
    "role": {"id": "researcher"},
    "affiliations": [{"name": "Test Uni"}],
}

SAMPLE_BASE_CONFIG = {
    "zenodo_url": "https://sandbox.zenodo.org/api",
    "access_token": "test_token",
    "user_agent": "piccione/2.1.0",
    "subjects": [{"subject": "test"}],
    "notes": "Test notes content",
    "locations": [
        {
            "lat": 44.497,
            "lon": 11.353,
            "place": "Bologna, Italy",
            "description": "Palazzo Poggi Museum",
        },
    ],
}

SAMPLE_METHODS = "Test method content"


class TestGenerateZenodoConfig:
    def test_generates_valid_config(self, freezer):
        freezer.move_to("2024-06-15")
        zip_path = Path("/tmp/1-raw.zip")
        config = generate_zenodo_config("raw", zip_path, "Test Title", SAMPLE_BASE_CONFIG, [SAMPLE_CREATOR], SAMPLE_METHODS)

        assert config == {
            "zenodo_url": "https://sandbox.zenodo.org/api",
            "access_token": "test_token",
            "user_agent": "piccione/2.1.0",
            "title": "Test Title - Raw - Aldrovandi Digital Twin",
            "description": 'Raw acquisition data of "Test Title" from the Aldrovandi Digital Twin. This dataset contains the raw material generated during the acquisition phase. Includes metadata (meta.ttl) and provenance (prov.trig) files following the <a href="https://w3id.org/dharc/ontology/chad-ap">CHAD-AP</a> ontology.\n',
            "resource_type": {"id": "dataset"},
            "publisher": "Zenodo",
            "access": {"record": "public", "files": "public"},
            "creators": [SAMPLE_CREATOR],
            "subjects": [{"subject": "test"}],
            "files": [str(zip_path.absolute())],
            "publication_date": "2024-06-15",
            "rights": [
                {
                    "title": {"en": "Creative Commons Zero v1.0 Universal (Metadata license)"},
                    "description": {"en": "Applies to metadata files: meta.ttl, prov.trig"},
                    "link": "https://creativecommons.org/publicdomain/zero/1.0/",
                },
            ],
            "additional_descriptions": [
                {"description": "Test method content", "type": {"id": "methods"}},
                {"description": "Test notes content", "type": {"id": "notes"}},
            ],
            "locations": {
                "features": [
                    {
                        "geometry": {"type": "Point", "coordinates": [11.353, 44.497]},
                        "place": "Bologna, Italy",
                        "description": "Palazzo Poggi Museum",
                    },
                ]
            },
        }

    def test_adds_entity_uri_as_alternate_identifier(self, freezer):
        freezer.move_to("2024-06-15")
        zip_path = Path("/tmp/27-raw.zip")
        entity_uri = "https://w3id.org/changes/4/aldrovandi/itm/27/ob00/1"
        config = generate_zenodo_config("raw", zip_path, "Test Title", SAMPLE_BASE_CONFIG, [SAMPLE_CREATOR], SAMPLE_METHODS, entity_uri=entity_uri)

        assert config["identifiers"] == [
            {"identifier": "https://w3id.org/changes/4/aldrovandi/itm/27/ob00/1", "scheme": "url"}
        ]

    def test_converts_related_identifiers(self, freezer):
        freezer.move_to("2024-06-15")
        base_config = {
            **SAMPLE_BASE_CONFIG,
            "related_identifiers": [
                {
                    "identifier": "10.3724/2096-7004.di.2024.0061",
                    "relation": "isdocumentedby",
                    "resource_type": "publication-article",
                }
            ],
        }
        zip_path = Path("/tmp/27-raw.zip")
        config = generate_zenodo_config("raw", zip_path, "Test Title", base_config, [SAMPLE_CREATOR], SAMPLE_METHODS)

        assert config["related_identifiers"] == [
            {
                "identifier": "10.3724/2096-7004.di.2024.0061",
                "relation_type": {"id": "isdocumentedby"},
                "resource_type": {"id": "publication-article"},
            },
        ]

    def test_converts_notes_and_method_to_additional_descriptions(self, freezer):
        freezer.move_to("2024-06-15")
        zip_path = Path("/tmp/1-raw.zip")
        config = generate_zenodo_config("raw", zip_path, "Test Title", SAMPLE_BASE_CONFIG, [SAMPLE_CREATOR], SAMPLE_METHODS)

        assert config["additional_descriptions"] == [
            {"description": "Test method content", "type": {"id": "methods"}},
            {"description": "Test notes content", "type": {"id": "notes"}},
        ]

    def test_cc0_disclaimer_in_additional_descriptions(self, freezer):
        freezer.move_to("2024-06-15")
        zip_path = Path("/tmp/1-raw.zip")
        config = generate_zenodo_config("raw", zip_path, "Test Title", SAMPLE_BASE_CONFIG, [SAMPLE_CREATOR], SAMPLE_METHODS, license="cc0-1.0")

        assert config["additional_descriptions"] == [
            {"description": "Test method content", "type": {"id": "methods"}},
            {"description": "Test notes content", "type": {"id": "notes"}},
            {"description": CC0_DISCLAIMER, "type": {"id": "notes"}},
        ]

    def test_converts_locations_to_geojson(self, freezer):
        freezer.move_to("2024-06-15")
        zip_path = Path("/tmp/1-raw.zip")
        config = generate_zenodo_config("raw", zip_path, "Test Title", SAMPLE_BASE_CONFIG, [SAMPLE_CREATOR], SAMPLE_METHODS)

        assert config["locations"] == {
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [11.353, 44.497]},
                    "place": "Bologna, Italy",
                    "description": "Palazzo Poggi Museum",
                },
            ]
        }

    def test_includes_community_field(self, freezer):
        freezer.move_to("2024-06-15")
        base_config = {**SAMPLE_BASE_CONFIG, "community": "project-changes"}
        zip_path = Path("/tmp/1-raw.zip")
        config = generate_zenodo_config("raw", zip_path, "Test Title", base_config, [SAMPLE_CREATOR], SAMPLE_METHODS)

        assert config["community"] == "project-changes"

    def test_includes_restricted_notice_when_no_license(self, freezer):
        freezer.move_to("2024-06-15")
        zip_path = Path("/tmp/1-raw.zip")
        config = generate_zenodo_config("raw", zip_path, "Test Title", SAMPLE_BASE_CONFIG, [SAMPLE_CREATOR], SAMPLE_METHODS, has_license=False)

        assert RESTRICTED_NOTICE not in config["description"]
        assert {"description": RESTRICTED_NOTICE, "type": {"id": "notes"}} in config["additional_descriptions"]

    def test_no_restricted_notice_when_licensed(self, freezer):
        freezer.move_to("2024-06-15")
        zip_path = Path("/tmp/1-raw.zip")
        config = generate_zenodo_config("raw", zip_path, "Test Title", SAMPLE_BASE_CONFIG, [SAMPLE_CREATOR], SAMPLE_METHODS, has_license=True)

        assert {"description": RESTRICTED_NOTICE, "type": {"id": "notes"}} not in config["additional_descriptions"]

    def test_propagates_funding_field(self, freezer):
        freezer.move_to("2024-06-15")
        funding = [
            {
                "funder": {"name": "European Union - NextGenerationEU"},
                "award": {
                    "title": {"en": "CHANGES"},
                    "number": "PE 0000020",
                },
            }
        ]
        base_config = {**SAMPLE_BASE_CONFIG, "funding": funding}
        zip_path = Path("/tmp/1-raw.zip")
        config = generate_zenodo_config("raw", zip_path, "Test Title", base_config, [SAMPLE_CREATOR], SAMPLE_METHODS)

        assert config["funding"] == funding


class TestExtractLicenseForEntityStage:
    def test_extracts_license_from_kg(self):
        g = Graph()
        lic_uri = URIRef(f"{BASE_URI}/lic/42/00/1")
        license_url = URIRef("https://creativecommons.org/publicdomain/zero/1.0/")
        g.add((lic_uri, P70I, license_url))
        result = extract_license_for_entity_stage(g, "42", "raw")
        assert result == "cc0-1.0"

    def test_returns_none_for_missing_license(self):
        g = Graph()
        result = extract_license_for_entity_stage(g, "42", "raw")
        assert result is None

    def test_returns_none_for_unknown_license_uri(self):
        g = Graph()
        lic_uri = URIRef(f"{BASE_URI}/lic/42/00/1")
        unknown_license = URIRef("https://example.com/custom-license")
        g.add((lic_uri, P70I, unknown_license))
        result = extract_license_for_entity_stage(g, "42", "raw")
        assert result is None

    def test_extracts_cc_by(self):
        g = Graph()
        lic_uri = URIRef(f"{BASE_URI}/lic/42/00/1")
        license_url = URIRef("https://creativecommons.org/licenses/by/4.0/")
        g.add((lic_uri, P70I, license_url))
        result = extract_license_for_entity_stage(g, "42", "raw")
        assert result == "cc-by-4.0"


class TestExtractKeeperInfo:
    def test_extracts_keeper_from_kg(self, real_kg):
        keeper_name, keeper_location = extract_keeper_info(real_kg, ["1"])
        assert keeper_name == "Biblioteca Universitaria di Bologna"
        assert keeper_location == "Bologna"

    def test_extracts_non_bologna_keeper(self, real_kg):
        keeper_name, keeper_location = extract_keeper_info(real_kg, ["21"])
        assert keeper_name == "Accademia Carrara"
        assert keeper_location == "Bergamo"

    def test_returns_none_for_missing_entity(self, real_kg):
        keeper_name, keeper_location = extract_keeper_info(real_kg, ["nonexistent"])
        assert keeper_name is None
        assert keeper_location is None

    def test_extracts_from_synthetic_graph(self):
        g = Graph()
        custody_uri = URIRef(f"{BASE_URI}/act/42/ob08/1")
        keeper_uri = URIRef(f"{BASE_URI}/acr/test_museum/1")
        apl_uri = URIRef(f"{BASE_URI}/apl/test_museum/1")
        place_uri = URIRef(f"{BASE_URI}/plc/test_city/1")
        place_apl_uri = URIRef(f"{BASE_URI}/apl/test_city/1")
        g.add((custody_uri, P14_CARRIED_OUT_BY, keeper_uri))
        g.add((keeper_uri, P1_IS_IDENTIFIED_BY, apl_uri))
        g.add((apl_uri, P190_HAS_SYMBOLIC_CONTENT, Literal("Test Museum")))
        g.add((keeper_uri, P74_HAS_RESIDENCE, place_uri))
        g.add((place_uri, P1_IS_IDENTIFIED_BY, place_apl_uri))
        g.add((place_apl_uri, P190_HAS_SYMBOLIC_CONTENT, Literal("Test City")))
        keeper_name, keeper_location = extract_keeper_info(g, ["42"])
        assert keeper_name == "Test Museum"
        assert keeper_location == "Test City"

    def test_keeper_without_location(self):
        g = Graph()
        custody_uri = URIRef(f"{BASE_URI}/act/42/ob08/1")
        keeper_uri = URIRef(f"{BASE_URI}/acr/test_museum/1")
        apl_uri = URIRef(f"{BASE_URI}/apl/test_museum/1")
        g.add((custody_uri, P14_CARRIED_OUT_BY, keeper_uri))
        g.add((keeper_uri, P1_IS_IDENTIFIED_BY, apl_uri))
        g.add((apl_uri, P190_HAS_SYMBOLIC_CONTENT, Literal("Test Museum")))
        keeper_name, keeper_location = extract_keeper_info(g, ["42"])
        assert keeper_name == "Test Museum"
        assert keeper_location is None


class TestBuildEnhancedDescription:
    def test_raw_stage_description(self):
        result = build_enhanced_description("raw", "Test Object")
        assert result == (
            'Raw acquisition data of "Test Object" from the Aldrovandi Digital Twin. '
            "This dataset contains the raw material generated during the acquisition phase. "
            'Includes metadata (meta.ttl) and provenance (prov.trig) files following the <a href="https://w3id.org/dharc/ontology/chad-ap">CHAD-AP</a> ontology.\n'
        )

    def test_dcho_stage_description(self):
        result = build_enhanced_description("dcho", "Museum Specimen")
        assert "Digital Cultural Heritage Object" in result
        assert '"Museum Specimen"' in result
        assert "interpolation, gap filling, and resolution of geometric issues" in result

    def test_dchoo_stage_description(self):
        result = build_enhanced_description("dchoo", "Object Title")
        assert "Optimized Digital Cultural Heritage Object" in result
        assert "optimised for real-time online interaction" in result

    def test_description_never_contains_disclaimer(self):
        result = build_enhanced_description("dcho", "Test Object")
        assert CC0_DISCLAIMER not in result

    def test_includes_keeper_and_location(self):
        result = build_enhanced_description("raw", "Test Object", keeper_name="Test Museum", keeper_location="Test City")
        assert "The original object is held by Test Museum (Test City)." in result

    def test_includes_keeper_without_location(self):
        result = build_enhanced_description("raw", "Test Object", keeper_name="Test Museum")
        assert "The original object is held by Test Museum." in result
        assert "Test Museum (" not in result

    def test_no_keeper_line_when_none(self):
        result = build_enhanced_description("raw", "Test Object")
        assert "held by" not in result

    def test_description_is_single_paragraph(self):
        result = build_enhanced_description("raw", "Test Object", keeper_name="Museum", keeper_location="City")
        assert "\n" not in result.rstrip("\n")


class TestFormatCreatorsForTable:
    def test_formats_multiple_creators(self):
        config = {
            "creators": [
                {"person_or_org": {"family_name": "Bordignon", "given_name": "Alice", "identifiers": [{"scheme": "orcid", "identifier": "0009-0008-3556-0493"}]}},
                {"person_or_org": {"family_name": "Massari", "given_name": "Arcangelo", "identifiers": [{"scheme": "orcid", "identifier": "0000-0002-8420-0696"}]}},
            ]
        }
        assert _format_creators_for_table(config) == "Bordignon, Alice [orcid:0009-0008-3556-0493]; Massari, Arcangelo [orcid:0000-0002-8420-0696]"

    def test_formats_single_creator(self):
        config = {
            "creators": [
                {"person_or_org": {"family_name": "Barzaghi", "given_name": "Sebastian", "identifiers": [{"scheme": "orcid", "identifier": "0000-0002-0799-1527"}]}},
            ]
        }
        assert _format_creators_for_table(config) == "Barzaghi, Sebastian [orcid:0000-0002-0799-1527]"


class TestFormatLicensesForTable:
    def test_formats_cc0_metadata_and_content(self):
        config = {
            "rights": [
                {"title": {"en": "Creative Commons Zero v1.0 Universal (Metadata license)"}},
                {"title": {"en": "Creative Commons Zero v1.0 Universal (Content license)"}},
            ]
        }
        assert _format_licenses_for_table(config) == "cc0-1.0 (Metadata license); cc0-1.0 (Content license)"

    def test_formats_mixed_licenses(self):
        config = {
            "rights": [
                {"title": {"en": "Creative Commons Zero v1.0 Universal (Metadata license)"}},
                {"title": {"en": "Creative Commons Attribution Non Commercial Share Alike 4.0 International (Content license)"}},
            ]
        }
        assert _format_licenses_for_table(config) == "cc0-1.0 (Metadata license); cc-by-nc-sa-4.0 (Content license)"

    def test_formats_metadata_only(self):
        config = {
            "rights": [
                {"title": {"en": "Creative Commons Zero v1.0 Universal (Metadata license)"}},
            ]
        }
        assert _format_licenses_for_table(config) == "cc0-1.0 (Metadata license)"


class TestExtractDoi:
    def test_extracts_doi_from_record(self):
        record = {"pids": {"doi": {"identifier": "10.5281/zenodo.12345"}}}
        assert _extract_doi(record) == "10.5281/zenodo.12345"

    def test_returns_empty_string_on_sandbox(self):
        assert _extract_doi({}) == ""
        assert _extract_doi({"pids": {}}) == ""


class TestExtractRecordUrl:
    def test_extracts_url_from_record(self):
        record = {"links": {"self_html": "https://zenodo.org/records/12345"}}
        assert _extract_record_url(record) == "https://zenodo.org/records/12345"


class TestExtractAcquisitionTechnique:
    def test_extracts_photography_from_kg(self, real_kg):
        technique = extract_acquisition_technique(real_kg, ["1"])
        assert technique == "digital photography"

    def test_extracts_scanning_from_kg(self, real_kg):
        technique = extract_acquisition_technique(real_kg, ["12"])
        assert technique == "optical scanning"

    def test_returns_none_for_missing_entity(self):
        g = Graph()
        assert extract_acquisition_technique(g, ["nonexistent"]) is None

    def test_extracts_from_synthetic_graph(self):
        g = Graph()
        act_uri = URIRef(f"{BASE_URI}/act/42/00/1")
        g.add((act_uri, P32_USED_GENERAL_TECHNIQUE, URIRef(f"{AAT}300266792")))
        assert extract_acquisition_technique(g, ["42"]) == "digital photography"


class TestExtractDevices:
    def test_extracts_devices_from_kg(self, real_kg):
        devices = extract_devices(real_kg, ["1"])
        assert devices == ["Nikkor 50mm", "Nikon D7200"]

    def test_extracts_scanner_device(self, real_kg):
        devices = extract_devices(real_kg, ["12"])
        assert devices == ["Artec Eva"]

    def test_returns_empty_for_missing_entity(self):
        g = Graph()
        assert extract_devices(g, ["nonexistent"]) == []

    def test_excludes_item_uris(self):
        g = Graph()
        act_uri = URIRef(f"{BASE_URI}/act/42/00/1")
        g.add((act_uri, P16_USED_SPECIFIC_OBJECT, URIRef(f"{BASE_URI}/dev/nikon_d7200/1")))
        g.add((act_uri, P16_USED_SPECIFIC_OBJECT, URIRef(f"{BASE_URI}/itm/42/ob00/1")))
        devices = extract_devices(g, ["42"])
        assert devices == ["Nikon D7200"]


class TestExtractSoftwareForStage:
    def test_extracts_raw_software(self, real_kg):
        software = extract_software_for_stage(real_kg, ["1"], "raw")
        assert software == []

    def test_extracts_rawp_software(self, real_kg):
        software = extract_software_for_stage(real_kg, ["1"], "rawp")
        assert "3DF Zephyr" in software

    def test_excludes_metadata_step_software(self, real_kg):
        software = extract_software_for_stage(real_kg, ["1"], "dchoo")
        assert "CHAD-AP" not in software
        assert "HeriTrace" not in software
        assert "Morph-KGC" not in software

    def test_includes_step_06_software(self, real_kg):
        software = extract_software_for_stage(real_kg, ["1"], "dchoo")
        assert "ATON" in software

    def test_returns_empty_for_missing_entity(self):
        g = Graph()
        assert extract_software_for_stage(g, ["nonexistent"], "raw") == []


class TestBuildMethodsDescription:
    def test_includes_workflow_reference(self):
        g = Graph()
        result = build_methods_description(g, ["nonexistent"], "raw")
        assert "doi:10.46298/transformations.14773" in result

    def test_includes_technique_and_devices(self, real_kg):
        result = build_methods_description(real_kg, ["1"], "raw")
        assert "digital photography" in result
        assert "Nikon D7200" in result

    def test_includes_software_for_rawp(self, real_kg):
        result = build_methods_description(real_kg, ["1"], "rawp")
        assert "Processing software:" in result
        assert "3DF Zephyr" in result

    def test_no_software_for_raw(self, real_kg):
        result = build_methods_description(real_kg, ["1"], "raw")
        assert "Processing software:" not in result

    def test_includes_chad_ap_reference(self):
        g = Graph()
        result = build_methods_description(g, ["nonexistent"], "raw")
        assert "CHAD-AP" in result

    def test_scanning_entity(self, real_kg):
        result = build_methods_description(real_kg, ["12"], "raw")
        assert "optical scanning" in result
        assert "Artec Eva" in result


MINIMAL_CONFIG = {
    "title": "Test Object - Raw - Aldrovandi Digital Twin",
    "zenodo_url": "https://sandbox.zenodo.org/api",
    "access_token": "fake-token",
    "user_agent": "test/1.0",
    "publication_date": "2026-05-22",
    "creators": [{
        "person_or_org": {
            "type": "personal",
            "family_name": "Rossi",
            "given_name": "Mario",
            "identifiers": [{"scheme": "orcid", "identifier": "0000-0001-0000-0001"}],
        },
        "role": {"id": "researcher"},
        "affiliations": [{"name": "University of Bologna"}],
    }],
    "rights": [{"title": {"en": "Creative Commons Zero v1.0 Universal (Metadata license)"}, "link": "https://creativecommons.org/publicdomain/zero/1.0/"}],
}

MOCK_RECORD = {
    "id": "999001",
    "pids": {"doi": {"identifier": "10.5281/zenodo.999001"}},
    "links": {"self_html": "https://sandbox.zenodo.org/records/999001"},
}


def _write_config(path: Path, overrides: dict | None = None) -> Path:
    if overrides is None:
        overrides = {}
    config = {**MINIMAL_CONFIG, **overrides}
    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    return path


class TestAtomicWriteJson:
    def test_writes_json(self, tmp_path):
        path = tmp_path / "data.json"
        _atomic_write_json(path, [{"a": 1}])
        with open(path) as f:
            assert json.load(f) == [{"a": 1}]

    def test_overwrites_existing(self, tmp_path):
        path = tmp_path / "data.json"
        _atomic_write_json(path, [{"old": True}])
        _atomic_write_json(path, [{"new": True}])
        with open(path) as f:
            assert json.load(f) == [{"new": True}]


class TestWriteDoiTable:
    def test_generates_csv_from_drafts(self, tmp_path):
        config_path = _write_config(tmp_path / "test-raw.yaml")
        drafts = [{
            "draft_id": "100",
            "config_file": str(config_path),
            "title": "Test",
            "zenodo_url": "https://sandbox.zenodo.org/api",
            "access_token": "tok",
            "user_agent": "ua",
            "status": "uploaded",
            "doi": "10.5281/zenodo.100",
            "record_url": "https://sandbox.zenodo.org/records/100",
        }]
        csv_path = _write_doi_table(drafts, tmp_path)
        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["DOI"] == "10.5281/zenodo.100"
        assert rows[0]["Titolo"] == "Test Object - Raw - Aldrovandi Digital Twin"

    def test_skips_failed_entries(self, tmp_path):
        config_path = _write_config(tmp_path / "test-raw.yaml")
        drafts = [
            {
                "draft_id": "100",
                "config_file": str(config_path),
                "title": "Good",
                "zenodo_url": "",
                "access_token": "",
                "user_agent": "",
                "status": "uploaded",
                "doi": "10.5281/zenodo.100",
                "record_url": "https://sandbox.zenodo.org/records/100",
            },
            {
                "draft_id": "",
                "config_file": str(config_path),
                "title": "Bad",
                "zenodo_url": "",
                "access_token": "",
                "user_agent": "",
                "status": "failed",
                "doi": "",
                "record_url": "",
                "error": "boom",
            },
        ]
        csv_path = _write_doi_table(drafts, tmp_path)
        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1


class TestUploadAllResume:
    def _setup_configs(self, tmp_path):
        configs_dir = tmp_path / "configs"
        configs_dir.mkdir()
        _write_config(configs_dir / "entity-a-raw.yaml", {"title": "Entity A - Raw"})
        _write_config(configs_dir / "entity-b-raw.yaml", {"title": "Entity B - Raw"})
        _write_config(configs_dir / "entity-c-raw.yaml", {"title": "Entity C - Raw"})
        return configs_dir

    @patch("changes_metadata_manager.zenodo_upload.time.sleep")
    @patch("changes_metadata_manager.zenodo_upload.piccione_upload")
    def test_fresh_upload(self, mock_upload, mock_sleep, tmp_path):
        configs_dir = self._setup_configs(tmp_path)
        call_count = 0

        def side_effect(config_file, publish=False):
            nonlocal call_count
            call_count += 1
            return {
                "id": f"draft-{call_count}",
                "pids": {},
                "links": {"self_html": f"https://sandbox.zenodo.org/records/draft-{call_count}"},
            }

        mock_upload.side_effect = side_effect
        upload_all(configs_dir, publish=False)

        drafts_path = tmp_path / "drafts.json"
        with open(drafts_path) as f:
            drafts = json.load(f)
        assert len(drafts) == 3
        assert all(d["status"] == "uploaded" for d in drafts)
        assert mock_upload.call_count == 3

    @patch("changes_metadata_manager.zenodo_upload.time.sleep")
    @patch("changes_metadata_manager.zenodo_upload.piccione_upload")
    def test_resume_skips_completed(self, mock_upload, mock_sleep, tmp_path):
        configs_dir = self._setup_configs(tmp_path)
        drafts_path = tmp_path / "drafts.json"
        _atomic_write_json(drafts_path, [{
            "draft_id": "existing-1",
            "config_file": str(configs_dir / "entity-a-raw.yaml"),
            "title": "Entity A - Raw",
            "zenodo_url": "https://sandbox.zenodo.org/api",
            "access_token": "tok",
            "user_agent": "ua",
            "status": "uploaded",
            "doi": "",
            "record_url": "https://sandbox.zenodo.org/uploads/existing-1",
        }])

        mock_upload.return_value = {
            "id": "new-draft",
            "pids": {},
            "links": {"self_html": "https://sandbox.zenodo.org/records/new-draft"},
        }

        upload_all(configs_dir, publish=False)

        with open(drafts_path) as f:
            drafts = json.load(f)
        assert len(drafts) == 3
        assert mock_upload.call_count == 2
        stems = {Path(d["config_file"]).stem for d in drafts if d["status"] == "uploaded"}
        assert "entity-a-raw" in stems
        assert "entity-b-raw" in stems
        assert "entity-c-raw" in stems

    @patch("changes_metadata_manager.zenodo_upload.time.sleep")
    @patch("changes_metadata_manager.zenodo_upload.piccione_upload")
    def test_failure_continues_and_records_error(self, mock_upload, mock_sleep, tmp_path):
        configs_dir = self._setup_configs(tmp_path)
        call_count = 0

        def side_effect(config_file, publish=False):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Zenodo is down")
            return {
                "id": f"draft-{call_count}",
                "pids": {},
                "links": {"self_html": f"https://sandbox.zenodo.org/records/draft-{call_count}"},
            }

        mock_upload.side_effect = side_effect
        upload_all(configs_dir, publish=False)

        drafts_path = tmp_path / "drafts.json"
        with open(drafts_path) as f:
            drafts = json.load(f)
        assert len(drafts) == 3
        statuses = [d["status"] for d in drafts]
        assert statuses.count("uploaded") == 2
        assert statuses.count("failed") == 1
        failed = [d for d in drafts if d["status"] == "failed"][0]
        assert failed["error"] == "Zenodo is down"

    @patch("changes_metadata_manager.zenodo_upload.time.sleep")
    @patch("changes_metadata_manager.zenodo_upload.piccione_upload")
    def test_failed_entry_retried_on_rerun(self, mock_upload, mock_sleep, tmp_path):
        configs_dir = self._setup_configs(tmp_path)
        drafts_path = tmp_path / "drafts.json"
        _atomic_write_json(drafts_path, [
            {
                "draft_id": "existing-1",
                "config_file": str(configs_dir / "entity-a-raw.yaml"),
                "title": "Entity A - Raw",
                "zenodo_url": "https://sandbox.zenodo.org/api",
                "access_token": "tok",
                "user_agent": "ua",
                "status": "uploaded",
                "doi": "",
                "record_url": "",
            },
            {
                "draft_id": "",
                "config_file": str(configs_dir / "entity-b-raw.yaml"),
                "title": "entity-b-raw",
                "zenodo_url": "",
                "access_token": "",
                "user_agent": "",
                "status": "failed",
                "doi": "",
                "record_url": "",
                "error": "previous failure",
            },
            {
                "draft_id": "existing-3",
                "config_file": str(configs_dir / "entity-c-raw.yaml"),
                "title": "Entity C - Raw",
                "zenodo_url": "https://sandbox.zenodo.org/api",
                "access_token": "tok",
                "user_agent": "ua",
                "status": "uploaded",
                "doi": "",
                "record_url": "",
            },
        ])

        mock_upload.return_value = {
            "id": "retried-draft",
            "pids": {},
            "links": {"self_html": "https://sandbox.zenodo.org/records/retried-draft"},
        }

        upload_all(configs_dir, publish=False)

        assert mock_upload.call_count == 1
        with open(drafts_path) as f:
            drafts = json.load(f)
        assert len(drafts) == 3
        assert all(d["status"] == "uploaded" for d in drafts)
        retried = [d for d in drafts if Path(d["config_file"]).stem == "entity-b-raw"][0]
        assert retried["draft_id"] == "retried-draft"
        assert "error" not in retried

    @patch("changes_metadata_manager.zenodo_upload.time.sleep")
    @patch("changes_metadata_manager.zenodo_upload.piccione_upload")
    def test_drafts_json_written_after_each_upload(self, mock_upload, mock_sleep, tmp_path):
        configs_dir = self._setup_configs(tmp_path)
        drafts_path = tmp_path / "drafts.json"
        snapshots: list[int] = []

        def counting_upload(config_file, publish=False):
            return {
                "id": f"draft-{len(snapshots) + 1}",
                "pids": {},
                "links": {"self_html": f"https://sandbox.zenodo.org/records/draft-{len(snapshots) + 1}"},
            }

        mock_upload.side_effect = counting_upload

        def tracking_write(path, data):
            snapshots.append(len(data))
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            import os
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)

        with patch("changes_metadata_manager.zenodo_upload._atomic_write_json", side_effect=tracking_write):
            upload_all(configs_dir, publish=False)

        assert snapshots == [1, 2, 3]

    @patch("changes_metadata_manager.zenodo_upload.time.sleep")
    @patch("changes_metadata_manager.zenodo_upload.piccione_upload")
    def test_publish_flag_sets_published_status(self, mock_upload, mock_sleep, tmp_path):
        configs_dir = self._setup_configs(tmp_path)
        mock_upload.return_value = {
            "id": "pub-1",
            "pids": {"doi": {"identifier": "10.5281/zenodo.pub1"}},
            "links": {"self_html": "https://zenodo.org/records/pub-1"},
        }

        upload_all(configs_dir, publish=True)

        drafts_path = tmp_path / "drafts.json"
        with open(drafts_path) as f:
            drafts = json.load(f)
        assert all(d["status"] == "published" for d in drafts)
        assert all(d["doi"] == "10.5281/zenodo.pub1" for d in drafts)


class TestPublishAllDraftsResume:
    def _make_drafts(self, tmp_path, statuses):
        configs_dir = tmp_path / "configs"
        configs_dir.mkdir(exist_ok=True)
        drafts = []
        for i, status in enumerate(statuses):
            config_path = _write_config(configs_dir / f"entity-{i}-raw.yaml", {"title": f"Entity {i}"})
            entry = {
                "draft_id": f"draft-{i}",
                "config_file": str(config_path),
                "title": f"Entity {i}",
                "zenodo_url": "https://sandbox.zenodo.org/api",
                "access_token": "tok",
                "user_agent": "ua",
                "status": status,
                "doi": "10.5281/existing" if status == "published" else "",
                "record_url": f"https://sandbox.zenodo.org/records/draft-{i}" if status == "published" else "",
            }
            if status in ("failed", "publish_failed"):
                entry["error"] = "old error"
            drafts.append(entry)
        drafts_path = tmp_path / "drafts.json"
        _atomic_write_json(drafts_path, drafts)
        return drafts_path

    @patch("changes_metadata_manager.zenodo_upload.time.sleep")
    @patch("changes_metadata_manager.zenodo_upload.piccione_publish_draft")
    def test_publishes_uploaded_drafts(self, mock_publish, mock_sleep, tmp_path):
        drafts_path = self._make_drafts(tmp_path, ["uploaded", "uploaded"])
        mock_publish.return_value = {
            "pids": {"doi": {"identifier": "10.5281/zenodo.pub"}},
            "links": {"self_html": "https://zenodo.org/records/pub"},
        }

        publish_all_drafts(drafts_path)

        with open(drafts_path) as f:
            drafts = json.load(f)
        assert all(d["status"] == "published" for d in drafts)
        assert all(d["doi"] == "10.5281/zenodo.pub" for d in drafts)
        assert mock_publish.call_count == 2

    @patch("changes_metadata_manager.zenodo_upload.time.sleep")
    @patch("changes_metadata_manager.zenodo_upload.piccione_publish_draft")
    def test_skips_already_published(self, mock_publish, mock_sleep, tmp_path):
        drafts_path = self._make_drafts(tmp_path, ["published", "uploaded"])
        mock_publish.return_value = {
            "pids": {"doi": {"identifier": "10.5281/zenodo.new"}},
            "links": {"self_html": "https://zenodo.org/records/new"},
        }

        publish_all_drafts(drafts_path)

        assert mock_publish.call_count == 1
        with open(drafts_path) as f:
            drafts = json.load(f)
        assert drafts[0]["doi"] == "10.5281/existing"
        assert drafts[1]["doi"] == "10.5281/zenodo.new"

    @patch("changes_metadata_manager.zenodo_upload.time.sleep")
    @patch("changes_metadata_manager.zenodo_upload.piccione_publish_draft")
    def test_failure_continues(self, mock_publish, mock_sleep, tmp_path):
        drafts_path = self._make_drafts(tmp_path, ["uploaded", "uploaded"])
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("publish error")
            return {
                "pids": {"doi": {"identifier": "10.5281/zenodo.ok"}},
                "links": {"self_html": "https://zenodo.org/records/ok"},
            }

        mock_publish.side_effect = side_effect
        publish_all_drafts(drafts_path)

        with open(drafts_path) as f:
            drafts = json.load(f)
        assert drafts[0]["status"] == "publish_failed"
        assert drafts[0]["error"] == "publish error"
        assert drafts[1]["status"] == "published"
        assert drafts[1]["doi"] == "10.5281/zenodo.ok"

    @patch("changes_metadata_manager.zenodo_upload.time.sleep")
    @patch("changes_metadata_manager.zenodo_upload.piccione_publish_draft")
    def test_retries_publish_failed(self, mock_publish, mock_sleep, tmp_path):
        drafts_path = self._make_drafts(tmp_path, ["published", "publish_failed"])
        mock_publish.return_value = {
            "pids": {"doi": {"identifier": "10.5281/zenodo.retried"}},
            "links": {"self_html": "https://zenodo.org/records/retried"},
        }

        publish_all_drafts(drafts_path)

        assert mock_publish.call_count == 1
        with open(drafts_path) as f:
            drafts = json.load(f)
        assert drafts[1]["status"] == "published"
        assert drafts[1]["doi"] == "10.5281/zenodo.retried"
        assert "error" not in drafts[1]

    @patch("changes_metadata_manager.zenodo_upload.time.sleep")
    @patch("changes_metadata_manager.zenodo_upload.piccione_publish_draft")
    def test_skips_upload_failed_entries(self, mock_publish, mock_sleep, tmp_path):
        drafts_path = self._make_drafts(tmp_path, ["uploaded", "failed"])
        mock_publish.return_value = {
            "pids": {"doi": {"identifier": "10.5281/zenodo.ok"}},
            "links": {"self_html": "https://zenodo.org/records/ok"},
        }

        publish_all_drafts(drafts_path)

        assert mock_publish.call_count == 1
        with open(drafts_path) as f:
            drafts = json.load(f)
        assert drafts[0]["status"] == "published"
        assert drafts[1]["status"] == "failed"
