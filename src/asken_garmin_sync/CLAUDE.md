# asken-garmin-sync

あすけん (asken.jp) と Garmin Connect 間のデータ同期ツール。

## プロジェクト概要

- **言語**: Python
- **実行環境**: AWS Lambda
- **連携頻度**: 30分〜1時間間隔（EventBridge Scheduler等で定期実行）
- **認証情報管理**: AWS Secrets Manager

## 連携仕様

### あすけん → Garmin Connect

| データ | 方法 |
|--------|------|
| 体重 | あすけんからスクレイピングで取得 → Garmin Connect に登録 |
| 体脂肪率 | あすけんからスクレイピングで取得 → Garmin Connect に登録 |
| 摂取カロリー | **スコープ外** (Garmin Connect への書き込み手段に制限あり) |

### Garmin Connect → あすけん

| データ | 方法 |
|--------|------|
| アクティビティ消費カロリー | Garmin Connect から取得 → あすけんに登録 |

### 重複データの扱い

- 同じ日のデータが既に存在する場合は **上書き** する

## 技術スタック

### あすけん (データ取得元/登録先)

- 公式APIなし、データエクスポート機能なし
- Web スクレイピングで対応（requests + BeautifulSoup or Playwright）
- ログインURL: `https://www.asken.jp/login/`
- 認証: メール + パスワード（フォームベース）

### Garmin Connect (データ取得元/登録先)

- `garminconnect` ライブラリ (python-garminconnect) を使用
- 認証: メール + パスワード → OAuth トークン自動管理
- 体重・体脂肪率登録: `add_body_composition()` メソッド
- アクティビティ取得: `get_activities_by_date()` / `get_stats()` メソッド
- 栄養データ書き込み: ライブラリ未サポート（要検討）

## 決定事項

- 摂取カロリーのGarmin Connect連携はスコープ外（ライブラリ未サポートのため）

## 認証情報（Secrets Manager）

シークレット名: `asken-garmin-sync`

```json
{
  "asken_email": "...",
  "asken_password": "...",
  "garmin_email": "...",
  "garmin_password": "...",
  "garmin_tokens": null
}
```

> `garmin_tokens` は初回認証後に自動書き込みされる OAuth トークン群。Lambda 同時実行数=1 必須（CAS APIがないため）。

## インフラ構成

- **Lambda 関数名**: `asken-garmin-sync`
- **実行スケジュール**: 30分〜1時間間隔（EventBridge Scheduler）
- **同時実行数制限**: 1（Garmin トークンの並行書き込み破壊防止）
- **SAM テンプレート**: `template-garmin.yaml`（ルートに配置）

## エラーハンドリング・ロギング

- CloudWatch Logs へ JSON 構造化ログ出力（`src/utils/logging_config.py` の `JsonFormatter` を使用）
- 認証エラーは例外として伝播させ Lambda を失敗扱いにする
- 環境変数:
  - `SECRET_NAME`: Secrets Manager シークレット名（省略時: `asken-garmin-sync`）
  - `TARGET_DATE`: 同期対象日（省略時: JST 当日）

## モジュール構成

```
src/asken_garmin_sync/
├── __init__.py
├── handler.py          # Lambda ハンドラー
├── sync.py             # 同期ロジック（メインフロー）
├── asken_client.py     # あすけんスクレイピングクライアント
├── garmin_client.py    # Garmin Connect クライアント
├── models.py           # データモデル
├── config.py           # 設定・Secrets Manager アクセス・トークン永続化
└── logging_config.py   # src/utils/logging_config.py の re-export shim
```
