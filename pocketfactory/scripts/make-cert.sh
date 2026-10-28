#!/usr/bin/env bash
# 폰 카메라(getUserMedia)는 HTTPS에서만 동작하므로 edge용 자체 서명 인증서를 만들고,
# QR에 들어갈 주소(.env의 PUBLIC_BASE_URL)를 같은 IP로 채운다. (설계 10장)
# 사용: bash scripts/make-cert.sh                (PC의 Wi-Fi IP 자동 감지)
#       bash scripts/make-cert.sh 192.168.0.48   (자동 감지가 VPN 등으로 틀릴 때 직접 지정)
# 결과: edge/certs/cert.pem, edge/certs/key.pem (Git 제외), .env의 PUBLIC_BASE_URL
set -euo pipefail
cd "$(dirname "$0")/.."

PY=$(command -v python3 || command -v python || true)
# 기본 경로로 나가는 내 주소 (UDP connect는 실제로 패킷을 보내지 않음)
detect_ip() {
  "$PY" -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8', 80)); print(s.getsockname()[0])" 2>/dev/null
}
IP="${1:-$( [ -n "$PY" ] && detect_ip || true )}"
if [ -z "$IP" ]; then
  echo "IP를 찾지 못했습니다. 직접 넣어 주세요. 예: bash scripts/make-cert.sh 192.168.0.48" >&2
  exit 1
fi

mkdir -p edge/certs
# Git Bash가 /CN=... 를 Windows 경로로 바꾸지 않게 막음
MSYS_NO_PATHCONV=1 openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout edge/certs/key.pem -out edge/certs/cert.pem \
  -subj "/CN=$IP" \
  -addext "subjectAltName=IP:$IP,DNS:localhost,IP:127.0.0.1" 2>/dev/null

[ -f .env ] || cp .env.example .env
grep -v '^PUBLIC_BASE_URL=' .env > .env.tmp || true
echo "PUBLIC_BASE_URL=https://$IP" >> .env.tmp
mv .env.tmp .env

echo "인증서: edge/certs/ ($IP)"
echo ".env: PUBLIC_BASE_URL=https://$IP"
echo "이미 실행 중이면 반영: docker compose up -d"
