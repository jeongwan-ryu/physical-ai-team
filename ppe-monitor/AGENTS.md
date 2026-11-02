# AGENTS.md — ppe-monitor (하루 프로젝트)

LLM 코딩 도구용 지침입니다. **README.md와 docs/interface.md를 먼저 읽으세요.** 데이터 형식은 interface.md만이 기준입니다.

**하루 안에 시연까지 끝내는 프로젝트입니다.** 동작하는 가장 단순한 코드를 씁니다. 요청받지 않은 기능, 추상화, 설정 옵션을 추가하지 않습니다.

## 규칙

- 사용자의 역할(A~E)을 모르면 작업을 시작하기 전에 먼저 묻습니다.
- 사용자가 맡은 파일만 수정합니다(README 역할 표).
- `docs/interface.md`는 수정하지 않습니다. 변경이 필요하면 제안만 하고 멈춥니다.
- interface.md에 없는 필드, 엔드포인트, 환경변수 이름을 만들지 않습니다.
- 아래 "결정된 사항"과 "하지 않는 것"을 뒤집지 않습니다.
- 각 역할 메모에 적힌 것 외의 의존성은 추가하지 않습니다.
- 비밀값(DEVICE_KEY, Wi-Fi 비밀번호)은 코드에 넣지 않습니다. `.env`나 `secrets.h`에만 둡니다.

## 결정된 사항

| 결정 | 이유 |
|---|---|
| ESP32는 Arduino IDE `CameraWebServer` 예제를 사용 | 필요한 `/capture`가 이미 있음 |
| Pi가 ESP32에 `/capture`를 요청해서 가져감(pull). 스트림(:81)은 쓰지 않음 | 처리 속도를 Pi가 결정하고, 버퍼 지연이 없음 |
| 모델은 Hugging Face `best.pt`(YOLOv8n)를 **변환 없이** ultralytics로 로드. Pi에서 `IMGSZ=320`으로도 초당 1장이 안 나올 때만 NCNN으로 변환하고 `MODEL_PATH`만 바꿈(코드 동일). ONNX는 쓰지 않음 | 변환 과정 자체가 위험 요소. 초당 1~2장이면 시연에 충분. Pi(ARM CPU)에서는 NCNN이 ONNX보다 유리 |
| 시연 영상은 E가 골라서 URL을 공유(기준과 후보는 README "시연 영상"). ESP32 없이 개발할 때는 ultralytics 이미지의 예제 사진(`bus.jpg`)을 입력으로 씀 | 영상 파일을 만들거나 주고받을 필요가 없음. YouTube 다운로드는 약관 위반 |
| edge는 ultralytics 공식 이미지를 그대로 쓰고 코드는 볼륨으로 연결. Dockerfile 없음 | torch를 빌드하는 시간이 없음. 코드를 고치면 restart만 하면 됨 |
| server는 컨테이너 1개(FastAPI + 표준 라이브러리 sqlite3)이고, 대시보드도 직접 서빙 | DB 컨테이너, 프록시, 빌드 단계가 없음 |
| 대시보드는 `index.html` + `app.js`만 사용. 프레임워크와 빌드 도구 없음 | 하루 안에 완성 가능 |
| 대시보드는 `/api/latest`를 0.5초 폴링(WebSocket 없이). edge는 EC2 전송을 백그라운드 스레드로 하고 프레임을 0.3초마다 보냄 | 단순함. 실시간 화면이 끊겨 보이지 않게 |
| HTTP만 사용. EC2 보안 그룹에서 80번을 집 IP만 허용 | 시연은 집에서만 함 |

## 하지 않는 것

YouTube 영상 다운로드(`yt-dlp` 등)와 코드에서 YouTube URL 읽기, ONNX 변환, fine-tune, 라벨링, PostgreSQL, Caddy·nginx, S3, 오프라인 큐와 재전송, 중복 방지 ID, 통계 API와 그래프, WebSocket·SSE, React, 사람 추적, YouTube Data API, HTTPS.

## 역할별 구현 메모

### A — `firmware/`, `docs/demo-setup.md` (Pi 보유자)

