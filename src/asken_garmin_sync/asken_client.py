"""あすけんクライアント - ログイン・体重取得・運動カロリー登録."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from typing import Any

import requests
from bs4 import BeautifulSoup

from .models import BodyComposition

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.asken.jp"
_LOGIN_URL = f"{_BASE_URL}/login/"
_COMMENT_URL = f"{_BASE_URL}/wsp/comment/{{date}}"
_EXERCISE_URL = f"{_BASE_URL}/wsp/exercise/{{date}}"
_EXERCISE_ADD_URL = f"{_BASE_URL}/exercise/add/{{exercise_id}}"
_EXERCISE_DELETE_URL = f"{_BASE_URL}/exercise/delete_v2/{{item_type}}/{{authcode}}"

_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# 運動登録のデフォルト設定
# exercise_id はあすけん運動カタログの ID（要確認）
# cal_per_min は選択した運動種目の消費カロリー/分
DEFAULT_EXERCISE_ID: int = 1
DEFAULT_CAL_PER_MIN: float = 4.0  # kcal/分

# リトライ設定（認証エラーはリトライしない）
_MAX_RETRIES: int = 2
_RETRY_BASE_DELAY: float = 1.0  # 指数バックオフの基底（秒）


class AskenAuthError(Exception):
    """あすけん認証エラー（リトライ不可）."""


class AskenError(Exception):
    """あすけん操作エラー."""


def _request_with_retry(
    fn: Any,
    *args: Any,
    max_retries: int = _MAX_RETRIES,
    **kwargs: Any,
) -> requests.Response:
    """接続エラー時に最大 max_retries 回指数バックオフでリトライする.

    - 認証エラー (401/403) はリトライせず即座に例外を送出する
    - ログインページへのリダイレクト（セッション切れ）も認証エラーとして扱う
    """
    if max_retries < 0:
        raise ValueError(f"max_retries は 0 以上である必要があります: {max_retries}")

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp: requests.Response = fn(*args, **kwargs)
            if resp.status_code in (401, 403):
                raise AskenAuthError(
                    f"あすけんへのアクセスが拒否されました (HTTP {resp.status_code})"
                )
            resp.raise_for_status()
            # セッション切れ判定: リダイレクト後の最終 URL がログインページ
            # startswith を使い /login/logout 等の誤検知を防ぐ
            if resp.url.startswith(_LOGIN_URL):
                raise AskenAuthError(
                    "セッションが切れています。再ログインが必要です。"
                )
            return resp
        except AskenAuthError:
            raise
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "リクエスト失敗 (attempt %d/%d): %s — %.1f秒後にリトライ",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)
            else:
                raise AskenError(
                    f"リクエストが {max_retries + 1} 回失敗しました"
                ) from last_exc
    raise AskenError("リトライ上限に達しました")  # unreachable


class AskenClient:
    """あすけんスクレイピングクライアント."""

    def __init__(self, email: str, password: str) -> None:
        self._session: requests.Session = self._login(email, password)

    # ─── 認証 ────────────────────────────────────────────────────────────────

    def _login(self, email: str, password: str) -> requests.Session:
        """ログインページから CSRF / _Token 系 hidden input を取得してフォームログインする.

        CakePHP 2.x のフォーム保護には data[_Token][key], [fields], [unlocked] が必要。
        すべての hidden input を収集して payload に含める。

        Raises:
            AskenAuthError: 認証失敗（リトライ不可）
        """
        session = requests.Session()

        # Step 1: ログインページから _Token 系 hidden input をすべて収集
        try:
            get_resp = session.get(_LOGIN_URL, headers=_HEADERS, timeout=30)
            get_resp.raise_for_status()
        except requests.RequestException as exc:
            # ネットワーク障害・HTTP エラーは AskenError（リトライ可能）
            # 認証情報不正とは区別する
            raise AskenError("ログインページの取得に失敗しました") from exc

        soup = BeautifulSoup(get_resp.text, "lxml")
        login_form = soup.find("form", {"id": "indexForm"})
        if login_form is None:
            raise AskenAuthError("ログインフォームが見つかりません")

        # フォーム内の全 hidden input を収集
        payload: dict[str, Any] = {}
        for hidden in login_form.find_all("input", {"type": "hidden"}):
            name = hidden.get("name")
            value = hidden.get("value", "")
            if isinstance(name, str) and name:
                payload[name] = value

        if "data[_Token][key]" not in payload:
            raise AskenAuthError("ログインページの CSRF トークンが見つかりません")
        if not payload["data[_Token][key]"]:
            raise AskenAuthError("CSRF トークンが空です")

        # Step 2: ユーザー認証情報を追加して POST
        payload.update(
            {
                "data[CustomerMember][email]": email,
                "data[CustomerMember][passwd_plain]": password,
                "data[CustomerMember][autologin]": "1",
            }
        )
        try:
            post_resp = session.post(
                _LOGIN_URL,
                headers=_HEADERS,
                data=payload,
                timeout=30,
            )
            post_resp.raise_for_status()
        except requests.RequestException as exc:
            # ネットワーク障害・HTTP エラーは AskenError（リトライ可能）
            raise AskenError("ログインリクエストに失敗しました") from exc

        # ログイン成功判定:
        #   1. 最終 URL がログインページでない（リダイレクトされた）
        #   2. 「ログアウト」リンクが存在する
        if post_resp.url.startswith(_LOGIN_URL):
            raise AskenAuthError(
                "あすけんのログインに失敗しました（ログインページへリダイレクト）"
            )
        if "ログアウト" not in post_resp.text:
            raise AskenAuthError(
                "あすけんのログインに失敗しました（メールアドレスまたはパスワードを確認してください）"
            )

        logger.info("あすけんにログインしました")
        return session

    # ─── 体重・体脂肪率取得 ──────────────────────────────────────────────────

    def get_body_composition(self, target_date: date) -> BodyComposition | None:
        """コメントページから体重・体脂肪率を取得する.

        Returns:
            BodyComposition: 体重が記録されている場合
            None: 体重が未記録の場合
        Raises:
            AskenError: ページ取得またはパース失敗
        """
        url = _COMMENT_URL.format(date=target_date.isoformat())
        resp = _request_with_retry(
            self._session.get, url, headers=_HEADERS, timeout=30
        )

        soup = BeautifulSoup(resp.text, "lxml")

        weight_input = soup.find("input", {"name": "data[Body][weight]"})
        fat_input = soup.find("input", {"name": "data[Body][body_fat]"})

        if weight_input is None:
            logger.warning("体重入力フィールドが見つかりません: %s", target_date)
            return None

        weight_raw = weight_input.get("value")  # type: ignore[union-attr]
        weight_str = str(weight_raw).strip() if weight_raw is not None else ""

        if not weight_str:
            logger.debug("体重未記録: %s", target_date)
            return None

        try:
            weight_kg = float(weight_str)
        except ValueError as exc:
            raise AskenError(f"体重の解析に失敗しました: {weight_str!r}") from exc

        body_fat: float | None = None
        if fat_input is not None:
            fat_raw = fat_input.get("value")  # type: ignore[union-attr]
            fat_str = str(fat_raw).strip() if fat_raw is not None else ""
            if fat_str:
                try:
                    body_fat = float(fat_str)
                except ValueError:
                    logger.warning("体脂肪率の解析に失敗しました: %r（スキップ）", fat_str)

        logger.debug(
            "体重・体脂肪率取得: %s weight=%.1f fat=%s",
            target_date,
            weight_kg,
            f"{body_fat:.1f}%" if body_fat is not None else "未記録",
        )
        return BodyComposition(
            date=target_date,
            weight_kg=weight_kg,
            body_fat_percent=body_fat,
        )

    # ─── 運動カロリー登録 ────────────────────────────────────────────────────

    _AUTHCODE_RE = re.compile(r"delete_exercise_v2\('([^']+)',\s*'([^']+)'\)")

    def _get_exercise_entries(self, target_date: date) -> list[tuple[str, str]]:
        """運動ページから既存エントリの (item_type, authcode) リストを取得する.

        onclick 属性から正規表現で authcode を抽出する。
        BeautifulSoup でパース後の属性値に適用することで
        HTML エンティティのエスケープ問題を回避する。
        """
        url = _EXERCISE_URL.format(date=target_date.isoformat())
        resp = _request_with_retry(
            self._session.get, url, headers=_HEADERS, timeout=30
        )
        soup = BeautifulSoup(resp.text, "lxml")

        entries: list[tuple[str, str]] = []
        for tag in soup.find_all(onclick=self._AUTHCODE_RE):
            onclick_val = tag.get("onclick", "")
            if not isinstance(onclick_val, str):
                continue
            for match in self._AUTHCODE_RE.finditer(onclick_val):
                entries.append((match.group(1), match.group(2)))

        logger.debug("既存の運動エントリ %d 件を検出: %s", len(entries), target_date)
        return entries

    def _delete_exercise_entry(
        self, target_date: date, item_type: str, authcode: str
    ) -> None:
        """運動エントリを削除する."""
        url = _EXERCISE_DELETE_URL.format(item_type=item_type, authcode=authcode)
        _request_with_retry(
            self._session.get,
            url,
            params={"record_date": target_date.isoformat()},
            headers=_HEADERS,
            timeout=30,
        )
        logger.debug("運動エントリを削除しました: %s/%s", item_type, authcode)

    def _add_exercise_entry(
        self, target_date: date, exercise_id: int, amount: int
    ) -> None:
        """運動エントリを追加する.

        Args:
            exercise_id: あすけん運動カタログ ID
            amount: 運動時間（分）
        """
        url = _EXERCISE_ADD_URL.format(exercise_id=exercise_id)
        resp = _request_with_retry(
            self._session.post,
            url,
            params={"record_date": target_date.isoformat()},
            data={"amount": amount},
            headers=_HEADERS,
            timeout=30,
        )
        try:
            data: dict[str, Any] = resp.json()
        except json.JSONDecodeError as exc:
            raise AskenError("運動登録 API のレスポンスが JSON ではありません") from exc

        if data.get("result") != "OK":
            raise AskenError(f"運動登録に失敗しました: {data}")

        logger.debug(
            "運動エントリを追加しました: exercise_id=%d amount=%d分", exercise_id, amount
        )

    def register_activity_calories(
        self,
        target_date: date,
        calories: int,
        exercise_id: int = DEFAULT_EXERCISE_ID,
        cal_per_min: float = DEFAULT_CAL_PER_MIN,
    ) -> None:
        """Garmin のアクティビティカロリーをあすけん運動ページに登録する（上書き対応）.

        既存の全運動エントリを削除してから新しいエントリを追加する。

        Args:
            target_date: 対象日
            calories: 登録するカロリー（kcal）
            exercise_id: あすけん運動カタログ ID
            cal_per_min: 選択した運動の消費カロリー/分

        Raises:
            AskenError: 登録失敗
        """
        if calories <= 0:
            logger.info("カロリーが 0 以下のため運動登録をスキップ: %s", target_date)
            return

        # 既存エントリを全削除（上書き）
        entries = self._get_exercise_entries(target_date)
        for item_type, authcode in entries:
            self._delete_exercise_entry(target_date, item_type, authcode)
            time.sleep(0.3)  # 連続削除のレート制限対策

        if entries:
            logger.debug("%d 件の既存運動エントリを削除しました", len(entries))

        # カロリーから運動時間を算出（5分単位、四捨五入、最小5分）
        # Python の round() は銀行家の丸めを使うため int(x + 0.5) で明示的に四捨五入する
        raw_minutes = calories / cal_per_min
        amount = max(5, int(raw_minutes / 5 + 0.5) * 5)
        logger.debug(
            "運動時間算出: %dkcal ÷ %.1fkcal/分 → %d分（5分単位）",
            calories,
            cal_per_min,
            amount,
        )

        self._add_exercise_entry(target_date, exercise_id, amount)
        logger.info(
            "あすけんに運動を登録しました: %s %dkcal → exercise_id=%d %d分",
            target_date,
            calories,
            exercise_id,
            amount,
        )
