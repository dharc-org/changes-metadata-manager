# SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelomas@gmail.com>
#
# SPDX-License-Identifier: ISC

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from changes_metadata_manager.patch.license_metadata import (
    MAX_RETRIES,
    _create_edit_draft,
    _current_content_license,
    _extract_entity_id_from_config,
    _extract_stage_from_config_path,
    _fetch_record_metadata,
    _has_cc0_disclaimer,
    _rebuild_additional_descriptions,
    _request_with_retry,
    patch_drafts,
)


class TestExtractStageFromConfigPath:
    def test_extracts_raw(self):
        assert _extract_stage_from_config_path("configs/sala1-obj-42-raw.yaml") == "raw"

    def test_extracts_dchoo(self):
        assert _extract_stage_from_config_path("configs/sala1-obj-42-dchoo.yaml") == "dchoo"

    def test_raises_on_invalid(self):
        with pytest.raises(AssertionError):
            _extract_stage_from_config_path("configs/sala1-obj-42.yaml")


class TestExtractEntityIdFromConfig:
    def test_extracts_entity(self):
        config = {"identifiers": [
            {"identifier": "https://w3id.org/changes/4/aldrovandi/itm/42/ob1/1"}
        ]}
        assert _extract_entity_id_from_config(config) == "42"

    def test_raises_when_no_match(self):
        config = {"identifiers": [{"identifier": "https://example.com/other"}]}
        with pytest.raises(ValueError):
            _extract_entity_id_from_config(config)


class TestCurrentContentLicense:
    def test_detects_cc0(self):
        metadata = {"rights": [{"title": {"en": "CC0 (Content license)"}, "link": "https://creativecommons.org/publicdomain/zero/1.0/"}]}
        assert _current_content_license(metadata) == "cc0-1.0"

    def test_detects_cc_by_nc(self):
        metadata = {"rights": [{"title": {"en": "CC BY-NC 4.0 (Content license)"}, "link": "https://creativecommons.org/licenses/by-nc/4.0/"}]}
        assert _current_content_license(metadata) == "cc-by-nc-4.0"

    def test_returns_none_without_content_license(self):
        metadata = {"rights": [{"title": {"en": "ISC (Code license)"}, "link": "https://example.com"}]}
        assert _current_content_license(metadata) is None

    def test_returns_none_on_empty(self):
        assert _current_content_license({}) is None


class TestHasCc0Disclaimer:
    def test_true_with_disclaimer(self):
        metadata = {"additional_descriptions": [{"description": "Ai sensi del D. Lgs. 42/2004..."}]}
        assert _has_cc0_disclaimer(metadata) is True

    def test_false_without(self):
        assert _has_cc0_disclaimer({"additional_descriptions": []}) is False


class TestRebuildAdditionalDescriptions:
    def test_adds_disclaimer_for_cc0(self):
        result = _rebuild_additional_descriptions([], "cc0-1.0")
        assert len(result) == 1
        assert "D. Lgs. 42/2004" in result[0]["description"]

    def test_removes_old_disclaimer_when_not_cc0(self):
        current = [{"description": "Ai sensi del D. Lgs. 42/2004..."}]
        result = _rebuild_additional_descriptions(current, "cc-by-nc-4.0")
        assert result == []

    def test_preserves_other_descriptions(self):
        current = [
            {"description": "Some other note"},
            {"description": "Ai sensi del D. Lgs. 42/2004..."},
        ]
        result = _rebuild_additional_descriptions(current, "cc-by-nc-4.0")
        assert result == [{"description": "Some other note"}]


