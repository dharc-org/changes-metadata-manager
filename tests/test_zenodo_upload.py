import tempfile
import zipfile
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef

from changes_metadata_manager.folder_metadata_builder import load_kg
from changes_metadata_manager.zenodo_upload import (
    BASE_URI,
    E21_PERSON,
    P14_CARRIED_OUT_BY,
    P190_HAS_SYMBOLIC_CONTENT,
    P1_IS_IDENTIFIED_BY,
    P3_HAS_NOTE,
    P70I,
    RDF_TYPE,
    build_creators_for_entity_stage,
    create_stage_zip,
    extract_authors_for_entity_stage,
    extract_entity_title,
    extract_licensed_entity_stages,
    generate_zenodo_config,
    group_folders_by_entity,
    load_creators_lookup,
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


class TestCreateStageZip:
    def test_includes_all_files_for_licensed_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            stage_dir = root / "Sala1" / "S1-01-Test" / "raw"
            stage_dir.mkdir(parents=True)
            (stage_dir / "meta.jsonld").write_text("{}")
            (stage_dir / "prov.jsonld").write_text("{}")
            (stage_dir / "photo.jpg").write_text("image")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [("Sala1", "S1-01-Test", {"raw": {}})]
            licensed_stages = {("1", "raw")}

            zip_path = create_stage_zip("1", "raw", folders, root, licensed_stages, output_dir)

            assert zip_path.name == "1-raw.zip"
            with zipfile.ZipFile(zip_path) as zf:
                names = sorted(zf.namelist())
                assert names == ["S1-01-Test/raw/meta.jsonld", "S1-01-Test/raw/photo.jpg", "S1-01-Test/raw/prov.jsonld"]

    def test_includes_only_metadata_for_unlicensed_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            stage_dir = root / "Sala1" / "S1-01-Test" / "raw"
            stage_dir.mkdir(parents=True)
            (stage_dir / "meta.jsonld").write_text("{}")
            (stage_dir / "prov.jsonld").write_text("{}")
            (stage_dir / "photo.jpg").write_text("image")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [("Sala1", "S1-01-Test", {"raw": {}})]
            licensed_stages = set()

            zip_path = create_stage_zip("1", "raw", folders, root, licensed_stages, output_dir)

            with zipfile.ZipFile(zip_path) as zf:
                names = sorted(zf.namelist())
                assert names == ["S1-01-Test/raw/meta.jsonld", "S1-01-Test/raw/prov.jsonld"]

    def test_multiple_folders_in_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"

            for variant in ["a", "b"]:
                stage_dir = root / "Sala6" / f"S6-98{variant}-Test" / "raw"
                stage_dir.mkdir(parents=True)
                (stage_dir / "meta.jsonld").write_text("{}")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [
                ("Sala6", "S6-98a-Test", {"raw": {}}),
                ("Sala6", "S6-98b-Test", {"raw": {}}),
            ]

            zip_path = create_stage_zip("98", "raw", folders, root, set(), output_dir)

            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert names == ["S6-98a-Test/raw/meta.jsonld", "S6-98b-Test/raw/meta.jsonld"]

    def test_returns_none_for_missing_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            stage_dir = root / "Sala1" / "S1-01-Test" / "raw"
            stage_dir.mkdir(parents=True)
            (stage_dir / "meta.jsonld").write_text("{}")

            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            folders = [("Sala1", "S1-01-Test", {"raw": {}})]

            result = create_stage_zip("1", "dcho", folders, root, set(), output_dir)

            assert result is None
            assert not (output_dir / "1-dcho.zip").exists()


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

    def test_filters_only_persons(self):
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

    def test_ignores_non_person_actors(self):
        g = Graph()
        act_uri = URIRef(f"{BASE_URI}/act/42/00/1")
        actor_uri = URIRef(f"{BASE_URI}/grp/42/1")
        apl_uri = URIRef(f"{BASE_URI}/apl/42/1")
        g.add((act_uri, P14_CARRIED_OUT_BY, actor_uri))
        g.add((actor_uri, P1_IS_IDENTIFIED_BY, apl_uri))
        g.add((apl_uri, P190_HAS_SYMBOLIC_CONTENT, Literal("Test Group")))
        authors = extract_authors_for_entity_stage(g, "42", "raw")
        assert authors == set()


class TestLoadCreatorsLookup:
    def test_loads_creators_as_dict(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("creators:\n  - name_in_rdf: Test Author\n    name: Author, Test\n    affiliation: Test Uni\n    orcid: 0000-0001-2345-6789\n")
            f.flush()
            lookup = load_creators_lookup(Path(f.name))
        assert lookup == {
            "Test Author": {
                "name": "Author, Test",
                "affiliation": "Test Uni",
                "orcid": "0000-0001-2345-6789",
            }
        }


class TestBuildCreatorsForEntityStage:
    def test_builds_creators_list(self, real_kg):
        lookup = {
            "Federica Bonifazi": {
                "name": "Bonifazi, Federica",
                "affiliation": "CNR-ISPC",
                "orcid": "0009-0000-8466-5541",
            }
        }
        creators = build_creators_for_entity_stage(real_kg, "1", "raw", lookup)
        assert creators == [
            {
                "name": "Bonifazi, Federica",
                "affiliation": "CNR-ISPC",
                "orcid": "0009-0000-8466-5541",
            }
        ]

    def test_ignores_authors_not_in_lookup(self, real_kg):
        lookup = {}
        creators = build_creators_for_entity_stage(real_kg, "1", "raw", lookup)
        assert creators == []

    def test_sorts_authors_alphabetically(self):
        g = Graph()
        for name in ["Zeta, Author", "Alpha, Author"]:
            act_uri = URIRef(f"{BASE_URI}/act/42/00/1")
            actor_uri = URIRef(f"{BASE_URI}/per/{name}/1")
            apl_uri = URIRef(f"{BASE_URI}/apl/{name}/1")
            g.add((act_uri, P14_CARRIED_OUT_BY, actor_uri))
            g.add((actor_uri, RDF_TYPE, E21_PERSON))
            g.add((actor_uri, P1_IS_IDENTIFIED_BY, apl_uri))
            g.add((apl_uri, P190_HAS_SYMBOLIC_CONTENT, Literal(name)))
        lookup = {
            "Alpha, Author": {"name": "Alpha, Author"},
            "Zeta, Author": {"name": "Zeta, Author"},
        }
        creators = build_creators_for_entity_stage(g, "42", "raw", lookup)
        assert [c["name"] for c in creators] == ["Alpha, Author", "Zeta, Author"]


class TestGenerateZenodoConfig:
    def test_generates_valid_config(self):
        base_config = {
            "zenodo_url": "https://sandbox.zenodo.org/api",
            "access_token": "test_token",
            "user_agent": "piccione/2.1.0",
            "upload_type": "dataset",
            "keywords": ["test"],
        }
        creators = [{"name": "Test Author"}]
        zip_path = Path("/tmp/1-raw.zip")
        config = generate_zenodo_config("1", "raw", zip_path, "Test Title", base_config, creators)

        assert config == {
            "zenodo_url": "https://sandbox.zenodo.org/api",
            "access_token": "test_token",
            "user_agent": "piccione/2.1.0",
            "title": "Test Title - RAW - Aldrovandi collection",
            "description": "Digitization data for entity 1 (RAW stage) from the Aldrovandi collection.\n\nThis dataset contains metadata (meta.jsonld) and provenance (prov.jsonld) files for the RAW processing stage.",
            "upload_type": "dataset",
            "creators": [{"name": "Test Author"}],
            "keywords": ["test"],
            "files": [str(zip_path.absolute())],
        }
