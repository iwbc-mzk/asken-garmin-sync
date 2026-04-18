"""設定モジュールのユニットテスト（Phase 3）."""
from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.asken_myfitnesspal_sync.config import Credentials, get_credentials, get_target_date

_JST = ZoneInfo("Asia/Tokyo")


def _make_secret_response(payload: dict) -> dict:
    return {"SecretString": json.dumps(payload)}


_VALID_SECRET = {
    "asken_email": "asken@example.com",
    "asken_password": "asken_pass",
    "myfitnesspal_email": "mfp@example.com",
    "myfitnesspal_password": "mfp_pass",
}


class TestGetCredentials:
    def _patch_client(self, secret_payload: dict | None = None, secret_string: str | None = None):
        mock_client = MagicMock()
        if secret_string is not None:
            mock_client.get_secret_value.return_value = {"SecretString": secret_string}
        else:
            payload = secret_payload if secret_payload is not None else _VALID_SECRET
            mock_client.get_secret_value.return_value = _make_secret_response(payload)
        return mock_client

    def test_returns_credentials_with_valid_secret(self):
        mock_client = self._patch_client()
        with patch("src.asken_myfitnesspal_sync.config._secrets_client", return_value=mock_client):
            creds = get_credentials("test-secret")

        assert isinstance(creds, Credentials)
        assert creds.asken_email == "asken@example.com"
        assert creds.asken_password == "asken_pass"
        assert creds.myfitnesspal_email == "mfp@example.com"
        assert creds.myfitnesspal_password == "mfp_pass"

    def test_uses_default_secret_name_when_not_specified(self):
        mock_client = self._patch_client()
        env = {"SECRET_NAME": ""}
        with (
            patch("src.asken_myfitnesspal_sync.config._secrets_client", return_value=mock_client),
            patch.dict(os.environ, env, clear=False),
        ):
            get_credentials()

        mock_client.get_secret_value.assert_called_once_with(
            SecretId="asken-myfitnesspal-sync/credentials"
        )

    def test_uses_env_secret_name_when_set(self):
        mock_client = self._patch_client()
        env = {"SECRET_NAME": "custom/secret"}
        with (
            patch("src.asken_myfitnesspal_sync.config._secrets_client", return_value=mock_client),
            patch.dict(os.environ, env, clear=False),
        ):
            get_credentials()

        mock_client.get_secret_value.assert_called_once_with(SecretId="custom/secret")

    def test_explicit_secret_name_overrides_env(self):
        mock_client = self._patch_client()
        env = {"SECRET_NAME": "env/secret"}
        with (
            patch("src.asken_myfitnesspal_sync.config._secrets_client", return_value=mock_client),
            patch.dict(os.environ, env, clear=False),
        ):
            get_credentials("explicit/secret")

        mock_client.get_secret_value.assert_called_once_with(SecretId="explicit/secret")

    def test_raises_when_secret_string_is_missing(self):
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {}
        with (
            patch("src.asken_myfitnesspal_sync.config._secrets_client", return_value=mock_client),
            pytest.raises(ValueError, match="SecretString"),
        ):
            get_credentials("test-secret")

    def test_raises_when_secret_string_is_empty(self):
        mock_client = self._patch_client(secret_string="")
        with (
            patch("src.asken_myfitnesspal_sync.config._secrets_client", return_value=mock_client),
            pytest.raises(ValueError, match="SecretString"),
        ):
            get_credentials("test-secret")

    def test_raises_on_invalid_json(self):
        mock_client = self._patch_client(secret_string="not-json")
        with (
            patch("src.asken_myfitnesspal_sync.config._secrets_client", return_value=mock_client),
            pytest.raises(ValueError, match="JSON"),
        ):
            get_credentials("test-secret")

    def test_raises_when_secret_is_not_object(self):
        mock_client = self._patch_client(secret_string='["list"]')
        with (
            patch("src.asken_myfitnesspal_sync.config._secrets_client", return_value=mock_client),
            pytest.raises(ValueError, match="形式が不正"),
        ):
            get_credentials("test-secret")

    @pytest.mark.parametrize(
        "missing_key",
        ["asken_email", "asken_password", "myfitnesspal_email", "myfitnesspal_password"],
    )
    def test_raises_when_required_key_missing(self, missing_key: str):
        secret = {k: v for k, v in _VALID_SECRET.items() if k != missing_key}
        mock_client = self._patch_client(secret_payload=secret)
        with (
            patch("src.asken_myfitnesspal_sync.config._secrets_client", return_value=mock_client),
            pytest.raises(ValueError, match="必須キー"),
        ):
            get_credentials("test-secret")

    def test_repr_does_not_expose_passwords(self):
        mock_client = self._patch_client()
        with patch("src.asken_myfitnesspal_sync.config._secrets_client", return_value=mock_client):
            creds = get_credentials("test-secret")

        repr_str = repr(creds)
        assert "asken_pass" not in repr_str
        assert "mfp_pass" not in repr_str
        assert "asken@example.com" in repr_str


