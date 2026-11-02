# AGENTS.md — ppe-monitor

LLM 코딩 도구용 지침입니다. **README.md와 docs/interface.md를 먼저 읽으세요.** 데이터 형식은 interface.md만이 기준입니다.

## 규칙

- 사용자의 역할(A~E)을 모르면 작업을 시작하기 전에 먼저 묻습니다.
- 사용자가 맡은 역할의 폴더와 파일만 수정합니다(README 역할 표 참고).
- `docs/interface.md`는 수정하지 않습니다. 변경이 필요하면 제안만 하고 멈춥니다(해당 연결 지점의 양쪽 담당자가 승인할 사항).
- interface.md에 없는 필드, 엔드포인트, 환경변수 이름을 만들지 않습니다.
- 아래 "결정된 사항"을 뒤집지 않습니다. 더 나은 방법이 있으면 제안만 합니다.
- 각 역할 메모에 적힌 것 외의 의존성은 추가하지 않습니다. 필요하면 제안만 합니다.
- 비밀값(토큰, 비밀번호, Wi-Fi 정보, AWS 키)은 코드나 커밋에 넣지 않습니다. `.env`나 `secrets.h`에만 둡니다.

## 결정된 사항

| 결정 | 이유 |
|---|---|
| ESP32 펌웨어는 Arduino IDE의 `CameraWebServer` 예제를 수정해서 사용. ESP-IDF·PlatformIO는 쓰지 않음 | interface가 요구하는 `GET /capture`가 예제에 이미 있음 |
| Pi가 ESP32에 `/capture`를 요청해서 가져감(pull). MJPEG 스트림(:81)은 쓰지 않음 | 처리 속도를 Pi가 결정하고, 스트림을 쓰면 OpenCV 버퍼 때문에 지연이 쌓임 |
| 추론은 Pi에서 수행. 클라우드에는 판정 결과와 위반 스냅샷만 전송 | 대역폭, 비용, 개인정보 |
| 모델은 Ultralytics YOLO11n, 클래스 3개(`person`, `helmet`, `vest`), NCNN으로 export | Pi 5 CPU에서 실시간 처리. 미착용은 모델이 아니라 edge가 판정 |
| edge → server는 HTTP REST. MQTT와 AWS IoT Core는 쓰지 않음 | 로컬에서 그대로 재현 가능, curl로 디버깅 가능 |
| 대시보드는 2초 간격 폴링. WebSocket과 SSE는 쓰지 않음 | 갱신 주기가 초 단위라 폴링으로 충분 |
| AWS는 EC2 1대 + docker compose + S3. Lambda와 DynamoDB는 쓰지 않음 | 로컬과 운영 환경을 동일하게 유지 |
| DB는 PostgreSQL 16, 테이블 1개. ORM과 마이그레이션 도구는 쓰지 않음 | 서버 시작 시 `CREATE TABLE IF NOT EXISTS`로 충분 |
| 리버스 프록시는 Caddy(Basic Auth). nginx는 쓰지 않음 | 설정이 짧음 |
| HTTPS는 쓰지 않음. 대신 EC2 보안 그룹에서 80번을 **집 IP만** 허용 | 시연은 집에서만 함. 도메인·인증서 관리가 필요 없음 |
| 사람 추적(tracking)과 YouTube Data API는 v0.1 범위 밖 | 요구사항에 없음 |

## 역할별 구현 메모

### A — `firmware/`, `docs/demo-setup.md`

- Arduino IDE와 `esp32 by Espressif` 코어 3.x를 사용합니다. 쓴 버전은 `firmware/esp32cam/README.md`에 기록합니다.
- `파일 → 예제 → ESP32 → Camera → CameraWebServer`를 `firmware/esp32cam/CameraWebServer/`로 통째로 복사합니다. 폴더 이름과 `.ino` 이름이 같아야 합니다.
- 보드 설정: `AI Thinker ESP32-CAM`, PSRAM `Enabled`, Partition Scheme `Huge APP`. README에 기록합니다.
- 카메라 모델은 `CAMERA_MODEL_AI_THINKER`입니다. 코어 버전에 따라 `.ino`에 있기도 하고 `board_config.h`에 있기도 합니다.
- Wi-Fi 정보는 `secrets.h`(gitignore 대상)에 `WIFI_SSID`, `WIFI_PASS`로 넣습니다. 레포에는 `secrets.h.example`만 커밋합니다.
- `setup()`에서 예제의 QVGA 설정 줄을 대체해 다음 값을 고정합니다. `set_framesize(FRAMESIZE_VGA)`, `set_quality(12)`, `set_whitebal(0)`, `set_exposure_ctrl(0)`, `set_aec_value(<보정값>)`. 웹 UI에서 바꾼 값은 재부팅하면 사라지므로 반드시 코드에 넣습니다.
- `WiFi.setAutoReconnect(true)`를 설정합니다. `app_httpd.cpp`의 엔드포인트는 수정하지 않습니다.
- IP는 공유기에서 DHCP 예약으로 고정합니다.
- 전원은 5V 2A 이상을 씁니다. 전원이 약하면 brownout으로 재부팅되는 증상이 나옵니다.
- Pi 세팅: Raspberry Pi OS 64-bit, Docker(`curl -fsSL https://get.docker.com | sh`), `timedatectl`로 NTP 동기화 확인.
- `demo-setup.md`에 적을 것: 모니터와 카메라 사이 거리·각도, 모니터 밝기, 실내 조명, `aec_value`, ESP32·Pi IP, 시연 영상 ID.
- 시연용 현장 영상을 녹화해서 C에게 `sample.mp4`로 전달합니다. 개발 중 테스트와 시연 당일 백업 겸용입니다.

