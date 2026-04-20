"""pytest 共通フィクスチャ - asken_myfitnesspal_sync."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_html():
    """HTML fixture ファイルを読み込むヘルパー."""

    def _load(name: str) -> str:
        return (FIXTURES_DIR / name).read_text(encoding="utf-8")

    return _load


@pytest.fixture(autouse=True)
def mock_mfp_sleep():
    """MFP リトライのスリープをモック化してテスト実行時間を短縮する."""
    with patch("asken_myfitnesspal_sync.myfitnesspal_client.time.sleep") as mock_sleep:
        yield mock_sleep
