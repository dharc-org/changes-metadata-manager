import json
import shutil
import tempfile

import pytest
from pathlib import Path
from rdflib import Graph

from aldrovandi_provenance.folder_metadata_builder import (
    STAGE_STEPS,
    extract_metadata_for_stage,
    extract_nr_from_folder_name,
    load_kg,
    load_sharepoint_structure,
    process_all_folders,
)


DATA_DIR = Path(__file__).parent.parent / "data"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "folder_metadata"
REAL_KG_PATH = DATA_DIR / "kg.ttl"
REAL_SHAREPOINT_PATH = DATA_DIR / "sharepoint_structure.json"

TEST_ITEMS = [
    ("Sala1", "S1-01-CNR_CartaNautica", 1),
    ("Sala2", "S2-24-CNR_MappaOrtoBotanicoPADOVA", 24),
    ("Sala5", "S5-57-FICLIT_VolumePolpo", 57),
]


def load_fixture(relative_path: str) -> Graph:
    g = Graph()
    g.parse(FIXTURE_DIR / relative_path, format="turtle")
    return g


def assert_graphs_equal(actual: Graph, expected: Graph):
    actual_triples = set(actual)
    expected_triples = set(expected)

    missing = expected_triples - actual_triples
    extra = actual_triples - expected_triples

    if missing:
        missing_str = "\n".join(f"  {s} {p} {o}" for s, p, o in sorted(missing, key=str))
        raise AssertionError(f"Missing {len(missing)} triples:\n{missing_str}")

    if extra:
        extra_str = "\n".join(f"  {s} {p} {o}" for s, p, o in sorted(extra, key=str))
        raise AssertionError(f"Extra {len(extra)} triples:\n{extra_str}")


@pytest.fixture(scope="module")
def real_kg():
    return load_kg(REAL_KG_PATH)


@pytest.fixture
def subset_structure():
    full_structure = load_sharepoint_structure(REAL_SHAREPOINT_PATH)
    subset = {"structure": {}}
    for sala, folder, _ in TEST_ITEMS:
        if sala not in subset["structure"]:
            subset["structure"][sala] = {}
        subset["structure"][sala][folder] = full_structure["structure"][sala][folder]

    tmpdir = tempfile.mkdtemp()
    tmpdir_path = Path(tmpdir)
    structure_path = tmpdir_path / "structure_subset.json"
    with open(structure_path, "w") as f:
        json.dump(subset, f)

    yield tmpdir_path, structure_path

    shutil.rmtree(tmpdir)


class TestExtractMetadataForStageExact:
    @pytest.mark.parametrize("nr,stage", [
        (1, "raw"), (1, "rawp"), (1, "dcho"), (1, "dchoo"),
        (24, "raw"), (24, "rawp"), (24, "dcho"), (24, "dchoo"),
        (57, "raw"), (57, "rawp"), (57, "dcho"), (57, "dchoo"),
    ])
    def test_stage_output_matches_fixture(self, real_kg, nr, stage):
        result = extract_metadata_for_stage(real_kg, nr, stage)
        expected = load_fixture(f"nr_{nr}/{stage}.ttl")
        assert_graphs_equal(result, expected)


class TestExtractNrFromFolderName:
    @pytest.mark.parametrize("folder_name,expected", [
        ("S1-5-nome_oggetto", 5),
        ("S2-42-altro_nome", 42),
        ("S6-123-oggetto_complesso", 123),
        ("S1-7-nome con spazi", 7),
    ])
    def test_valid_folder_names(self, folder_name, expected):
        assert extract_nr_from_folder_name(folder_name) == expected

    @pytest.mark.parametrize("folder_name", [
        "1-5-nome",
        "Sala1-5-nome",
        "S1_5_nome",
    ])
    def test_invalid_folder_names(self, folder_name):
        with pytest.raises(ValueError, match="Cannot extract NR"):
            extract_nr_from_folder_name(folder_name)


class TestProcessAllFoldersExact:
    def test_creates_correct_structure(self, subset_structure):
        tmpdir, structure_path = subset_structure
        output_dir = tmpdir / "output"
        process_all_folders(
            output_dir=output_dir,
            structure_path=structure_path,
            kg_path=REAL_KG_PATH,
        )

        for sala, folder, _ in TEST_ITEMS:
            sala_dir = output_dir / sala / folder
            assert sala_dir.exists(), f"Folder directory not created for {folder}"

            stage_dirs = [d for d in sala_dir.iterdir() if d.is_dir()]
            assert len(stage_dirs) == 4, f"Expected 4 stages for {folder}, got {len(stage_dirs)}"

            for stage_dir in stage_dirs:
                meta_file = stage_dir / "meta.ttl"
                prov_file = stage_dir / "prov.nq"

                assert meta_file.exists(), f"meta.ttl not created for {folder}/{stage_dir.name}"
                assert prov_file.exists(), f"prov.nq not created for {folder}/{stage_dir.name}"