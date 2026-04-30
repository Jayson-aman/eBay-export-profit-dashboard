# GitHub 連携と携帯ブラウザで見る（Streamlit Community Cloud）

このリポジトリを **GitHub に公開**し、[Streamlit Community Cloud](https://streamlit.io/cloud) と連携すると、**HTTPS の URL をスマホの Safari / Chrome で開ける**ようになります（PC 常時起動や cloudflared トンネルが不要）。

## 手順の概要

1. GitHub にリポジトリを作成し、このプロジェクトを `git push` する。
2. [Streamlit Community Cloud](https://share.streamlit.io/) にログインし、**New app** で該当リポジトリを選択する。
3. **Main file path** に `amazon_fba_research_app.py` を指定する。
4. **Secrets**（鍵アイコン）に、楽天・Yahoo の API キーを TOML で登録する（下記サンプル）。
5. **Deploy** 後に表示される `https://....streamlit.app` をスマホのブラウザで開く。

## Secrets の例（Streamlit Cloud の入力欄にそのまま貼れる形式）

`.streamlit/secrets.toml.example` と同様です。

```toml
RAKUTEN_APP_ID = "あなたの楽天アプリケーションID"
YAHOO_APP_ID = "あなたのYahoo_Client_ID"
```

登録後、アプリ左サイドバーの API 欄にはデフォルトで反映されます（画面上ではマスク表示されます）。

## 注意

- **無料枠は公開リポジトリ前提**のことが多いです。プライベートリポジトリの場合は Streamlit の料金プランを確認してください。
- クラウド上のアプリは **URL を知っている人がアクセス可能**です。API キーは必ず **Secrets** にだけ置き、Git にコミットしないでください。
- トラフィックや利用規約は Streamlit / GitHub 各公式の最新情報に従ってください。

## ローカル＋携帯（自宅PCから一時公開する方法）

リポジトリ連携を使わず、一時的にスマホから見るだけなら、プロジェクト内の `start_external_access.sh`（要 cloudflared）も利用できます。

```bash
STREAMLIT_APP=amazon_fba_research_app.py ./start_external_access.sh
```
