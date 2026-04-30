# Daily LINE Paper Notification

GitHub Actions が毎日21:05(JST)に arXiv からEVインバータ・パワーモジュール関連の最新論文を取得し、LINEに通知します。

## ファイル

- `notify.py` — arXiv検索 + LINE Messaging API へPOST
- `.github/workflows/daily-line-notify.yml` — GitHub Actions のスケジュール定義

## セットアップ

1. このリポジトリを GitHub に作成(Private 推奨)
2. リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で以下を登録:
   - `LINE_CHANNEL_ACCESS_TOKEN`(LINE Developers の Channel access token (long-lived))
   - `LINE_USER_ID`(LINE Developers の Your user ID, U で始まる33文字)
3. リポジトリの **Actions** タブで `Daily LINE Paper Notification` を選択 → **Run workflow** を押せば手動実行で疎通確認可能

## 手動実行(任意)

ローカルでも動かせます:

```sh
export LINE_CHANNEL_ACCESS_TOKEN='...'
export LINE_USER_ID='U...'
python3 notify.py
```
