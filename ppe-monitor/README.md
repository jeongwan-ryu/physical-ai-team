# PPE Monitor

작업 현장 인원의 안전모·조끼 착용 여부를 판정하고, 그 결과를 클라우드에 자동으로 기록합니다.

```
[모니터: YouTube 현장 영상] → [ESP32-CAM] ─GET /capture─▶ [Raspberry Pi: edge] ─HTTPS─▶ [AWS EC2: caddy·server·db·dashboard] ─▶ 브라우저
                               (Arduino IDE, Docker 밖)       YOLO 추론 + 착용 판정          └──────── docker compose ────────┘   + S3(위반 스냅샷)
```

**데이터 형식은 [`docs/interface.md`](docs/interface.md)가 유일한 기준입니다.**

## 실행

```sh
cp .env.example .env               # 값 채우기
docker compose up -d --build       # http://localhost (server, db, dashboard, caddy)
python3 tools/fake_edge.py         # Pi·ESP32 없이 가짜 이벤트·프레임 전송
```

edge (Pi 또는 노트북):

```sh
cd edge
cp ../.env.example .env            # edge 항목 채우기. SOURCE=/data/sample.mp4 이면 ESP32 없이 동작
docker compose up -d --build
```

## 역할

| | 담당 | 파일 | 완료 기준 |
|---|---|---|---|
| A | ESP32-CAM, 시연 환경, Pi 기본 세팅 | `firmware/`, `docs/demo-setup.md` | `curl http://<ESP32_IP>/capture`로 640×480 JPEG 수신, 재부팅 후에도 설정 유지, 1fps로 10분 연속 요청해도 오류 없음, 거치 위치·노출값·IP를 `demo-setup.md`에 기록, Pi에 Docker 설치와 NTP 동기화 확인 |
| B | ML 모델 | `ml/` | GitHub Release `model-v1.0` 업로드, `ml/results.md`에 클래스별 mAP50(공개 데이터 val, 모니터 재촬영 val 각각)과 Pi 5 FPS 기록 |
| C | edge (Pi 앱), 전체 통합 리드 | `edge/` | `SOURCE=sample.mp4`로 실행해 서버에 이벤트 도착, 서버를 껐다 켜면 쌓인 큐가 모두 전송됨, 클래스 이름이 다른 모델을 넣으면 즉시 종료, `test_compliance.py` 통과 |
| D | server, 인프라, 가짜 데이터 도구 | `server/`, `infra/`, `docker-compose.yml`, `.env.example`, `tools/` | `docker compose up` 한 번에 전체 기동, `python3 tools/fake_edge.py --check` 통과, EC2에서 HTTPS 접속 가능 |
| E | 대시보드 | `dashboard/` | `fake_edge.py` 데이터만으로 현황·위반 로그·착용률 차트·실시간 프레임·offline 배지 동작, 퍼가기 금지 영상이면 안내 문구 표시 |

- `docs/interface.md` 변경은 PR을 올리고, 해당 연결 지점의 양쪽 담당자가 승인해야 merge합니다.
- 브랜치는 `feat/ppe-fw`, `feat/ppe-ml`, `feat/ppe-edge`, `feat/ppe-server`, `feat/ppe-web`를 씁니다. 모두 main에서 분기하고 PR로 merge합니다.

## LLM으로 개발할 때

이 폴더(`ppe-monitor/`)에서 도구를 실행하면 `AGENTS.md`/`CLAUDE.md`가 자동으로 참조됩니다. 첫 요청에서 **자기 역할(A~E)을 밝히세요.**

```
나는 C(edge) 담당이야. AGENTS.md의 C 항목대로 capture.py를 구현해줘.
```
