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
cp .env.example .env
bash scripts/make-cert.sh 192.168.0.48     # PC의 Wi-Fi IP
docker compose up -d --build
docker compose ps                          # c3-sam2 3개가 healthy인지 확인
```

폰에서 `https://{PC IP}/capture.html`, PC에서 `https://localhost/dashboard.html`.