### B — `ml/`

- 학습은 PC나 Colab의 GPU에서 합니다. Pi에서 학습하지 않으며, `ml/`의 의존성은 edge 이미지에 넣지 않습니다.
- 베이스 모델은 `yolo11n.pt`(사전학습)이고, 여기에 fine-tune합니다. `train.py`는 `ultralytics`만 사용합니다.
- `data.yaml`의 `names`는 반드시 `{0: person, 1: helmet, 2: vest}`입니다. 공개 데이터셋(Roboflow Universe의 Construction Site Safety, SH17 등. 라이선스 확인 필요)의 클래스가 다르면 **학습 전에 라벨 파일을 다시 매핑**하고, `NO-Hardhat`처럼 미착용을 뜻하는 클래스는 버립니다. 매핑 코드는 `train.py` 안에 둡니다.
- 머리에 쓴 안전모와 입은 조끼만 라벨링합니다. 손에 든 것이나 바닥에 놓인 것은 라벨링하지 않습니다.
- **도메인 차이 대응:** ESP32로 모니터를 재촬영한 이미지 200~500장을 라벨링(Roboflow나 CVAT)해서 별도 val 세트로 만듭니다. 재촬영 val 점수가 낮으면 일부를 train에도 넣습니다.
- export: `YOLO(best).export(format="ncnn", imgsz=640)`. 결과 폴더 이름을 `ppe-v1.0_ncnn_model/`로 바꾸고 zip으로 묶어 GitHub Release `model-v1.0`에 올립니다.
- Pi FPS는 C의 edge 컨테이너 안에서 측정합니다(같은 환경 기준). 640 입력에서 FPS가 부족하면 `imgsz=320`으로 export한 버전도 함께 올립니다.
- `results.md`에는 릴리스별로 데이터 구성, `imgsz`, 클래스별 mAP50(공개 val, 재촬영 val), Pi FPS를 표로 적습니다.

### C — `edge/`

- 의존성은 `ultralytics`, `ncnn`, `requests`, `opencv-python-headless`입니다. 큐는 표준 라이브러리 `sqlite3`를 씁니다.
- Dockerfile은 `python:3.11-slim`을 베이스로 하고, torch를 CPU 인덱스(`--index-url https://download.pytorch.org/whl/cpu`)로 먼저 설치합니다. 이렇게 하면 같은 Dockerfile로 노트북(amd64)과 Pi(arm64)를 모두 빌드할 수 있습니다.
- `capture.py`: `SOURCE`가 `http`로 시작하면 `requests.get(timeout=3)`으로 JPEG를 받아 디코딩합니다. 그 외에는 `cv2.VideoCapture(파일)`로 읽되, 실제 경과 시간에 맞춰 프레임을 건너뛰어 실시간처럼 동작시키고, 영상이 끝나면 처음부터 다시 재생합니다. 실패 처리는 interface 3장을 따릅니다.
- `compliance.py`는 **입출력과 시간 호출이 없는 순수 로직**으로 만듭니다.
  - `judge(dets, frame_w, frame_h, conf_th, head_ratio) -> persons` (interface 5.1의 `persons` 형식)
  - `Debouncer(confirm_frames)`: 매 프레임 "위반자가 1명 이상인가"를 입력받습니다. 위반이 아닌 상태에서 위반이 `confirm_frames`프레임 연속이면 `True`(새 위반 확정)를 한 번 반환합니다. 위반 상태에서는 정상이 `confirm_frames`프레임 연속이어야 해제됩니다. 추적 기능이 없으므로 위반이 이어지는 동안 다른 사람이 새로 위반해도 이벤트를 다시 보내지 않습니다.
