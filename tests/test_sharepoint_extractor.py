import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from changes_metadata_manager.sharepoint_extractor import (
    extract_all_sale,
    get_folder_contents,
    get_folder_structure,
    process_sala,
    sort_structure,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sharepoint" / "api_responses.json"


@pytest.fixture(scope="module")
def sharepoint_fixture():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def create_mock_client(responses: dict, site_url: str):
    """Create a mock httpx client that returns responses based on URL."""
    def mock_get(url: str):
        # Extract path from URL: site_url/_api/web/GetFolderByServerRelativeUrl('path')/Folders
        match = re.search(r"GetFolderByServerRelativeUrl\('([^']+)'\)/(Folders|Files)", url)
        if not match:
            raise ValueError(f"Unexpected URL format: {url}")

        folder_path = match.group(1)
        endpoint = match.group(2)
        response_key = f"{folder_path}/{endpoint}"

        if response_key not in responses:
            raise KeyError(f"No fixture response for: {response_key}")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = responses[response_key]
        mock_response.raise_for_status = MagicMock()
        return mock_response

    mock_client = MagicMock()
    mock_client.get.side_effect = mock_get
    return mock_client


class TestSortStructure:
    def test_sorts_dict_keys_alphabetically_with_files_last(self):
        input_data = {"_files": ["a.txt"], "zebra": {}, "apple": {}}
        result = sort_structure(input_data)
        assert list(result.keys()) == ["apple", "zebra", "_files"]

    def test_sorts_list_elements(self):
        input_data = ["zebra", "apple", "mango"]
        result = sort_structure(input_data)
        assert result == ["apple", "mango", "zebra"]

    def test_returns_primitive_unchanged(self):
        assert sort_structure("hello") == "hello"
        assert sort_structure(42) == 42
        assert sort_structure(None) is None


class TestGetFolderContents:
    def test_extracts_folders_and_files_from_sharepoint_api(self, sharepoint_fixture):
        site_url = sharepoint_fixture["site_url"]
        responses = sharepoint_fixture["responses"]
        mock_client = create_mock_client(responses, site_url)

        folder_path = f"{sharepoint_fixture['docs_folder']}/Sala1/S1-01-CNR_CartaNautica"
        folders, files = get_folder_contents(mock_client, site_url, folder_path)

        assert len(folders) == 4
        folder_names = [f["Name"] for f in folders]
        assert set(folder_names) == {"dcho", "dchoo", "raw", "rawp"}
        assert files == []


class TestGetFolderStructure:
    def test_extracts_complete_item_structure(self, sharepoint_fixture):
        site_url = sharepoint_fixture["site_url"]
        responses = sharepoint_fixture["responses"]
        mock_client = create_mock_client(responses, site_url)

        item_path = f"{sharepoint_fixture['docs_folder']}/Sala1/S1-01-CNR_CartaNautica"
        result = get_folder_structure(mock_client, site_url, item_path, "Sala1")

        expected = sharepoint_fixture["expected_item_structure"]
        assert result == expected

    def test_filters_system_folders(self, sharepoint_fixture):
        site_url = sharepoint_fixture["site_url"]

        responses_with_system = dict(sharepoint_fixture["responses"])
        test_path = f"{sharepoint_fixture['docs_folder']}/TestFolder"
        responses_with_system[f"{test_path}/Folders"] = {
            "d": {
                "results": [
                    {"Name": "_private", "ServerRelativeUrl": f"{test_path}/_private"},
                    {"Name": "Forms", "ServerRelativeUrl": f"{test_path}/Forms"},
                    {"Name": "valid", "ServerRelativeUrl": f"{test_path}/valid"},
                ]
            }
        }
        responses_with_system[f"{test_path}/Files"] = {"d": {"results": []}}
        responses_with_system[f"{test_path}/valid/Folders"] = {"d": {"results": []}}
        responses_with_system[f"{test_path}/valid/Files"] = {"d": {"results": [{"Name": "test.txt"}]}}

        mock_client = create_mock_client(responses_with_system, site_url)
        result = get_folder_structure(mock_client, site_url, test_path, "Test")

        assert "_private" not in result
        assert "Forms" not in result
        assert "valid" in result
        assert result["valid"]["_files"] == ["test.txt"]

    def test_empty_folder_has_no_files_key(self, sharepoint_fixture):
        site_url = sharepoint_fixture["site_url"]

        responses = dict(sharepoint_fixture["responses"])
        test_path = f"{sharepoint_fixture['docs_folder']}/EmptyFolder"
        responses[f"{test_path}/Folders"] = {"d": {"results": []}}
        responses[f"{test_path}/Files"] = {"d": {"results": []}}

        mock_client = create_mock_client(responses, site_url)
        result = get_folder_structure(mock_client, site_url, test_path, "Test")

        assert "_files" not in result
        assert result == {}


class TestProcessSala:
    def test_extracts_sala_structure(self, sharepoint_fixture, capsys):
        site_url = sharepoint_fixture["site_url"]
        docs_folder = sharepoint_fixture["docs_folder"]
        responses = sharepoint_fixture["responses"]
        mock_client = create_mock_client(responses, site_url)

        sala_name, structure = process_sala(mock_client, "Sala1", site_url, docs_folder)

        assert sala_name == "Sala1"
        assert "S1-01-CNR_CartaNautica" in structure
        assert structure == sharepoint_fixture["expected_sala1_structure"]

        captured = capsys.readouterr()
        assert "[Sala1] Starting..." in captured.out
        assert "[Sala1] Done" in captured.out


class TestExtractAllSale:
    def test_returns_sorted_structure(self, sharepoint_fixture):
        site_url = sharepoint_fixture["site_url"]
        responses = sharepoint_fixture["responses"]
        mock_client = create_mock_client(responses, site_url)

        result = extract_all_sale(mock_client, site_url, ["Sala1"])

        # Verify keys are sorted (dcho before dchoo before raw before rawp)
        item_keys = list(result["Sala1"]["S1-01-CNR_CartaNautica"].keys())
        assert item_keys == sorted(item_keys, key=lambda k: (k == "_files", k))
