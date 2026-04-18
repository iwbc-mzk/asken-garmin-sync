"""AWS Lambda ハンドラー - あすけん → MyFitnessPal 同期エントリーポイント.

環境変数:
    SECRET_NAME: Secrets Manager のシークレット名（省略時: "asken-myfitnesspal-sync/credentials"）
    TARGET_DATE: 同期対象日（YYYY-MM-DD 形式、省略時: JST 基準の当日）
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .config import get_target_date
from .logging_config import configure_logging
from .sync import run_sync

configure_logging()
logger = logging.getLogger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda ハンドラー."""
    secret_name = os.environ.get("SECRET_NAME")

    try:
        target_date = get_target_date()
        logger.info("同期開始: target_date=%s", target_date)
        result = run_sync(target_date, secret_name=secret_name)
    except Exception:
        logger.exception("同期中にエラーが発生しました")
        raise

    logger.info("同期完了: target_date=%s result=%s", target_date, result)
    return {
        "statusCode": 200,
        "target_date": target_date.isoformat(),
        "result": result,
    }
