import tempfile
import zipfile
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef

from changes_metadata_manager.folder_metadata_builder import load_kg
from changes_metadata_manager.zenodo_upload import (
    BASE_URI,
    P3_HAS_NOTE,
    P70I,
    create_entity_zip,
    extract_entity_title,
    extract_licensed_entity_stages,
    generate_zenodo_config,
    group_folders_by_entity,
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


class TestCreateEntityZip:
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

            zip_path = create_entity_zip("1", folders, root, licensed_stages, output_dir)

            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert "S1-01-Test/raw/meta.jsonld" in names
                assert "S1-01-Test/raw/prov.jsonld" in names
                assert "S1-01-Test/raw/photo.jpg" in names

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

            zip_path = create_entity_zip("1", folders, root, licensed_stages, output_dir)

            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert "S1-01-Test/raw/meta.jsonld" in names
                assert "S1-01-Test/raw/prov.jsonld" in names
                assert "S1-01-Test/raw/photo.jpg" not in names

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

            zip_path = create_entity_zip("98", folders, root, set(), output_dir)

            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert "S6-98a-Test/raw/meta.jsonld" in names
                assert "S6-98b-Test/raw/meta.jsonld" in names


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


class TestGenerateZenodoConfig:
    def test_generates_valid_config(self):
        base_config = {
            "zenodo_url": "https://sandbox.zenodo.org/api",
            "access_token": "test_token",
            "user_agent": "piccione/2.1.0",
            "creators": [{"name": "Test Author"}],
            "keywords": ["test"],
        }
        zip_path = Path("/tmp/1.zip")
        config = generate_zenodo_config("1", zip_path, "Test Title", base_config)

        assert config["zenodo_url"] == "https://sandbox.zenodo.org/api"
        assert config["access_token"] == "test_token"
        assert config["user_agent"] == "piccione/2.1.0"
        assert config["title"] == "Test Title - Aldrovandi collection"
        assert config["upload_type"] == "dataset"
        assert config["creators"] == [{"name": "Test Author"}]
        assert config["keywords"] == ["test"]
        assert config["files"] == [str(zip_path.absolute())]
        assert "entity 1" in config["description"]
        assert "license" not in config
