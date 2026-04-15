"""logging_config モジュールのユニットテスト."""
from __future__ import annotations

import json
import logging
import re

import pytest

from asken_garmin_sync.logging_config import JsonFormatter, configure_logging


# ── JsonFormatter ────────────────────────────────────────────────────────────


def _make_record(
    message: str = "テストメッセージ",
    level: int = logging.INFO,
    name: str = "test.logger",
) -> logging.LogRecord:
    """テスト用ログレコードを生成する（例外なし）."""
    return logging.LogRecord(
        name=name,
        level=level,
        pathname="test_logging_config.py",
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


class TestJsonFormatter:
    def setup_method(self) -> None:
        self.formatter = JsonFormatter()

    def _format(self, message: str = "msg", level: int = logging.INFO) -> dict:
        record = _make_record(message=message, level=level)
        output = self.formatter.format(record)
        return json.loads(output)

    def test_required_fields_present(self) -> None:
        data = self._format()
        assert "timestamp" in data
        assert "level" in data
        assert "logger" in data
        assert "message" in data

    def test_message_content(self) -> None:
        data = self._format(message="こんにちは世界")
        assert data["message"] == "こんにちは世界"

    def test_level_name(self) -> None:
        assert self._format(level=logging.INFO)["level"] == "INFO"
        assert self._format(level=logging.WARNING)["level"] == "WARNING"
        assert self._format(level=logging.ERROR)["level"] == "ERROR"

    def test_logger_name(self) -> None:
        record = _make_record(name="asken_garmin_sync.handler")
        data = json.loads(self.formatter.format(record))
        assert data["logger"] == "asken_garmin_sync.handler"

    def test_timestamp_format(self) -> None:
        data = self._format()
        # 例: "2026-04-14T10:00:00.123Z"
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", data["timestamp"])

    def test_output_is_single_line_json(self) -> None:
        record = _make_record()
        output = self.formatter.format(record)
        assert "\n" not in output
        json.loads(output)  # パース成功 = 有効な JSON

    def test_no_exc_info_field_when_no_exception(self) -> None:
        data = self._format()
        assert "exc_info" not in data

    def test_exc_info_field_present_when_exception(self) -> None:
        try:
            raise RuntimeError("テスト例外")
        except RuntimeError:
            import sys
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="test.py",
                lineno=1,
                msg="エラー発生",
                args=(),
                exc_info=sys.exc_info(),
            )
        data = json.loads(self.formatter.format(record))
        assert "exc_info" in data
        assert "RuntimeError" in data["exc_info"]
        assert "テスト例外" in data["exc_info"]

    def test_utc_iso_milliseconds(self) -> None:
        """_utc_iso がミリ秒を正確に変換する."""
        # created=0.123 は epoch 0.123秒 → milliseconds=123
        result = JsonFormatter._utc_iso(0.123)
        assert result.endswith("Z")
        # ミリ秒部分が存在する
        ms_part = result.split(".")[-1][:-1]  # "123Z" → "123"
        assert len(ms_part) == 3


# ── configure_logging ─────────────────────────────────────────────────────────


def _non_pytest_handlers(root: logging.Logger) -> list[logging.Handler]:
    """pytest の LogCaptureHandler を除いた通常ハンドラー一覧を返す.

    pytest はテスト中にルートロガーへ LogCaptureHandler を注入する。
    ハンドラー数を検証するテストではこれを除外する必要がある。
    """
    return [h for h in root.handlers if type(h).__name__ != "LogCaptureHandler"]


class TestConfigureLogging:
    def setup_method(self) -> None:
        # テスト前に pytest ハンドラー以外をすべて除去する
        root = logging.getLogger()
        for h in _non_pytest_handlers(root):
            root.removeHandler(h)
        root.setLevel(logging.WARNING)

    def teardown_method(self) -> None:
        root = logging.getLogger()
        for h in _non_pytest_handlers(root):
            root.removeHandler(h)
        root.setLevel(logging.WARNING)

    def test_sets_root_logger_level(self) -> None:
        configure_logging(logging.INFO)
        assert logging.getLogger().level == logging.INFO

    def test_adds_stream_handler_when_no_handlers_exist(self, mocker) -> None:
        """ハンドラーが存在しない場合は StreamHandler を追加する.

        pytest は LogCaptureHandler を常に注入するため、
        mocker で root.handlers を空リストに差し替えてテストする。
        """
        root = logging.getLogger()
        empty: list[logging.Handler] = []
        mocker.patch.object(root, "handlers", empty)

        configure_logging(logging.INFO)

        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.StreamHandler)

    def test_handler_uses_json_formatter(self, mocker) -> None:
        """StreamHandler が追加されたときフォーマッターが JsonFormatter になっている."""
        root = logging.getLogger()
        empty: list[logging.Handler] = []
        mocker.patch.object(root, "handlers", empty)

        configure_logging()

        assert isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_new_stream_handler_level_is_set(self, mocker) -> None:
        """新規追加 StreamHandler にもレベルが設定される（既存ハンドラーと一貫性）."""
        root = logging.getLogger()
        empty: list[logging.Handler] = []
        mocker.patch.object(root, "handlers", empty)

        configure_logging(logging.INFO)

        assert root.handlers[0].level == logging.INFO

    def test_replaces_formatter_on_existing_handlers(self) -> None:
        root = logging.getLogger()
        existing = logging.StreamHandler()
        existing.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(existing)

        configure_logging()

        assert isinstance(existing.formatter, JsonFormatter)

    def test_sets_level_on_existing_handlers(self) -> None:
        """既存ハンドラーの個別レベルも INFO に設定される（Lambda 環境対策）."""
        root = logging.getLogger()
        existing = logging.StreamHandler()
        existing.setLevel(logging.WARNING)  # Lambda の LambdaLoggerHandler に相当
        root.addHandler(existing)

        configure_logging(logging.INFO)

        assert existing.level == logging.INFO

    def test_does_not_add_extra_handler_when_existing(self) -> None:
        root = logging.getLogger()
        existing = logging.StreamHandler()
        root.addHandler(existing)

        configure_logging()

        assert len(_non_pytest_handlers(root)) == 1

    def test_existing_handler_formatter_is_json_after_configure(self) -> None:
        """既存ハンドラーが configure_logging 後に JSON フォーマッターを持つ."""
        root = logging.getLogger()
        existing = logging.StreamHandler()
        root.addHandler(existing)

        configure_logging(logging.DEBUG)

        formatter = existing.formatter
        assert isinstance(formatter, JsonFormatter)

        record = logging.LogRecord(
            name="test_output",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="JSON テスト",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "JSON テスト"
        assert data["level"] == "INFO"
