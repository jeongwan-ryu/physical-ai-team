# AGENTS.md — zero-touch-media

LLM 코딩 도구용 지침. **README.md를 먼저 읽을 것.** README의 "인터페이스 계약"이 유일한 기준이다.

## 규칙

- 사용자의 역할(A~D)을 모르면 작업 전에 먼저 묻는다.
- 사용자가 맡은 역할의 폴더/파일만 수정한다 (README 역할 표).
- 계약은 수정하지 않는다: README 인터페이스 계약 섹션, `firmware/main/common.h`. 변경이 필요하면 제안만 하고 멈춘다 (4명 전원 승인 사항).
- 아래 "결정된 사항"을 뒤집지 않는다. 더 나은 방법이 있으면 제안만 한다.
- 의존성 추가 금지. 필요하면 제안만 한다.

## 결정된 사항

| 결정 | 이유 |
|---|---|
| ESP32 → 서버는 MQTT. 웹소켓 쓰지 않음 | `mosquitto_pub`로 하드웨어 없이 mock, `mosquitto_sub`로 디버깅 |
| 서버 → 브라우저는 SSE. 웹소켓·폴링 쓰지 않음 | 단방향이면 충분, `EventSource` 자동 재연결 |
| nginx 없음. bridge가 `/web` 정적 서빙 | 단일 사용자 시연, SSE 버퍼링 함정 제거 |
| bridge는 표준 라이브러리 `http.server` + `paho-mqtt`만. FastAPI/Flask 금지 | 스레드/asyncio 혼용 회피, 의존성 1개 |
| 얼굴검출은 ESP32-S3에서 `espressif/human_face_detect`(사전학습). 서버에 OpenCV 없음, Edge Impulse·자체 학습 없음 | 요구사항은 "얼굴 유무"뿐, 기성 모델로 충분 |
| 얼굴 유무만 판단. 시선·머리 방향 판단 없음 | 요구사항 |

## 역할별 구현 메모

### A — `firmware/main/{main.c,net.c,Kconfig.projbuild}`

- ESP-IDF v5.3+, target `esp32s3`.
- `esp_wifi` STA 모드, 끊기면 재연결.
- `esp-mqtt`(`mqtt_client.h`): broker `CONFIG_MQTT_URI`, topic `"ztmc/" CONFIG_CAM_ID "/face"`, QoS 0, retain 0.
- 발행 확인용으로 bridge 없이 브로커만 띄울 수 있다: `docker compose up -d mosquitto`.
- `xQueueReceive`로 score를 받아 최대 5Hz로 `{"score":0.91}` 형식(소수 2자리) 발행. 미연결 중에는 버린다.
- 검출이 준비되기 전에는 `Kconfig.projbuild`에 `FAKE_DETECT` bool 옵션을 추가하고, 켜져 있으면 `main.c`가 `detect_start` 대신 가짜 score(0.9/0 1초 간격 토글)를 큐에 넣는 태스크를 시작한다. B의 `detect.cpp`는 건드리지 않는다.

### B — `firmware/main/{detect.cpp,idf_component.yml,CMakeLists.txt}`, `firmware/{sdkconfig.defaults,CMakeLists.txt}`

- 보드: ESP32-S3 + 카메라 + PSRAM. 카메라 핀맵은 보드 문서 기준.
- `espressif/esp32-camera`로 프레임 취득 → `HumanFaceDetect` (`human_face_detect.hpp`)의 `detect->run(img)`.
- 카메라는 `PIXFORMAT_RGB565`, `FRAMESIZE_QVGA` 권장 (JPEG는 디코딩 비용이 추가됨). 프레임 버퍼는 PSRAM.
- `sdkconfig.defaults`에 `CONFIG_COMPILER_OPTIMIZATION_PERF=y` (공식 지연시간 수치의 기준 설정).
- 기본 파티션(앱 1MB)으로는 ESP-DL+모델+Wi-Fi+MQTT가 넘칠 수 있다. 보드 플래시 크기(`CONFIG_ESPTOOLPY_FLASHSIZE_*`)와 `CONFIG_PARTITION_TABLE_SINGLE_APP_LARGE=y`(또는 커스텀 `partitions.csv`)를 `sdkconfig.defaults`에 설정한다. A의 빌드도 이 설정을 따른다.
- 결과 중 최고 score, 없으면 `0.0f`를 `xQueueOverwrite`. `detect_start`는 태스크를 만들고 바로 반환한다.
- 기본 모델 MSR+MNP(S3 약 40ms). 정확도 부족 시 `ESPDET_PICO_224_224_FACE`(약 130ms).
- 첫 빌드 성공 후 `idf_component.yml` 버전 고정(`human_face_detect: "~0.5.2"`), 생성된 `dependencies.lock` 커밋.
- `detect.cpp`는 C++이고 `main.c`는 C다. `common.h`의 `extern "C"`를 유지한다.

