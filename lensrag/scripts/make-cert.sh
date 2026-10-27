#!/usr/bin/env bash
# 폰 카메라(getUserMedia)는 HTTPS에서만 동작하므로 api-https용 자체 서명 인증서를 만든다.
# 사용: bash scripts/make-cert.sh 192.168.0.48   (PC의 Wi-Fi IP)
# 결과: certs/cert.pem, certs/key.pem (Git 제외)
set -euo pipefail

IP="${1:?PC의 Wi-Fi IP를 넣어주세요. 예: bash scripts/make-cert.sh 192.168.0.48}"
cd "$(dirname "$0")/.."
mkdir -p certs

# Git Bash가 /CN=... 를 Windows 경로로 바꾸지 않게 막음
MSYS_NO_PATHCONV=1 openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout certs/key.pem -out certs/cert.pem \
  -subj "/CN=$IP" \
  -addext "subjectAltName=IP:$IP,DNS:localhost,IP:127.0.0.1"

echo "생성 완료: certs/cert.pem, certs/key.pem ($IP)"
