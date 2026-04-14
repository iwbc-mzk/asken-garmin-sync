"""Lambda ハンドラーのユニットテスト."""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from asken_garmin_sync.asken_client import AskenAuthError
from asken_garmin_sync.garmin_client import GarminAuthError


# ─── _get_target_date ────────────────────────────────────────────────────────


def test_get_target_date_uses_jst_today(monkeypatch):
    """TARGET_DATE 未設定時は JST 基準の当日を返す."""
    monkeypatch.delenv("TARGET_DATE", raising=False)

    fixed_now = datetime(2026, 4, 14, 10, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    with patch("asken_garmin_sync.handler.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        from asken_garmin_sync.handler import _get_target_date

        result = _get_target_date()

    assert result == date(2026, 4, 14)
    mock_dt.now.assert_called_once_with(ZoneInfo("Asia/Tokyo"))


def test_get_target_date_uses_env_override(monkeypatch):
    """TARGET_DATE 設定時はその日付を返す."""
    monkeypatch.setenv("TARGET_DATE", "2026-01-15")

    from asken_garmin_sync.handler import _get_target_date

    result = _get_target_date()

    assert result == date(2026, 1, 15)


def test_get_target_date_invalid_format_raises(monkeypatch):
    """TARGET_DATE の形式が不正な場合は ValueError を送出する."""
    monkeypatch.setenv("TARGET_DATE", "2026/04/14")  # スラッシュ区切りは ISO 形式でない

    from asken_garmin_sync.handler import _get_target_date

    with pytest.raises(ValueError, match="TARGET_DATE の形式が不正"):
        _get_target_date()


# ─── lambda_handler ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_handler_env(monkeypatch):
    """lambda_handler の外部依存をモックするフィクスチャ."""
    monkeypatch.setenv("TARGET_DATE", "2026-04-14")

    with patch("asken_garmin_sync.handler.run_sync") as mock_run_sync:
        mock_run_sync.return_value = {
            "body_composition": {"synced": True, "error": None},
            "calories": {"synced": True, "error": None},
        }
        yield mock_run_sync


def test_lambda_handler_success(mock_handler_env):
    """正常系: run_sync が成功した場合は statusCode 200 とともに結果を返す."""
    from asken_garmin_sync.handler import lambda_handler

    response = lambda_handler({}, MagicMock())

    assert response["statusCode"] == 200
    assert response["target_date"] == "2026-04-14"
    assert response["result"]["body_composition"]["synced"] is True
    assert response["result"]["calories"]["synced"] is True
    mock_handler_env.assert_called_once_with(date(2026, 4, 14), secret_name=None)


def test_lambda_handler_passes_correct_date(mock_handler_env):
    """TARGET_DATE 環境変数の日付が run_sync に渡される."""
    from asken_garmin_sync.handler import lambda_handler

    lambda_handler({}, MagicMock())

    mock_handler_env.assert_called_once_with(date(2026, 4, 14), secret_name=None)


def test_lambda_handler_reraises_auth_error(mock_handler_env):
    """run_sync が認証エラーを投げた場合は再送出する（Lambda を失敗させる）."""
    mock_handler_env.side_effect = GarminAuthError("MFA要求")

    from asken_garmin_sync.handler import lambda_handler

    with pytest.raises(GarminAuthError):
        lambda_handler({}, MagicMock())


def test_lambda_handler_reraises_asken_auth_error(mock_handler_env):
    """run_sync が AskenAuthError を投げた場合は再送出する."""
    mock_handler_env.side_effect = AskenAuthError("認証失敗")

    from asken_garmin_sync.handler import lambda_handler

    with pytest.raises(AskenAuthError):
        lambda_handler({}, MagicMock())


def test_lambda_handler_reraises_unexpected_error(mock_handler_env):
    """run_sync が予期しない例外を投げた場合は再送出する."""
    mock_handler_env.side_effect = RuntimeError("予期しないエラー")

    from asken_garmin_sync.handler import lambda_handler

    with pytest.raises(RuntimeError):
        lambda_handler({}, MagicMock())


def test_lambda_handler_partial_sync_result(mock_handler_env):
    """片方のみ同期成功した場合も正常にレスポンスを返す."""
    mock_handler_env.return_value = {
        "body_composition": {"synced": True, "error": None},
        "calories": {"synced": False, "error": "API失敗"},
    }

    from asken_garmin_sync.handler import lambda_handler

    response = lambda_handler({}, MagicMock())

    assert response["statusCode"] == 200
    assert response["result"]["body_composition"]["synced"] is True
    assert response["result"]["calories"]["synced"] is False
    assert response["result"]["calories"]["error"] == "API失敗"


def test_lambda_handler_invalid_target_date_env(monkeypatch):
    """TARGET_DATE が不正な場合は ValueError を送出する（Lambda を失敗させる）."""
    monkeypatch.setenv("TARGET_DATE", "not-a-date")

    from asken_garmin_sync.handler import lambda_handler

    with pytest.raises(ValueError, match="TARGET_DATE の形式が不正"):
        lambda_handler({}, MagicMock())


def test_lambda_handler_jst_date_without_env(monkeypatch):
    """TARGET_DATE 未設定時に JST 基準の日付が run_sync に渡される."""
    monkeypatch.delenv("TARGET_DATE", raising=False)

    fixed_now = datetime(2026, 4, 14, 23, 59, 59, tzinfo=ZoneInfo("Asia/Tokyo"))

    with (
        patch("asken_garmin_sync.handler.datetime") as mock_dt,
        patch("asken_garmin_sync.handler.run_sync") as mock_run_sync,
    ):
        mock_dt.now.return_value = fixed_now
        mock_run_sync.return_value = {
            "body_composition": {"synced": False, "error": None},
            "calories": {"synced": False, "error": None},
        }

        from asken_garmin_sync.handler import lambda_handler

        lambda_handler({}, MagicMock())

    mock_run_sync.assert_called_once_with(date(2026, 4, 14), secret_name=None)