- **가장 먼저:** Pi에 Docker를 설치하고(`curl -fsSL https://get.docker.com | sh`), `docker pull ultralytics/ultralytics:8.4.198-arm64`를 실행해 둡니다. 약 1 GB라 시간이 걸립니다.
- **이미지가 받아지는 대로 FPS 확인:** README의 "Pi 속도 확인" 명령을 실행합니다(이미지 안의 예제 사진 사용). 두 번째 사진의 inference 시간이 1000ms가 넘으면 팀에 알리고 `IMGSZ=320`, 그다음 NCNN 순서로 대응합니다.
- **펌웨어는 작성되어 있습니다**(`firmware/esp32cam/CameraWebServer/`). 보드는 **XIAO ESP32S3 Sense**이고, 업로드 방법과 Tools 설정(Board `XIAO_ESP32S3`, PSRAM `OPI PSRAM`)은 `firmware/esp32cam/README.md`를 따릅니다.
  - `secrets.h.example`을 `secrets.h`로 복사해 Wi-Fi 정보를 넣습니다. `secrets.h`는 커밋하지 않습니다.
  - 노출은 자동으로 시작합니다. 화면이 너무 밝거나 어두울 때만 `.ino` 상단의 `FIX_EXPOSURE`를 1로 바꾸고 `AEC_VALUE`를 조정합니다.
  - 펌웨어를 수정할 때는 `CameraWebServer.ino`만 고치고, `app_httpd.cpp`(엔드포인트)는 건드리지 않습니다.
- 업로드 후 시리얼 모니터의 `edge SOURCE=http://<IP>/capture` 줄을 팀에 공유하고, 공유기에서 IP를 고정합니다.
- 확인: `curl -o a.jpg http://<ESP32_IP>/capture && file a.jpg`의 결과에 640x480이 나와야 합니다.
- 오후: 카메라가 대시보드 플레이어 영역을 정면으로 꽉 차게 찍도록 거치합니다. Pi에서 `edge/.env`를 `EDGE_BASE=...-arm64`, `SOURCE=http://<ESP32_IP>/capture`로 설정하고 실행합니다.
- `docs/demo-setup.md`에 IP, 거치 방법, 노출값을 적습니다.

### B — `edge/app/compliance.py`, `edge/tests/test_compliance.py`

- 의존성이 없는 **순수 함수**로 만듭니다(numpy, cv2, ultralytics를 import하지 않음). C가 import해서 씁니다.
- **함수 형태는 아래와 같이 고정합니다(C와의 약속).**
  ```python
  def judge(dets, conf_th, head_ratio):
      """dets: [(name, conf, [x1, y1, x2, y2]), ...]  # name은 모델 클래스 이름 그대로
      반환: interface 5.1의 persons 리스트 [{"bbox", "conf", "helmet", "vest"}, ...]"""

  class Debouncer:
      def __init__(self, confirm_frames): ...
      def update(self, violating: bool) -> bool:
          """위반이 새로 확정된 프레임에서만 True를 반환"""
  ```
- 판정 규칙은 interface 5.3을 따릅니다. `Person`, `Hardhat`, `Safety Vest`만 사용하고 나머지 클래스는 무시합니다. bbox는 int로 반환합니다.
- 오전에는 테스트(가짜 박스 데이터)로 로직을 완성합니다. 영상은 필요 없습니다.
- 기준값(`CONF_TH`, `HEAD_RATIO`)은 **오후 통합 때 실제 ESP32 화면**을 대시보드의 실시간 프레임으로 보면서 정하고, `edge/.env` 값을 팀에 공유합니다. 모니터를 다시 찍은 화면은 원본 영상과 달라서 이렇게 해야 정확합니다.
  - 안전모를 쓴 사람이 자꾸 위반으로 나오면, `NO-Hardhat`/`NO-Safety Vest` 박스가 있을 때만 `false`로 판정하는 방식도 시험해 봅니다. 반환 형식은 바꾸지 않습니다.
- 테스트(`tests/test_compliance.py`)는 assert 기반으로 하나만 만듭니다(pytest 없이 `if __name__ == "__main__"`). 확인할 경우: 착용, 안전모 없음, 조끼 없음, 사람 0명, conf 미달, Debouncer의 확정·유지·해제·깜빡임 무시.
- 실행: `cd edge && docker compose run --rm edge python tests/test_compliance.py`

