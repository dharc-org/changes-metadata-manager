import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.progress import Progress

from changes_metadata_manager.sharepoint_sync import (
    collect_files_from_structure,
    download_all_files,
    download_file,
    extract_structure,
    get_folder_contents,
    get_folder_structure,
    get_site_relative_url,
    load_config,
    process_folder,
    sort_structure,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sharepoint" / "api_responses.json"


@pytest.fixture(scope="module")
def sharepoint_fixture():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def create_mock_client(responses: dict):
    def mock_get(url: str):
        match = re.search(
            r"GetFolderByServerRelativeUrl\('([^']+)'\)/(Folders|Files)", url
        )
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


class TestLoadConfig:
    def test_loads_yaml_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
site_url: https://example.sharepoint.com/sites/Test
fedauth: abc123
rtfa: xyz789
folders:
  - /Shared Documents/Folder1
  - /Shared Documents/Folder2
"""
        )

        config = load_config(config_file)

        assert config["site_url"] == "https://example.sharepoint.com/sites/Test"
        assert config["fedauth"] == "abc123"
        assert config["rtfa"] == "xyz789"
        assert config["folders"] == [
            "/Shared Documents/Folder1",
            "/Shared Documents/Folder2",
        ]


class TestGetSiteRelativeUrl:
    def test_extracts_site_relative_url(self):
        site_url = "https://example.sharepoint.com/sites/MySite"
        result = get_site_relative_url(site_url)
        assert result == "/sites/MySite"

    def test_handles_nested_site_path(self):
        site_url = "https://liveunibo.sharepoint.com/sites/PE5-Spoke4-CaseStudyAldrovandi"
        result = get_site_relative_url(site_url)
        assert result == "/sites/PE5-Spoke4-CaseStudyAldrovandi"

    def test_handles_trailing_slash(self):
        site_url = "https://example.sharepoint.com/sites/MySite/"
        result = get_site_relative_url(site_url)
        assert result == "/sites/MySite"


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
        mock_client = create_mock_client(responses)

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
        mock_client = create_mock_client(responses)

        item_path = f"{sharepoint_fixture['docs_folder']}/Sala1/S1-01-CNR_CartaNautica"
        result = get_folder_structure(mock_client, site_url, item_path)

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
        responses_with_system[f"{test_path}/valid/Files"] = {
            "d": {"results": [{"Name": "test.txt"}]}
        }

        mock_client = create_mock_client(responses_with_system)
        result = get_folder_structure(mock_client, site_url, test_path)

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

        mock_client = create_mock_client(responses)
        result = get_folder_structure(mock_client, site_url, test_path)

        assert "_files" not in result
        assert result == {}


class TestProcessFolder:
    def test_extracts_folder_structure(self, sharepoint_fixture):
        site_url = sharepoint_fixture["site_url"]
        docs_folder = sharepoint_fixture["docs_folder"]
        responses = sharepoint_fixture["responses"]
        mock_client = create_mock_client(responses)

        mock_progress = MagicMock()
        mock_task_id = 0

        folder_path = f"{docs_folder}/Sala1"
        folder_name, returned_path, structure = process_folder(
            mock_client, folder_path, site_url, mock_progress, mock_task_id
        )

        assert folder_name == "Sala1"
        assert returned_path == folder_path
        assert "S1-01-CNR_CartaNautica" in structure
        assert structure == sharepoint_fixture["expected_sala1_structure"]

        mock_progress.update.assert_called()
        mock_progress.advance.assert_called_once_with(mock_task_id)


class TestExtractStructure:
    def test_returns_sorted_structure(self, sharepoint_fixture):
        site_url = sharepoint_fixture["site_url"]
        responses = sharepoint_fixture["responses"]
        mock_client = create_mock_client(responses)

        mock_progress = MagicMock()
        mock_progress.add_task.return_value = 0

        relative_folder = "/Shared Documents/Sala1"
        result, folder_paths = extract_structure(mock_client, site_url, [relative_folder], mock_progress)

        assert "Sala1" in result
        expected_full_path = f"{sharepoint_fixture['site_relative_url']}{relative_folder}"
        assert folder_paths["Sala1"] == expected_full_path
        item_keys = list(result["Sala1"]["S1-01-CNR_CartaNautica"].keys())
        assert item_keys == sorted(item_keys, key=lambda k: (k == "_files", k))

    def test_handles_folder_without_leading_slash(self, sharepoint_fixture):
        site_url = sharepoint_fixture["site_url"]
        responses = sharepoint_fixture["responses"]
        mock_client = create_mock_client(responses)

        mock_progress = MagicMock()
        mock_progress.add_task.return_value = 0

        relative_folder = "Shared Documents/Sala1"
        result, folder_paths = extract_structure(mock_client, site_url, [relative_folder], mock_progress)

        assert "Sala1" in result
        expected_full_path = f"{sharepoint_fixture['site_relative_url']}/{relative_folder}"
        assert folder_paths["Sala1"] == expected_full_path


class TestCollectFilesFromStructure:
    def test_extracts_files_with_correct_paths(self):
        structure = {
            "Sala1": {
                "S1-01-Item": {
                    "raw": {"_files": ["photo1.jpg", "photo2.jpg"]},
                    "dcho": {"_files": ["model.obj"]},
                }
            }
        }
        folder_paths = {"Sala1": "/sites/test/Shared Documents/Sala1"}

        result = collect_files_from_structure(structure, folder_paths)

        expected = [
            (
                "/sites/test/Shared Documents/Sala1/S1-01-Item/raw/photo1.jpg",
                "Sala1/S1-01-Item/raw/photo1.jpg",
            ),
            (
                "/sites/test/Shared Documents/Sala1/S1-01-Item/raw/photo2.jpg",
                "Sala1/S1-01-Item/raw/photo2.jpg",
            ),
            (
                "/sites/test/Shared Documents/Sala1/S1-01-Item/dcho/model.obj",
                "Sala1/S1-01-Item/dcho/model.obj",
            ),
        ]
        assert result == expected

    def test_handles_nested_folders(self):
        structure = {
            "Sala1": {
                "S1-01-Item": {
                    "rawp": {
                        "materials": {"_files": ["texture.png"]},
                        "_files": ["model.obj"],
                    }
                }
            }
        }
        folder_paths = {"Sala1": "/sites/test/Shared Documents/Sala1"}

        result = collect_files_from_structure(structure, folder_paths)

        assert len(result) == 2
        server_paths = [r[0] for r in result]
        assert any("materials/texture.png" in p for p in server_paths)
        assert any("rawp/model.obj" in p for p in server_paths)

    def test_empty_structure_returns_empty_list(self):
        result = collect_files_from_structure({}, {})
        assert result == []

    def test_folder_without_files_key(self):
        structure = {"Sala1": {"S1-01-Item": {"raw": {}}}}
        folder_paths = {"Sala1": "/docs/Sala1"}
        result = collect_files_from_structure(structure, folder_paths)
        assert result == []


class TestDownloadFile:
    def test_streams_content_to_file(self, tmp_path):
        mock_response = MagicMock()
        mock_response.iter_bytes.return_value = [b"chunk1", b"chunk2", b"chunk3"]
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        mock_client = MagicMock()

        with patch(
            "changes_metadata_manager.sharepoint_sync.stream_with_retry"
        ) as mock_stream:
            mock_stream.return_value = mock_response

            local_path = tmp_path / "subdir" / "file.txt"
            size = download_file(
                mock_client,
                "https://test.sharepoint.com",
                "/path/file.txt",
                local_path,
            )

        assert local_path.exists()
        assert local_path.read_bytes() == b"chunk1chunk2chunk3"
        assert size == 18

    def test_creates_parent_directories(self, tmp_path):
        mock_response = MagicMock()
        mock_response.iter_bytes.return_value = [b"data"]
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "changes_metadata_manager.sharepoint_sync.stream_with_retry"
        ) as mock_stream:
            mock_stream.return_value = mock_response

            local_path = tmp_path / "deep" / "nested" / "dir" / "file.bin"
            download_file(MagicMock(), "https://test", "/path", local_path)

        assert local_path.parent.exists()


@pytest.fixture
def mock_progress():
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    mock.add_task.return_value = 0
    return mock


class TestDownloadAllFiles:
    def test_skips_existing_files(self, tmp_path, mock_progress):
        structure = {"Sala1": {"item": {"raw": {"_files": ["existing.jpg"]}}}}
        folder_paths = {"Sala1": "/docs/Sala1"}

        existing = tmp_path / "Sala1" / "item" / "raw" / "existing.jpg"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"already here")

        mock_client = MagicMock()
        with patch("changes_metadata_manager.sharepoint_sync.Progress", return_value=mock_progress):
            with patch("changes_metadata_manager.sharepoint_sync.console"):
                download_all_files(
                    mock_client, "https://test", structure, tmp_path, folder_paths
                )

        assert existing.read_bytes() == b"already here"

    def test_continues_on_error(self, tmp_path, mock_progress):
        structure = {
            "Sala1": {"item": {"raw": {"_files": ["fail.jpg", "success.jpg"]}}}
        }
        folder_paths = {"Sala1": "/docs/Sala1"}

        mock_response = MagicMock()
        mock_response.iter_bytes.return_value = [b"data"]
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Network error")
            return mock_response

        with patch(
            "changes_metadata_manager.sharepoint_sync.stream_with_retry"
        ) as mock_stream:
            mock_stream.side_effect = side_effect
            with patch("changes_metadata_manager.sharepoint_sync.Progress", return_value=mock_progress):
                with patch("changes_metadata_manager.sharepoint_sync.console"):
                    download_all_files(
                        MagicMock(), "https://test", structure, tmp_path, folder_paths
                    )

        success_file = tmp_path / "Sala1" / "item" / "raw" / "success.jpg"
        assert success_file.exists()

    def test_downloads_files(self, tmp_path, mock_progress):
        structure = {"Sala1": {"item": {"raw": {"_files": ["photo.jpg"]}}}}
        folder_paths = {"Sala1": "/docs/Sala1"}

        mock_response = MagicMock()
        mock_response.iter_bytes.return_value = [b"x" * 1024]
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "changes_metadata_manager.sharepoint_sync.stream_with_retry"
        ) as mock_stream:
            mock_stream.return_value = mock_response
            with patch("changes_metadata_manager.sharepoint_sync.Progress", return_value=mock_progress):
                with patch("changes_metadata_manager.sharepoint_sync.console"):
                    download_all_files(
                        MagicMock(), "https://test", structure, tmp_path, folder_paths
                    )

        downloaded_file = tmp_path / "Sala1" / "item" / "raw" / "photo.jpg"
        assert downloaded_file.exists()
        assert downloaded_file.stat().st_size == 1024