### C — `bridge/`, `mosquitto/`, `tools/`

- paho-mqtt **2.x**: `mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)`. 1.x 예제의 콜백 시그니처는 동작하지 않는다.
- mosquitto보다 먼저 떠도 죽지 않게 `connect_async()` + `loop_start()` (자동 재연결). 구독은 `on_connect`에서 한다 (재연결 시 재구독).
- `presence.py`: I/O·시간 호출 없는 순수 로직. 현재 시각(ms)을 인자로 받아 상태를 반환한다 → 테스트 가능.
- `app.py`: MQTT 콜백 스레드 + 100ms tick(offline 판정) + `ThreadingHTTPServer(("0.0.0.0", 8080), ...)` (`localhost`로 바인딩하면 포트 매핑이 동작하지 않음). 핸들러는 `SimpleHTTPRequestHandler`를 상속해 `/events`만 SSE로 처리하고, 나머지는 `directory="/web"`으로 정적 서빙 (`functools.partial`로 전달).
- SSE: `Content-Type: text/event-stream`, `Cache-Control: no-cache`. 접속 즉시 현재 상태, 이후 변화 시에만. `BrokenPipeError`/`ConnectionResetError`가 나면 해당 클라이언트 루프를 종료한다.
- 설정은 환경변수(`SCORE_TH`, `PRESENT_MS`, `ABSENT_MS`, `STALE_MS`, `MQTT_HOST`). 기본값은 compose에 있다.
- 테스트는 assert 기반 `test_presence.py` 하나 (pytest 없음).

### D — `web/`

- 프레임워크·빌드 도구 없음. `index.html` + `app.js`만.
- YouTube IFrame API: `<script src="https://www.youtube.com/iframe_api">`, `onYouTubeIframeAPIReady`.
- URL 입력 → videoId 파싱 (`watch?v=`, `youtu.be/`, `shorts/`).
- 화면: URL 입력, "시작" 버튼, 플레이어, 상태 배지(`present`/`absent`/`offline` 텍스트+색), 연결 끊김 배너.
- `EventSource`는 페이지 로드 시 연결(배지·배너 즉시 갱신). 플레이어는 "시작" 클릭 시 생성하고, 그때부터 재생을 제어한다 (브라우저 자동재생 정책).
- `new EventSource("/events")` → `present`: `playVideo()`, `absent`: `pauseVideo()`, `offline`: `pauseVideo()` + "카메라 연결 끊김" 배너.
- `onerror`(bridge 연결 끊김)도 `offline`으로 취급한다. 재연결은 `EventSource`가 자동으로 하고, 재접속 즉시 현재 상태가 온다.
- 플레이어 `onReady` 전에 받은 상태는 저장해 두었다가 ready 후 적용한다.
- 플레이어 `onError` 101/150(퍼가기 금지 영상)이면 안내 메시지를 표시한다.
- bridge가 완성되기 전에는 `python3 -m http.server -d web 8090`으로 서빙하고 (8080은 compose가 사용), 상태 처리 함수를 `window.setState`로 노출해 브라우저 콘솔에서 `setState("present")` 등으로 테스트한다 (mock 서버를 만들지 않는다). 이때 `/events`는 404라 `EventSource`가 offline 후 재연결하지 않는데, 정상이다 (bridge는 항상 200).

## 검증

- 전체: `docker compose up -d --build` → `./tools/fake_esp32.sh` → 브라우저에서 재생 → 정지 → offline 확인.
- bridge: `docker compose run --rm bridge python test_presence.py`
- 펌웨어: `idf.py build`, 발행 확인은 `docker compose exec mosquitto mosquitto_sub -t 'ztmc/#' -v`