- `main.py` 루프: 캡처 → 추론 → `judge` → 박스 그리기(정상은 초록, 위반은 빨강) → 프레임 PUT(`FRAME_PUSH_INTERVAL_S`마다) → 새 위반이 확정되면 `violation` 이벤트(이미지 포함), `REPORT_INTERVAL_S`마다 `interval` 이벤트를 큐에 넣습니다.
- 시작할 때 `model.names`가 `{0:'person',1:'helmet',2:'vest'}`와 다르면 `sys.exit(1)`로 종료합니다.
- `uploader.py`: 이벤트를 sqlite3의 `outbox(event_id PRIMARY KEY, meta TEXT, image BLOB, created REAL)` 테이블에 **먼저 저장**하고, 별도 스레드가 전송합니다. 응답 코드별 처리(삭제, `failed.jsonl` 기록, 백오프)는 interface 5.1 표를 따릅니다. 프레임 PUT은 큐를 거치지 않고, 실패하면 버립니다.
- `compose.yml`은 **이미 작성되어 있습니다**(`./models:/models:ro`, `./data:/data`, `host.docker.internal`). Dockerfile은 이 파일에 맞춰 작성합니다. 서버가 같은 PC에서 돌고 있으면 `SERVER_URL=http://host.docker.internal`을 씁니다.
- 테스트는 assert 기반 `tests/test_compliance.py` 하나만 둡니다(pytest 없이). `judge`의 정상·안전모 미착용·조끼 미착용·사람 0명 경우와 `Debouncer`의 확정·해제·깜빡임 무시를 확인합니다.

### D — `server/`, `infra/`, `docker-compose.yml`, `.env.example`, `tools/`

- 의존성은 `fastapi`, `uvicorn`, `python-multipart`(Form/File 처리에 필수), `psycopg[binary,pool]`, `boto3`입니다.
- `db.py`: 서버 시작 시 `CREATE TABLE IF NOT EXISTS events(event_id UUID PRIMARY KEY, device_id TEXT, ts TIMESTAMPTZ, trigger TEXT, model_version TEXT, frame_w INT, frame_h INT, person_count INT, no_helmet INT, no_vest INT, persons JSONB, image_key TEXT, received_at TIMESTAMPTZ DEFAULT now())`와 `(device_id, ts DESC)` 인덱스를 만듭니다.
- `POST /api/events`: `meta`를 Pydantic 모델로 `model_validate_json`해서 검증합니다. `trigger`가 `violation`인데 이미지가 없으면 422, 이미지가 1 MB를 넘으면 413을 반환합니다. 저장은 `INSERT ... ON CONFLICT (event_id) DO NOTHING RETURNING event_id`로 하고, 반환된 행이 없으면 중복이므로 200을 반환합니다. 이미지 저장 후 INSERT하고, 중복일 때는 이미지를 저장하지 않습니다.
- 인증: `DEVICE_KEYS`를 파싱해서 헤더 키를 `hmac.compare_digest`로 비교합니다. meta나 경로의 `device_id`와 키가 서로 맞지 않으면 401을 반환합니다.
- 프레임: 메모리 딕셔너리 `{device_id: (bytes, frame_ts, received_at)}`에 보관합니다. **uvicorn worker는 1개**로 고정합니다(메모리 상태를 공유해야 하기 때문).
- `online`은 서버 시각 기준으로 판단합니다(마지막 `received_at`이나 프레임 수신이 15초 이내). Pi 시계가 틀려도 영향받지 않게 하기 위해서입니다.
- `stats`: `date_bin()`으로 구간을 나눕니다. `helmet_rate = SUM(person_count - no_helmet) / NULLIF(SUM(person_count), 0)`로, `interval` 이벤트만 집계합니다.
- `storage.py`: S3 키는 `snapshots/{device_id}/{YYYY}/{MM}/{DD}/{event_id}.jpg`, presigned GET은 3600초로 만듭니다. `S3_BUCKET`이 비어 있으면 `MEDIA_DIR`에 저장하고 `/media`로 정적 서빙합니다. EC2에서는 **IAM 역할(인스턴스 프로파일)**로 S3 권한을 주고, `.env`에 AWS 키를 넣지 않습니다.
- `docker-compose.yml`, `infra/Caddyfile`, `.env.example`은 **이미 작성되어 있습니다**. server는 `0.0.0.0:8000`에서 worker 1개로 실행하고, `DATABASE_URL`과 `MEDIA_DIR`는 compose가 주입합니다. 이 세 파일을 수정할 때는 C와 E의 실행 방법이 깨지지 않는지 확인합니다.
- `setup-ec2.sh`: Ubuntu 24.04에 Docker 설치, 레포 clone, `docker compose up -d`까지 수행합니다. 보안 그룹은 22와 80만 열고, **둘 다 집 공인 IP만** 허용합니다(443은 열지 않음). 집 IP가 바뀌면 보안 그룹을 갱신합니다. AWS Budgets 알람을 설정합니다.
- `tools/fake_edge.py`는 **표준 라이브러리(urllib)만** 사용합니다. 기본 동작은 interface 형식의 무작위 interval 이벤트를 5초마다, 생성한 JPEG 프레임을 1초마다 보내는 것입니다. `--check` 옵션을 주면 interval 1건, violation 1건, 같은 event_id 재전송 1건을 보내 201/201/200 응답과 `/api/latest`의 인원 수를 assert로 확인하고 종료합니다. **E가 이 도구에 의존하므로 서버 뼈대와 함께 가장 먼저 만듭니다.**

