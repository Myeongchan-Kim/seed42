#!/bin/bash
# VM 초기 설치. 여러 번 실행해도 안전하다.
set -euo pipefail

echo "== 패키지 =="
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-dev build-essential \
  debian-keyring debian-archive-keyring apt-transport-https curl gnupg

echo "== Caddy =="
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq caddy
fi

echo "== 사용자·디렉터리 =="
id seed42 >/dev/null 2>&1 || sudo useradd -r -m -d /opt/seed42 -s /bin/bash seed42
sudo mkdir -p /opt/seed42/logs /var/log/caddy
sudo chown -R seed42:seed42 /opt/seed42
sudo chown -R caddy:caddy /var/log/caddy

echo "== 파이썬 환경 =="
sudo -u seed42 bash -c '
  cd /opt/seed42
  [ -d .venv ] || python3 -m venv .venv
  ./.venv/bin/pip -q install --upgrade pip
  ./.venv/bin/pip -q install -r requirements.txt
  for m in en_core_web_sm es_core_news_sm zh_core_web_sm ja_core_news_sm ko_core_news_sm; do
    ./.venv/bin/python -c "import spacy; spacy.load(\"$m\")" 2>/dev/null \
      || ./.venv/bin/python -m spacy download $m -q
  done
'

echo "== 서비스 =="
sudo cp /opt/seed42/deploy/Caddyfile /etc/caddy/Caddyfile
sudo cp /opt/seed42/deploy/seed42.service /etc/systemd/system/
sudo cp /opt/seed42/deploy/seed42-daily.service /etc/systemd/system/
sudo cp /opt/seed42/deploy/seed42-daily.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now seed42.service
sudo systemctl enable --now seed42-daily.timer
sudo systemctl reload caddy || sudo systemctl restart caddy

echo "== 상태 =="
systemctl is-active seed42.service caddy seed42-daily.timer || true