### C — `edge/app/main.py`, `edge/compose.yml`, `edge/.env.example`

- 의존성은 ultralytics 이미지에 이미 있는 `ultralytics`, `cv2`, `numpy`, `requests`만 씁니다. Dockerfile은 만들지 않습니다(compose가 이미 작성되어 있음).
- 시작할 때:
  - 환경변수를 읽습니다(interface 7장).
  - `model = YOLO(MODEL_PATH)`로 모델을 로드합니다. `MODEL_PATH`는 `.pt` 파일이거나 NCNN 폴더일 수 있으며, 코드는 둘을 구분하지 않습니다.
  - `model.names`에 `Person`, `Hardhat`, `Safety Vest`가 하나라도 없으면 `sys.exit(1)`로 종료합니다.
- 캡처:
  - `SOURCE`가 `http`로 시작하면 `requests.get(SOURCE, timeout=3)` 후 `cv2.imdecode`로 읽습니다. 실패하면 1초 쉬고 다시 시도합니다.
  - 그 외에는 이미지 파일 경로로 보고 매 루프 `cv2.imread(SOURCE)`로 읽습니다(기본값 `/ultralytics/ultralytics/assets/bus.jpg`). 같은 사진을 반복 처리하면 되고, 영상 파일은 지원하지 않습니다.
- 루프:
  1. 캡처
  2. `model(frame, imgsz=IMGSZ, verbose=False)[0]`의 박스를 `(model.names[cls], conf, xyxy)` 리스트로 변환
  3. `compliance.judge` 호출
  4. 박스 그리기: 정상은 초록, 위반은 빨강. `cv2.rectangle`과 `putText`를 쓰고, 폰트 다운로드가 필요한 `result.plot()`은 쓰지 않습니다.
  5. `FRAME_PUSH_INTERVAL_S`마다 `PUT /api/frame`
  6. `debouncer.update(위반자 ≥ 1)`이 True이면 `violation` 이벤트를 이미지와 함께 전송
  7. `REPORT_INTERVAL_S`마다 `interval` 이벤트 전송
- 이벤트 전송: 먼저 `meta`를 `/data/events.jsonl`에 한 줄 추가한 뒤 `requests.post(timeout=5)`로 보냅니다. 실패하면 로그만 남기고 계속 진행합니다. 프레임 PUT도 실패하면 무시합니다.
- `ts`는 `datetime.now(timezone.utc)`를 밀리초까지 표시하고 `Z`로 끝나게 만듭니다.
- 매 루프마다 처리 시간(FPS)을 로그에 출력합니다. Pi에서 속도를 확인하기 위해서입니다.
- B의 `compliance.py`가 완성되기 전에는 interface 5.3대로 임시 판정을 `main.py` 안에 두고, B의 코드가 오면 바꿉니다. **`compliance.py`는 직접 수정하지 않습니다.**

### D — `server/`, `docker-compose.yml`, `.env.example`

- 의존성은 `fastapi`, `uvicorn`, `python-multipart`(Form/File 처리에 필수)와 표준 라이브러리 `sqlite3`뿐입니다. Dockerfile과 compose는 이미 작성되어 있습니다(포트 8000, `/data` 볼륨, `/app/static`에 대시보드 연결).
- `server/app/main.py` 파일 하나에 모두 작성합니다.
- DB: 시작할 때 `/data/media`를 만들고, `CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, ts TEXT, trigger TEXT, person_count INT, no_helmet INT, no_vest INT, persons TEXT, image TEXT, received_at REAL)`를 실행합니다. 요청마다 `sqlite3.connect("/data/ppe.db")`로 새로 연결합니다(스레드 문제를 피하기 위해).
- `POST /api/events`:
  - `meta: str = Form()`, `image: UploadFile | None = File(None)`으로 받습니다.
  - meta는 Pydantic 모델의 `model_validate_json`으로 검증하고, 실패하면 422를 반환합니다.
  - 키가 틀리면 401, `violation`인데 이미지가 없으면 422, 이미지가 1 MB를 넘으면 413을 반환합니다.
  - INSERT 후 이미지를 `/data/media/<id>.jpg`로 저장하고, 201로 응답합니다.
  - 키 비교는 `hmac.compare_digest`로 합니다.