### E — `dashboard/`

- `npm create vite@latest dashboard -- --template react`로 생성합니다(JavaScript). 추가 의존성은 `recharts` 하나뿐이고, 라우터, 상태관리, UI 프레임워크는 쓰지 않습니다(CSS 직접 작성).
- `vite.config.js`의 proxy로 `/api`와 `/media`를 `http://localhost:8000`에 연결합니다.
- 컴포넌트: `YouTubePlayer`, `LiveStatus`, `ViolationLog`, `StatsChart`.
- **플레이어를 화면 폭의 60% 이상으로 크게 배치합니다.** ESP32가 이 영역을 촬영하기 때문입니다.
- YouTube: `https://www.youtube.com/iframe_api` 스크립트와 `onYouTubeIframeAPIReady`를 씁니다. 기본 영상은 `VITE_YOUTUBE_VIDEO_ID`이고, URL 입력란으로 바꿀 수 있게 합니다(`watch?v=`, `youtu.be/`, `shorts/` 형식 파싱). 플레이어 `onError`가 101이나 150이면 퍼가기 금지 영상이라는 안내를 표시합니다. 브라우저 자동재생 정책 때문에 재생은 사용자가 클릭해서 시작합니다.
- 폴링: `useEffect` 안의 `setInterval(2000)`으로 `/api/latest`를 가져오고, 언마운트 시 정리합니다. 위반 로그와 통계는 갱신 주기를 10초로 둡니다.
- `LiveStatus`: 인원, 안전모 미착용, 조끼 미착용 수와 `online` 배지(offline이면 회색), 그리고 `<img src={frame_url + "?t=" + frame_ts}>`를 표시합니다.
- `ViolationLog`: `only_violations=true`로 조회해서 썸네일, 시각, 미착용 수를 보여 줍니다. 더 보기 버튼은 `next_before`를 사용합니다.
- `StatsChart`: 1h/24h/7d 버튼을 두고, `helmet_rate`와 `vest_rate`를 선 그래프로 그립니다. `null`은 0이 아니라 끊긴 구간으로 표시합니다.
- `image_url`과 `frame_url`은 받은 값을 그대로 씁니다. URL을 직접 조립하지 않습니다.
- Dockerfile: `node:20-alpine`에서 빌드하고(`VITE_API_BASE`, `VITE_YOUTUBE_VIDEO_ID`는 compose가 build `args`로 넘기므로 `ARG`로 받음), `caddy:2-alpine`에서 `caddy file-server --root /srv --listen :80`으로 서빙합니다.
- 서버가 준비되기 전에는 플레이어와 레이아웃부터 만들고, D의 서버와 `fake_edge.py`가 나오면 그것으로 데이터를 연결합니다. mock 서버는 따로 만들지 않습니다.

## 검증

- 전체: `docker compose up -d --build` → `python3 tools/fake_edge.py --check` → http://localhost 에서 대시보드 확인
- edge: `cd edge && docker compose run --rm edge python tests/test_compliance.py`
- edge에서 server까지: 서버를 띄운 상태에서 edge를 `SOURCE=/data/sample.mp4`로 실행 → 대시보드에 프레임과 이벤트가 표시되는지 확인 → `docker compose stop server` 후 30초 기다렸다가 `start` → 큐에 쌓인 이벤트가 모두 도착하는지 확인
- ESP32: `curl -o a.jpg http://<ESP32_IP>/capture && file a.jpg` (결과에 640x480이 나와야 함)
