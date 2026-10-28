# pocketfactory

주머니 속의 스마트 팩토리: SAM 2 및 모바일 스트리밍 기반 실시간 불량 과자 검출 시스템.
설계는 [docs/design.md](docs/design.md) 참고.

## 폴더

| 폴더 | 내용 |
| --- | --- |
| `c1_gateway/` | C1: 프레임 수신, C2→C3→C4 호출, 대시보드 푸시 |
| `c2_preprocess/` | C2: 조명 보정, 과자 검출, 검사선 통과 선별 |
| `c3_sam2/` | C3: SAM 2 마스크, 원형도·솔리디티 판정 |
| `c4_visualizer/` | C4: 원본 마킹, SQLite 이력 |
| `common/` | 서비스 간 메시지 규격 (`schema.py`) |
| `edge/`, `c3_lb/` | Nginx 설정 (HTTPS 입구, C3 분산) |
| `web/` | 정적 페이지 (`capture.html`, `dashboard.html`) |
| `weights/` | SAM 2 체크포인트 (Git 제외, 직접 받아 둠) |

## 실행

```bash
bash scripts/make-cert.sh        # PC Wi-Fi IP 자동 감지 → 인증서, .env(PUBLIC_BASE_URL) 생성
docker compose up -d --build
docker compose ps                # c3-sam2 3개가 healthy인지 확인
```

1. PC에서 `https://localhost/dashboard.html`을 열고 인증서 경고를 넘김
2. 모니터에 `https://localhost/simulator.html`을 띄움
3. 폰으로 대시보드의 QR을 찍어 촬영 페이지를 열고, 인증서 경고를 넘긴 뒤 카메라 허용 → 전송 시작

Wi-Fi가 바뀌어 IP가 달라지면 `bash scripts/make-cert.sh` 후 `docker compose up -d`.
IP가 VPN 등으로 잘못 잡히면 `bash scripts/make-cert.sh 192.168.0.48`처럼 직접 지정.

## 테스트

```bash
docker compose run --rm --no-deps c1-gateway python -m c1_gateway.test_main   # C1 파이프라인
```
