# Zero-Touch Media Control

얼굴이 보이면 유튜브 재생, 안 보이면 일시정지.

```
[ESP32-S3] 카메라 → 얼굴검출 ──MQTT {"score":0.91}──▶ [mosquitto] ──▶ [bridge] ──SSE──▶ 브라우저(YouTube IFrame)
 (Docker 밖, Wi-Fi)                                    └──────── docker compose ────────┘
```

## 실행

```sh
docker compose up -d --build      # http://localhost:8080
./tools/fake_esp32.sh             # ESP32 없이 테스트
```

펌웨어 (ESP-IDF v5.3+):

```sh
cd firmware
idf.py menuconfig                 # Zero-Touch Media 메뉴에서 Wi-Fi, MQTT_URI(노트북 IP) 입력
idf.py build flash monitor
```

## 역할

| | 담당 | 파일 |
|---|---|---|
| A | 펌웨어-네트워크, 하드웨어(전원·거치), 통합 테스트 | `firmware/main/{main.c,net.c,Kconfig.projbuild}` |
| B | 펌웨어-모델 | `firmware/main/detect.cpp`, `firmware/sdkconfig.defaults`, `idf_component.yml` |
| C | bridge, 인프라 | `bridge/`, `mosquitto/`, `docker-compose.yml`, `tools/` |
| D | 프론트 | `web/` |

브랜치: `feat/ztmc-fw-net`, `feat/ztmc-fw-detect`, `feat/ztmc-bridge`, `feat/ztmc-web` (main에서 분기, PR로 merge)

## 인터페이스 계약

> 이 섹션, `firmware/main/common.h`, `docker-compose.yml` 변경은 4명 전원 승인 후 merge.

### 1. ESP32 → mosquitto (MQTT)

| 항목 | 값 |
|---|---|
| 브로커 | `mqtt://<노트북IP>:1883`, 인증 없음 |
| 토픽 | `ztmc/cam1/face`, QoS 0, retain 없음 |
| 페이로드 | `{"score":0.91}` — 가장 높은 검출 점수 0~1, 얼굴 없으면 `0` |
| 주기 | 검출마다 발행, 최대 5Hz (heartbeat 겸용) |

### 2. bridge → 브라우저 (SSE)

```
GET /events    Content-Type: text/event-stream
data: {"state":"present"}
```

- `state`: `present` | `absent` | `offline`
- 접속 즉시 현재 상태 1회, 이후 바뀔 때만 전송
- 프론트: `present` → `play()`, `absent` → `pause()`, `offline` → `pause()` + "카메라 연결 끊김" 배너

### 3. bridge 상태머신

```
초기 = offline
score >= SCORE_TH 가 PRESENT_MS 동안 연속   → present
score <  SCORE_TH 가 ABSENT_MS 동안 연속    → absent
메시지가 STALE_MS 동안 없음                  → offline
```

| 환경변수 | 기본값 |
|---|---|
| `SCORE_TH` | 0.5 |
| `PRESENT_MS` | 300 |
| `ABSENT_MS` | 1500 |
| `STALE_MS` | 2000 |

바꾸려면 이 폴더에 `.env` 작성 (git 제외됨).

### 4. 펌웨어 내부 (A ↔ B)

`firmware/main/common.h` 참조. 길이 1 큐에 `float score`를 `xQueueOverwrite`.

## 규칙

- 버전 고정: ESP-IDF v5.3+ (팀 동일), `eclipse-mosquitto:2`, `python:3.12-slim`, `paho-mqtt==2.1.0`
- `firmware/sdkconfig`는 커밋 금지 (Wi-Fi 비밀번호 포함). 공유 설정은 `sdkconfig.defaults`에.
- 공용 Wi-Fi는 기기 간 통신이 막힐 수 있음 → 휴대폰 핫스팟/공유기 사용, 노트북 방화벽 1883 허용.
- 시연 영상은 퍼가기 허용 여부 미리 확인 (IFrame 오류 101/150).

## 통합 테스트 (시연 대본)

1. `docker compose up` → 브라우저 접속 → URL 입력 → 시작 클릭 → `offline`
2. ESP32 전원 on → `absent`
3. 카메라 앞에 앉음 → 0.3초 내 재생
4. 자리 비움 → 1.5초 후 정지
5. 복귀 → 이어서 재생
6. ESP32 전원 off → 2초 내 정지 + 배너
