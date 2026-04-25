#!/usr/bin/env bash
# 携帯のキャリア回線など「自宅の Wi-Fi 外」から HTTPS でダッシュボードを開く
#
# 前提: Cloudflare のコマンド cloudflared（無償）で、PC から外向きの一時トンネルを張ります。
# インストール例（macOS）: brew install cloudflared
#
# 使い方:
#   chmod +x start_external_access.sh
#   ./start_external_access.sh
#
# 起動後、表示される https://....trycloudflare.com を携帯ブラウザで開く
#
# 注意: URL を知る人は誰でも当該PCで動いている限り中身にアクセス可能です。不要になったら Ctrl+C で止めてください。

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${STREAMLIT_PORT:-8501}"

cleanup() { kill "${STREAMPID:-0}" 2>/dev/null || true; }
trap cleanup EXIT

echo "Streamlit を 0.0.0.0:$PORT で起動します…"
python3 -m streamlit run dashboard.py \
  --server.port "$PORT" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false \
  &
STREAMPID=$!

# 起動待ち
for _ in $(seq 1 30); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT"; then
    break
  fi
  sleep 1
done

if ! command -v cloudflared &>/dev/null; then
  echo ""
  echo "================================================================"
  echo " cloudflared が未インストールのため、インターネット経由のURLは出せません。"
  echo "  インストール:  brew install cloudflared"
  echo ""
  echo "  代替: 別ターミナルで  ngrok http $PORT  （要 ngrok 登録）"
  echo "  同一Wi-Fi内のみ: このPCのIPで http://<IP>:$PORT"
  echo "================================================================"
  wait "${STREAMPID}"
  exit 0
fi

echo ""
echo "================================================================"
echo " 下に出る https://....trycloudflare.com を、外出先の携帯のブラウザに入力する"
echo " 終了すると URL は使えません（Ctrl+C）"
echo "================================================================"
echo ""
cloudflared tunnel --url "http://127.0.0.1:$PORT"