class TestGetTargetDate:
    def test_returns_today_jst_when_env_not_set(self):
        fixed_jst_dt = datetime(2024, 3, 15, 10, 0, 0, tzinfo=_JST)
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("src.asken_myfitnesspal_sync.config.datetime") as mock_dt,
        ):
            os.environ.pop("TARGET_DATE", None)
            mock_dt.now.return_value = fixed_jst_dt
            result = get_target_date()

        assert result == date(2024, 3, 15)
        mock_dt.now.assert_called_once_with(_JST)

    def test_returns_jst_date_not_utc_at_boundary(self):
        # UTC 15:00 = JST 翌日 00:00（日付境界テスト）
        utc_dt = datetime(2024, 3, 14, 15, 0, 0, tzinfo=UTC)
        jst_dt = utc_dt.astimezone(_JST)  # 2024-03-15 00:00 JST
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("src.asken_myfitnesspal_sync.config.datetime") as mock_dt,
        ):
            os.environ.pop("TARGET_DATE", None)
            mock_dt.now.return_value = jst_dt
            result = get_target_date()

        assert result == date(2024, 3, 15)

    def test_returns_date_from_env_var(self):
        with patch.dict(os.environ, {"TARGET_DATE": "2024-03-15"}, clear=False):
            result = get_target_date()

        assert result == date(2024, 3, 15)

    def test_raises_on_invalid_date_format_slash(self):
        with (
            patch.dict(os.environ, {"TARGET_DATE": "2024/03/15"}, clear=False),
            pytest.raises(ValueError, match="TARGET_DATE"),
        ):
            get_target_date()

    def test_raises_on_compact_format_yyyymmdd(self):
        # YYYYMMDD は Python 3.12 の fromisoformat では受理されるが仕様外
        with (
            patch.dict(os.environ, {"TARGET_DATE": "20240315"}, clear=False),
            pytest.raises(ValueError, match="TARGET_DATE"),
        ):
            get_target_date()

    def test_raises_on_iso_week_format(self):
        # ISO 週番号形式（YYYY-Www-D）も仕様外
        with (
            patch.dict(os.environ, {"TARGET_DATE": "2024-W11-1"}, clear=False),
            pytest.raises(ValueError, match="TARGET_DATE"),
        ):
            get_target_date()

    def test_raises_on_non_date_string(self):
        with (
            patch.dict(os.environ, {"TARGET_DATE": "not-a-date"}, clear=False),
            pytest.raises(ValueError, match="TARGET_DATE"),
        ):
            get_target_date()

    @pytest.mark.parametrize(
        "invalid_date",
        ["2024-02-30", "2024-13-01", "2024-00-15", "2024-01-00"],
    )
    def test_raises_on_impossible_calendar_date(self, invalid_date: str):
        # _DATE_RE を通過するが date.fromisoformat() で失敗する暦として無効な日付
        with (
            patch.dict(os.environ, {"TARGET_DATE": invalid_date}, clear=False),
            pytest.raises(ValueError, match="TARGET_DATE"),
        ):
            get_target_date()
