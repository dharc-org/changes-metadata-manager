import tempfile
import zipfile
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef

from changes_metadata_manager.folder_metadata_builder import load_kg
from changes_metadata_manager.zenodo_upload import (
    BASE_URI,
    CC0_DISCLAIMER,
    E21_PERSON,
    P14_CARRIED_OUT_BY,
    P190_HAS_SYMBOLIC_CONTENT,
    P1_IS_IDENTIFIED_BY,
    P3_HAS_NOTE,
    P70I,
    P74_HAS_RESIDENCE,
    RDF_TYPE,
    build_creators_for_entity_stage,
    build_enhanced_description,
    build_entity_uri,
    build_metadata_creators,
    create_stage_zip,
    extract_authors_for_entity_stage,
    extract_entity_title,
    extract_keeper_info,
    extract_license_for_entity_stage,
    extract_licensed_entity_stages,
    extract_metadata_authors,
    generate_zenodo_config,
    group_folders_by_entity,
    load_creators_lookup,
    merge_creators,
    slugify,
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


class TestCreateStageZip:
    def test_includes_all_files_for_licensed_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            stage_dir = root / "Sala1" / "S1-01-Test" / "raw"
            stage_dir.mkdir(parents=True)
            (stage_dir / "meta.ttl").write_text("{}")
            (stage_dir / "prov.trig").write_text("{}")
            (stage_dir / "photo.jpg").write_text("image")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [("Sala1", "S1-01-Test", {"raw": {}})]
            licensed_stages = {("1", "raw")}

            zip_path = create_stage_zip("1", "raw", folders, root, licensed_stages, output_dir, "Test Object")

            assert zip_path is not None
            assert zip_path.name == "sala1-test-object-raw.zip"
            with zipfile.ZipFile(zip_path) as zf:
                names = sorted(zf.namelist())
                assert names == ["S1-01-Test/raw/meta.ttl", "S1-01-Test/raw/photo.jpg", "S1-01-Test/raw/prov.trig"]

    def test_includes_only_metadata_for_unlicensed_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            stage_dir = root / "Sala1" / "S1-01-Test" / "raw"
            stage_dir.mkdir(parents=True)
            (stage_dir / "meta.ttl").write_text("{}")
            (stage_dir / "prov.trig").write_text("{}")
            (stage_dir / "photo.jpg").write_text("image")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [("Sala1", "S1-01-Test", {"raw": {}})]
            licensed_stages = set()

            zip_path = create_stage_zip("1", "raw", folders, root, licensed_stages, output_dir, "Test Object")

            assert zip_path is not None
            with zipfile.ZipFile(zip_path) as zf:
                names = sorted(zf.namelist())
                assert names == ["S1-01-Test/raw/meta.ttl", "S1-01-Test/raw/prov.trig"]

    def test_multiple_folders_in_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"

            for variant in ["a", "b"]:
                stage_dir = root / "Sala6" / f"S6-98{variant}-Test" / "raw"
                stage_dir.mkdir(parents=True)
                (stage_dir / "meta.ttl").write_text("{}")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [
                ("Sala6", "S6-98a-Test", {"raw": {}}),
                ("Sala6", "S6-98b-Test", {"raw": {}}),
            ]

            zip_path = create_stage_zip("98", "raw", folders, root, set(), output_dir, "Test Masks")

            assert zip_path is not None
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert names == ["S6-98a-Test/raw/meta.ttl", "S6-98b-Test/raw/meta.ttl"]

    def test_returns_none_for_missing_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            stage_dir = root / "Sala1" / "S1-01-Test" / "raw"
            stage_dir.mkdir(parents=True)
            (stage_dir / "meta.ttl").write_text("{}")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [("Sala1", "S1-01-Test", {"raw": {}})]

            result = create_stage_zip("1", "dcho", folders, root, set(), output_dir, "Test Object")

            assert result is None
            assert not (output_dir / "sala1-test-object-dcho.zip").exists()


class TestExtractEntityTitle:
    def test_extracts_title_from_kg(self, real_kg):
        title = extract_entity_title(real_kg, "1")
        assert title == "Carta nautica"

    def test_returns_default_for_missing(self):
        g = Graph()
        title = extract_entity_title(g, "nonexistent")
        assert title == "Entity nonexistent"

    def test_takes_first_line(self):
        g = Graph()
        item_uri = URIRef(f"{BASE_URI}/itm/42/ob00/1")
        g.add((item_uri, P3_HAS_NOTE, Literal("First line\nSecond line")))
        title = extract_entity_title(g, "42")
        assert title == "First line"


class TestExtractAuthorsForEntityStage:
    def test_extracts_author_from_kg(self, real_kg):
        authors = extract_authors_for_entity_stage(real_kg, "1", "raw")
        assert authors == {"Federica Bonifazi"}

    def test_accumulates_authors_across_steps(self, real_kg):
        authors = extract_authors_for_entity_stage(real_kg, "1", "dchoo")
        assert "Federica Bonifazi" in authors
        assert len(authors) > 1

    def test_returns_empty_for_missing_entity(self, real_kg):
        authors = extract_authors_for_entity_stage(real_kg, "nonexistent", "raw")
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
        authors = extract_authors_for_entity_stage(g, "42", "raw")
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
        authors = extract_metadata_authors(g, "42")
        assert authors == {"Metadata Author"}

    def test_returns_empty_for_missing_entity(self):
        g = Graph()
        authors = extract_metadata_authors(g, "nonexistent")
        assert authors == set()

    def test_extracts_from_real_kg(self, real_kg):
        authors = extract_metadata_authors(real_kg, "1")
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
    def test_builds_creators_with_datacollector_role(self, real_kg):
        lookup = {
            "Federica Bonifazi": {
                "family_name": "Bonifazi",
                "given_name": "Federica",
                "affiliation": "CNR-ISPC",
                "orcid": "0009-0000-8466-5541",
            }
        }
        creators = build_creators_for_entity_stage(real_kg, "1", "raw", lookup)
        assert creators == [
            {
                "person_or_org": {
                    "type": "personal",
                    "family_name": "Bonifazi",
                    "given_name": "Federica",
                    "identifiers": [{"scheme": "orcid", "identifier": "0009-0000-8466-5541"}],
                },
                "role": {"id": "datacollector"},
                "affiliations": [{"name": "CNR-ISPC"}],
            }
        ]

    def test_ignores_authors_not_in_lookup(self, real_kg):
        lookup = {}
        creators = build_creators_for_entity_stage(real_kg, "1", "raw", lookup)
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
        creators = build_creators_for_entity_stage(g, "42", "raw", lookup)
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
        creators = build_metadata_creators(g, "42", lookup)
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
                "role": {"id": "datacollector"},
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
        assert merged[0]["role"] == {"id": "datacollector"}
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
                "role": {"id": "datacollector"},
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
        assert merged[0]["role"] == {"id": "datacollector"}

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
        result = build_entity_uri("27")
        assert result == "https://w3id.org/changes/4/aldrovandi/itm/27/ob00/1"

    def test_builds_uri_for_string_id(self):
        result = build_entity_uri("ptb")
        assert result == "https://w3id.org/changes/4/aldrovandi/itm/ptb/ob00/1"


SAMPLE_CREATOR = {
    "person_or_org": {
        "type": "personal",
        "family_name": "Author",
        "given_name": "Test",
        "identifiers": [{"scheme": "orcid", "identifier": "0000-0001-2345-6789"}],
    },
    "role": {"id": "datacollector"},
    "affiliations": [{"name": "Test Uni"}],
}

SAMPLE_BASE_CONFIG = {
    "zenodo_url": "https://sandbox.zenodo.org/api",
    "access_token": "test_token",
    "user_agent": "piccione/2.1.0",
    "keywords": ["test"],
    "notes": "Test notes content",
    "method": "Test method content",
    "locations": [
        {
            "lat": 44.497,
            "lon": 11.353,
            "place": "Bologna, Italy",
            "description": "Palazzo Poggi Museum",
        },
    ],
}


class TestGenerateZenodoConfig:
    def test_generates_valid_config(self, freezer):
        freezer.move_to("2024-06-15")
        zip_path = Path("/tmp/1-raw.zip")
        config = generate_zenodo_config("1", "raw", zip_path, "Test Title", SAMPLE_BASE_CONFIG, [SAMPLE_CREATOR])

        assert config == {
            "zenodo_url": "https://sandbox.zenodo.org/api",
            "access_token": "test_token",
            "user_agent": "piccione/2.1.0",
            "title": "Test Title - Raw sensor data - Aldrovandi Digital Twin",
            "description": 'Raw sensor data of "Test Title" from the Aldrovandi Digital Twin.\nThis stage contains the original acquisition output (photos and/or scans) without processing.\nIncludes metadata (meta.ttl) and provenance (prov.trig) files following the <a href="https://w3id.org/dharc/ontology/chad-ap">CHAD-AP</a> ontology.\n',
            "resource_type": {"id": "dataset"},
            "publisher": "Zenodo",
            "access": {"record": "public", "files": "public"},
            "creators": [SAMPLE_CREATOR],
            "keywords": ["test"],
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
                {"description": "Test notes content", "type": {"id": "notes"}},
                {"description": "Test method content", "type": {"id": "methods"}},
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
        config = generate_zenodo_config("27", "raw", zip_path, "Test Title", SAMPLE_BASE_CONFIG, [SAMPLE_CREATOR], entity_uri=entity_uri)

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
        config = generate_zenodo_config("27", "raw", zip_path, "Test Title", base_config, [SAMPLE_CREATOR])

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
        config = generate_zenodo_config("1", "raw", zip_path, "Test Title", SAMPLE_BASE_CONFIG, [SAMPLE_CREATOR])

        assert config["additional_descriptions"] == [
            {"description": "Test notes content", "type": {"id": "notes"}},
            {"description": "Test method content", "type": {"id": "methods"}},
        ]

    def test_cc0_disclaimer_in_additional_descriptions(self, freezer):
        freezer.move_to("2024-06-15")
        zip_path = Path("/tmp/1-raw.zip")
        config = generate_zenodo_config("1", "raw", zip_path, "Test Title", SAMPLE_BASE_CONFIG, [SAMPLE_CREATOR], license="cc0-1.0")

        assert config["additional_descriptions"] == [
            {"description": "Test notes content", "type": {"id": "notes"}},
            {"description": "Test method content", "type": {"id": "methods"}},
            {"description": CC0_DISCLAIMER, "type": {"id": "notes"}},
        ]

    def test_converts_locations_to_geojson(self, freezer):
        freezer.move_to("2024-06-15")
        zip_path = Path("/tmp/1-raw.zip")
        config = generate_zenodo_config("1", "raw", zip_path, "Test Title", SAMPLE_BASE_CONFIG, [SAMPLE_CREATOR])

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
        config = generate_zenodo_config("1", "raw", zip_path, "Test Title", base_config, [SAMPLE_CREATOR])

        assert config["community"] == "project-changes"


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
        keeper_name, keeper_location = extract_keeper_info(real_kg, "1")
        assert keeper_name == "Biblioteca Universitaria di Bologna"
        assert keeper_location == "Bologna"

    def test_extracts_non_bologna_keeper(self, real_kg):
        keeper_name, keeper_location = extract_keeper_info(real_kg, "21")
        assert keeper_name == "Accademia Carrara"
        assert keeper_location == "Bergamo"

    def test_returns_none_for_missing_entity(self, real_kg):
        keeper_name, keeper_location = extract_keeper_info(real_kg, "nonexistent")
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
        keeper_name, keeper_location = extract_keeper_info(g, "42")
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
        keeper_name, keeper_location = extract_keeper_info(g, "42")
        assert keeper_name == "Test Museum"
        assert keeper_location is None


class TestBuildEnhancedDescription:
    def test_raw_stage_description(self):
        result = build_enhanced_description("raw", "Test Object")
        assert result == (
            'Raw sensor data of "Test Object" from the Aldrovandi Digital Twin.\n'
            "This stage contains the original acquisition output (photos and/or scans) without processing.\n"
            'Includes metadata (meta.ttl) and provenance (prov.trig) files following the <a href="https://w3id.org/dharc/ontology/chad-ap">CHAD-AP</a> ontology.\n'
        )

    def test_dcho_stage_description(self):
        result = build_enhanced_description("dcho", "Museum Specimen")
        assert "Digital Cultural Heritage Object" in result
        assert '"Museum Specimen"' in result
        assert "interpolation, gap filling, and geometry corrections" in result

    def test_dchoo_stage_description(self):
        result = build_enhanced_description("dchoo", "Object Title")
        assert "Optimized Digital Cultural Heritage Object" in result
        assert "web-ready version optimized for real-time online interaction" in result

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