- `PUT /api/frame`: `await request.body()`를 전역 변수에 `(bytes, 받은 시각)`으로 보관하고 204로 응답합니다. **uvicorn worker는 1개**입니다(Dockerfile 기본값).
- `GET /api/latest`, `GET /api/events`, `GET /api/frame`: interface 6장대로 구현합니다. `online`은 server 시각 기준(`received_at`, 프레임 수신 시각)으로 판단합니다.
- 정적 파일: `/media`는 `StaticFiles(directory="/data/media")`로 연결합니다. **모든 API 라우트를 정의한 뒤 마지막에** `app.mount("/", StaticFiles(directory="/app/static", html=True))`를 둡니다.
- 확인: `docker compose up -d --build` 후 interface 8장의 curl을 실행합니다.
- 배포: README의 "EC2 배포"를 따릅니다.

### E — `dashboard/index.html`, `dashboard/app.js`

- **1:30 중간 점검까지:** README "시연 영상"의 기준대로 시연 영상을 골라 팀 채널에 URL을 공유합니다. A가 오후에 이 영상으로 카메라 거치와 노출을 맞춥니다. 후보 영상을 그대로 써도 됩니다.
- 프레임워크, 빌드 도구, 외부 라이브러리 없이 `index.html`과 `app.js`, 그리고 `index.html` 안의 `<style>`만 씁니다. server가 `/`에서 서빙하므로 API는 `/api/...` 상대 경로로 호출합니다.
- 화면 배치: 왼쪽에 **YouTube 플레이어(화면 폭의 60% 이상)**를 둡니다. ESP32가 이 영역을 촬영합니다. 오른쪽에는 실시간 프레임(`<img src="/api/frame?t=...">`), 인원·안전모 미착용·조끼 미착용 수, online/offline 배지, 위반 목록(사진, 시각, 미착용 수)을 둡니다.
- YouTube:
  - `<script src="https://www.youtube.com/iframe_api">`와 `onYouTubeIframeAPIReady`를 씁니다.
  - `app.js` 상단에 `const VIDEOS = [{label: "...", id: "<선정한 영상 ID>"}, ...]`를 두고, 버튼으로 `loadVideoById` 전환합니다. 기본은 첫 번째 영상입니다.
  - 다른 영상을 시험할 수 있도록 URL 입력란도 둡니다(`watch?v=`, `youtu.be/`, `shorts/` 형식 파싱).
  - `onError`가 101이나 150이면 "퍼가기 금지 영상" 안내를 표시합니다.
  - `playerVars`에 `mute: 1`을 넣고(자동재생 정책), 반복 재생(`loop: 1`, `playlist: <id>`)을 설정합니다.
- 폴링: 0.5초마다 `/api/latest`를 가져와 갱신하고, 위반 목록(`/api/events?only_violations=true&limit=20`)은 5초마다 갱신합니다. `frame_ts`가 바뀔 때만 이미지 `src`를 교체합니다. `online`이 false이거나 fetch가 실패하면 offline 배지를 표시합니다.
- server가 준비되기 전에는 `python3 -m http.server -d dashboard 8090`으로 열고, 화면 갱신 함수를 `window.render(latest)`로 노출해서 브라우저 콘솔에서 interface 6.1의 예시 JSON으로 테스트합니다. mock 서버는 만들지 않습니다.

## 검증

- server: `docker compose up -d --build` → interface 8장 curl → http://localhost
- 판정 로직: `cd edge && docker compose run --rm edge python tests/test_compliance.py`
- edge에서 server까지: server를 실행한 상태에서 `cd edge && docker compose up` (기본 `SOURCE` = 예제 사진) → 대시보드에 프레임, 인원 수, 위반 목록이 나타나는지 확인
- ESP32: `curl -o a.jpg http://<ESP32_IP>/capture && file a.jpg`