class TestRequestWithRetry:
    @patch("changes_metadata_manager.patch.license_metadata.requests.request")
    def test_returns_immediately_on_success(self, mock_request):
        mock_response = MagicMock(status_code=200)
        mock_request.return_value = mock_response
        result = _request_with_retry("GET", "https://example.com")
        assert result.status_code == 200
        assert mock_request.call_count == 1

    @patch("changes_metadata_manager.patch.license_metadata.time.sleep")
    @patch("changes_metadata_manager.patch.license_metadata.requests.request")
    def test_retries_on_429(self, mock_request, mock_sleep):
        rate_limited = MagicMock(status_code=429)
        success = MagicMock(status_code=200)
        mock_request.side_effect = [rate_limited, rate_limited, success]
        result = _request_with_retry("GET", "https://example.com")
        assert result.status_code == 200
        assert mock_request.call_count == 3

    @patch("changes_metadata_manager.patch.license_metadata.time.sleep")
    @patch("changes_metadata_manager.patch.license_metadata.requests.request")
    def test_returns_429_after_all_retries_exhausted(self, mock_request, mock_sleep):
        rate_limited = MagicMock(status_code=429)
        mock_request.return_value = rate_limited
        result = _request_with_retry("GET", "https://example.com")
        assert result.status_code == 429
        assert mock_request.call_count == MAX_RETRIES


class TestCreateEditDraft:
    @patch("changes_metadata_manager.patch.license_metadata._request_with_retry")
    def test_creates_draft(self, mock_retry):
        mock_retry.return_value = MagicMock(status_code=201)
        _create_edit_draft("https://zenodo.org/api", "123", "token", "agent")
        mock_retry.assert_called_once()
        assert "/records/123/draft" in mock_retry.call_args[0][1]

    @patch("changes_metadata_manager.patch.license_metadata._request_with_retry")
    def test_ignores_403_already_exists(self, mock_retry):
        resp = MagicMock(status_code=403)
        resp.text = "Draft already exists"
        mock_retry.return_value = resp
        _create_edit_draft("https://zenodo.org/api", "123", "token", "agent")

    @patch("changes_metadata_manager.patch.license_metadata._request_with_retry")
    def test_raises_on_other_error(self, mock_retry):
        resp = MagicMock(status_code=500)
        resp.text = "Internal error"
        resp.raise_for_status.side_effect = requests.HTTPError("500")
        mock_retry.return_value = resp
        with pytest.raises(requests.HTTPError):
            _create_edit_draft("https://zenodo.org/api", "123", "token", "agent")


class TestFetchRecordMetadata:
    @patch("changes_metadata_manager.patch.license_metadata._request_with_retry")
    def test_tries_draft_first(self, mock_retry):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"metadata": {"title": "test"}}
        mock_retry.return_value = resp
        result = _fetch_record_metadata("https://zenodo.org/api", "123", "token", "agent")
        assert result == {"title": "test"}
        assert mock_retry.call_count == 1
        assert "/records/123/draft" in mock_retry.call_args[0][1]

    @patch("changes_metadata_manager.patch.license_metadata._request_with_retry")
    def test_falls_back_to_published_on_404(self, mock_retry):
        draft_resp = MagicMock(status_code=404)
        published_resp = MagicMock(status_code=200)
        published_resp.json.return_value = {"metadata": {"title": "published"}}
        mock_retry.side_effect = [draft_resp, published_resp]
        result = _fetch_record_metadata("https://zenodo.org/api", "123", "token", "agent")
        assert result == {"title": "published"}
        assert mock_retry.call_count == 2


class TestPatchDrafts:
    def _make_drafts_json(self, tmp_path, entries):
        path = tmp_path / "drafts.json"
        path.write_text(json.dumps(entries))
        return path

    def _make_config(self, tmp_path, filename, rights=None):
        config = {
            "access": {"record": "public", "files": "public"},
            "rights": rights or [],
            "additional_descriptions": [],
        }
        config_path = tmp_path / filename
        import yaml
        config_path.write_text(yaml.dump(config))
        return str(config_path)

    @patch("changes_metadata_manager.patch.license_metadata.time.sleep")
    @patch("changes_metadata_manager.patch.license_metadata.extract_license_for_entity_stage")
    @patch("changes_metadata_manager.patch.license_metadata._fetch_record_metadata")
    def test_dry_run_logs_changes(self, mock_fetch, mock_extract, mock_sleep, tmp_path):
        mock_fetch.return_value = {
            "identifiers": [{"identifier": "https://w3id.org/changes/4/aldrovandi/itm/42/ob1/1"}],
            "rights": [{"title": {"en": "CC BY-NC 4.0 (Content license)"}, "link": "https://creativecommons.org/licenses/by-nc/4.0/"}],
            "additional_descriptions": [],
        }
        mock_extract.return_value = "cc0-1.0"

        config_file = self._make_config(tmp_path, "entity-42-dcho.yaml")
        drafts_path = self._make_drafts_json(tmp_path, [{
            "draft_id": 123,
            "config_file": f"{tmp_path}/entity-42-dcho.yaml",
            "zenodo_url": "https://zenodo.org/api",
            "access_token": "tok",
            "status": "published",
        }])

        kg_path = tmp_path / "kg.ttl"
        kg_path.write_text("")

        with patch("changes_metadata_manager.patch.license_metadata.load_kg"):
            patch_drafts(drafts_path, kg_path, dry_run=True)

        log = json.loads((tmp_path / "patch_license_log.json").read_text())
        assert len(log) == 1
        assert log[0]["status"] == "dry_run"
        assert log[0]["old_license"] == "cc-by-nc-4.0"
        assert log[0]["new_license"] == "cc0-1.0"

    @patch("changes_metadata_manager.patch.license_metadata.time.sleep")
    @patch("changes_metadata_manager.patch.license_metadata.publish_draft")
    @patch("changes_metadata_manager.patch.license_metadata.update_draft_metadata")
    @patch("changes_metadata_manager.patch.license_metadata.build_inveniordm_payload")
    @patch("changes_metadata_manager.patch.license_metadata._create_edit_draft")
    @patch("changes_metadata_manager.patch.license_metadata.extract_license_for_entity_stage")
    @patch("changes_metadata_manager.patch.license_metadata._fetch_record_metadata")
    def test_published_record_creates_edit_draft_and_publishes(
        self, mock_fetch, mock_extract, mock_create_edit, mock_build, mock_update, mock_publish, mock_sleep, tmp_path
    ):
        mock_fetch.return_value = {
            "identifiers": [{"identifier": "https://w3id.org/changes/4/aldrovandi/itm/42/ob1/1"}],
            "rights": [{"title": {"en": "CC BY-NC 4.0 (Content license)"}, "link": "https://creativecommons.org/licenses/by-nc/4.0/"}],
            "additional_descriptions": [],
        }
        mock_extract.return_value = "cc0-1.0"
        mock_build.return_value = {"metadata": {}}

        config_file = self._make_config(tmp_path, "entity-42-dcho.yaml")
        drafts_path = self._make_drafts_json(tmp_path, [{
            "draft_id": 456,
            "config_file": str(tmp_path / "entity-42-dcho.yaml"),
            "zenodo_url": "https://zenodo.org/api",
            "access_token": "tok",
            "status": "published",
        }])

        kg_path = tmp_path / "kg.ttl"
        kg_path.write_text("")

        with patch("changes_metadata_manager.patch.license_metadata.load_kg"):
            patch_drafts(drafts_path, kg_path, dry_run=False)

        mock_create_edit.assert_called_once_with("https://zenodo.org/api", "456", "tok", "changes-metadata-manager/1.0.0")
        mock_publish.assert_called_once_with("https://zenodo.org/api", "tok", "456", "changes-metadata-manager/1.0.0")

    @patch("changes_metadata_manager.patch.license_metadata.time.sleep")
    @patch("changes_metadata_manager.patch.license_metadata.update_draft_metadata")
    @patch("changes_metadata_manager.patch.license_metadata.build_inveniordm_payload")
    @patch("changes_metadata_manager.patch.license_metadata._create_edit_draft")
    @patch("changes_metadata_manager.patch.license_metadata.extract_license_for_entity_stage")
    @patch("changes_metadata_manager.patch.license_metadata._fetch_record_metadata")
    def test_unpublished_record_skips_edit_draft_and_publish(
        self, mock_fetch, mock_extract, mock_create_edit, mock_build, mock_update, mock_sleep, tmp_path
    ):
        mock_fetch.return_value = {
            "identifiers": [{"identifier": "https://w3id.org/changes/4/aldrovandi/itm/42/ob1/1"}],
            "rights": [{"title": {"en": "CC BY-NC 4.0 (Content license)"}, "link": "https://creativecommons.org/licenses/by-nc/4.0/"}],
            "additional_descriptions": [],
        }
        mock_extract.return_value = "cc0-1.0"
        mock_build.return_value = {"metadata": {}}

        config_file = self._make_config(tmp_path, "entity-42-dcho.yaml")
        drafts_path = self._make_drafts_json(tmp_path, [{
            "draft_id": 789,
            "config_file": str(tmp_path / "entity-42-dcho.yaml"),
            "zenodo_url": "https://zenodo.org/api",
            "access_token": "tok",
            "status": "uploaded",
        }])

        kg_path = tmp_path / "kg.ttl"
        kg_path.write_text("")

        with patch("changes_metadata_manager.patch.license_metadata.load_kg"), \
             patch("changes_metadata_manager.patch.license_metadata.publish_draft") as mock_publish:
            patch_drafts(drafts_path, kg_path, dry_run=False)

        mock_create_edit.assert_not_called()
        mock_publish.assert_not_called()

    @patch("changes_metadata_manager.patch.license_metadata.time.sleep")
    @patch("changes_metadata_manager.patch.license_metadata._fetch_record_metadata")
    def test_errors_are_logged(self, mock_fetch, mock_sleep, tmp_path):
        mock_fetch.side_effect = requests.HTTPError("500 Server Error")

        drafts_path = self._make_drafts_json(tmp_path, [{
            "draft_id": 999,
            "config_file": f"{tmp_path}/entity-42-dcho.yaml",
            "zenodo_url": "https://zenodo.org/api",
            "access_token": "tok",
            "status": "published",
        }])

        kg_path = tmp_path / "kg.ttl"
        kg_path.write_text("")

        with patch("changes_metadata_manager.patch.license_metadata.load_kg"):
            patch_drafts(drafts_path, kg_path, dry_run=False)

        log = json.loads((tmp_path / "patch_license_log.json").read_text())
        assert len(log) == 1
        assert log[0]["status"] == "error"
        assert "500 Server Error" in log[0]["error"]
        assert log[0]["record_id"] == 999

    @patch("changes_metadata_manager.patch.license_metadata.time.sleep")
    @patch("changes_metadata_manager.patch.license_metadata.extract_license_for_entity_stage")
    @patch("changes_metadata_manager.patch.license_metadata._fetch_record_metadata")
    def test_skips_already_correct(self, mock_fetch, mock_extract, mock_sleep, tmp_path):
        mock_fetch.return_value = {
            "identifiers": [{"identifier": "https://w3id.org/changes/4/aldrovandi/itm/42/ob1/1"}],
            "rights": [{"title": {"en": "CC0 (Content license)"}, "link": "https://creativecommons.org/publicdomain/zero/1.0/"}],
            "additional_descriptions": [{"description": "Ai sensi del D. Lgs. 42/2004..."}],
        }
        mock_extract.return_value = "cc0-1.0"

        drafts_path = self._make_drafts_json(tmp_path, [{
            "draft_id": 111,
            "config_file": f"{tmp_path}/entity-42-dcho.yaml",
            "zenodo_url": "https://zenodo.org/api",
            "access_token": "tok",
            "status": "published",
        }])

        kg_path = tmp_path / "kg.ttl"
        kg_path.write_text("")

        with patch("changes_metadata_manager.patch.license_metadata.load_kg"):
            patch_drafts(drafts_path, kg_path, dry_run=True)

        log = json.loads((tmp_path / "patch_license_log.json").read_text())
        assert log == []
