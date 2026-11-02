# 팀 간 데이터 인터페이스 명세 (하루 버전)

> 버전: v1.1 (2026-11-02) · 하루 프로젝트용으로 단순화한 버전입니다.

구성요소끼리 **주고받는 데이터 형식**을 정의합니다. 내부 구현은 담당자가 자유롭게 정하되, 이 문서에 적힌 경계는 반드시 지킵니다.

---

## 0. 규칙 (사람과 LLM 모두 따를 것)

1. **이 문서가 기준입니다.** 코드와 다르면 문서가 맞고, 코드를 고칩니다.
2. 필드 이름, 타입, 경로, 환경변수 이름은 **이 문서의 철자 그대로** 씁니다. 새 이름을 만들지 않습니다.
3. 여기에 없는 필드나 엔드포인트가 필요하면 **만들지 말고 팀에 먼저 말합니다.**
4. 받는 쪽은 모르는 필드를 무시합니다.

---

## 1. 전체 구조

```
[모니터: 대시보드 + YouTube] ──화면 촬영──▶ [ESP32-CAM]
                                              │ I1. GET /capture → JPEG
                                              ▼
              I2. best.pt ──────────▶ [Raspberry Pi: edge 컨테이너]
                                              │ I3. POST /api/events, PUT /api/frame
                                              ▼
                                  [EC2: server 컨테이너 1개]
                                   FastAPI + SQLite + 대시보드 정적 파일
                                              │ I4. GET /api/latest, /api/events, /api/frame
                                              ▼
                                       [브라우저: 대시보드]
```

| ID | 연결 | 형태 | 담당 |
|---|---|---|---|
| I1 | ESP32-CAM → edge | HTTP. edge가 요청해서 가져감 | A ↔ C |
| I2 | 모델 → edge | `best.pt` 파일, 클래스 이름 | B ↔ C |
| I3 | edge → server | HTTP REST | C ↔ D |
| I4 | server → 대시보드 | HTTP REST (같은 서버에서 서빙) | D ↔ E |

- 기기는 **Pi 1대**입니다(`device_id`: `pi-01`).
- 통신은 HTTP를 쓰고 HTTPS는 쓰지 않습니다. 접근 제한은 EC2 보안 그룹에서 80번 포트를 집 IP만 허용하는 것으로 합니다.

---

## 2. 공통 규약

| 항목 | 규칙 |
|---|---|
| JSON 키 | `snake_case` |
| 시각 | ISO 8601 UTC, `Z`로 끝남. 예: `2026-11-02T10:15:30.120Z` (edge가 프레임을 캡처한 시각) |
| bbox | `[x1, y1, x2, y2]` 정수 픽셀, 원본 프레임 기준, 원점은 좌상단 |
| conf | 0.0 ~ 1.0 float |
| 이미지 | JPEG, 1장당 1 MB 이하 |
| 기기 인증 | 쓰기 요청에 헤더 `X-Device-Key: <DEVICE_KEY>` |
| 에러 응답 | FastAPI 기본 형식인 `{"detail": "..."}` |

---

## 3. I1. ESP32-CAM → edge

```
GET http://<ESP32_IP>/capture
→ 200, Content-Type: image/jpeg, 본문: JPEG
```

- Arduino `CameraWebServer` 예제에 있는 기능 그대로입니다(포트 80).
- 해상도는 VGA 640×480으로 펌웨어에서 고정합니다.
- edge의 요청 타임아웃은 3초이고, 실패하면 1초 뒤에 다시 시도합니다.
- **개발할 때:** edge의 `SOURCE`가 `http`로 시작하지 않으면 이미지 파일 경로로 보고, 매 루프 같은 사진을 읽습니다. 기본값은 ultralytics 이미지에 들어 있는 예제 사진 `/ultralytics/ultralytics/assets/bus.jpg`입니다.

---

## 4. I2. 모델 → edge

- 파일: Hugging Face `Hansung-Cho/yolov8-ppe-detection`의 `best.pt`(YOLOv8n, 입력 640, MIT 라이선스). **기본은 변환하지 않고 그대로 씁니다.** Pi에서 너무 느릴 때만 NCNN으로 변환한 폴더(`/models/best_ncnn_model`)를 `MODEL_PATH`로 지정합니다. 이때 코드는 바뀌지 않습니다.
- 위치: `edge/models/best.pt`. 용량이 커서 Git에는 올리지 않고, 각자 아래 명령으로 내려받습니다.
  ```bash
  curl -L -o edge/models/best.pt https://huggingface.co/Hansung-Cho/yolov8-ppe-detection/resolve/main/best.pt
  ```
- 모델 클래스는 10개이고, **edge는 아래 3개만 이름으로 찾아서** 씁니다. index 숫자는 코드에 직접 쓰지 않습니다.

| 모델 클래스 이름 | edge 내부 의미 |
|---|---|
| `Person` | 사람 |
| `Hardhat` | 안전모 |
| `Safety Vest` | 조끼 |

- 나머지 클래스(`Mask`, `NO-Hardhat`, `NO-Mask`, `NO-Safety Vest`, `Safety Cone`, `machinery`, `vehicle`)는 무시합니다.
- edge는 시작할 때 `model.names`에 위 3개 이름이 모두 있는지 확인하고, 하나라도 없으면 종료합니다.

---

## 5. I3. edge → server

### 5.1 `POST /api/events`: 판정 기록

**보내는 시점**
- `trigger: "interval"`: `REPORT_INTERVAL_S`(기본 5초)마다 현재 상태를 보냅니다. 사람이 0명이어도 보냅니다. 이미지는 없습니다.
- `trigger: "violation"`: 위반이 **새로 확정되는 순간** 한 번 보냅니다. 박스를 그린 JPEG를 함께 보냅니다.

**요청:** `multipart/form-data`, 헤더 `X-Device-Key`

| 파트 | 필수 | 내용 |
|---|---|---|
| `meta` | ✅ | 아래 JSON을 문자열로 담음 |
| `image` | `violation`일 때만 | 박스를 그린 JPEG |

```json
{
  "device_id": "pi-01",
  "ts": "2026-11-02T10:15:30.120Z",
  "trigger": "violation",
  "frame_w": 640,
  "frame_h": 480,
  "persons": [
    {"bbox": [102, 40, 230, 410], "conf": 0.91, "helmet": true,  "vest": true},
    {"bbox": [300, 55, 420, 400], "conf": 0.87, "helmet": false, "vest": true}
  ]
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `device_id` | string | `pi-01` |
| `ts` | string | 캡처 시각 (UTC) |
| `trigger` | `"interval"` \| `"violation"` | |
| `frame_w`, `frame_h` | int | bbox의 기준이 되는 프레임 크기 |
| `persons` | array | 검출된 **모든** 사람. 0명이면 `[]` |
| `persons[].bbox` | int[4] | |
| `persons[].conf` | float | Person 검출 신뢰도 |
| `persons[].helmet` | bool | 안전모를 썼다고 판정되면 `true` |
| `persons[].vest` | bool | 조끼를 입었다고 판정되면 `true` |

- **위반자**는 `helmet == false` 또는 `vest == false`인 사람입니다.
- 인원 수와 미착용 수는 **server가 `persons`로 계산**합니다.

**응답**

| 코드 | 의미 |
|---|---|
| `201` | 저장 완료. 본문: `{"id": 12, "image_url": "/media/12.jpg"}` (이미지가 없으면 `null`) |
| `401` | `X-Device-Key` 오류 |
| `413` | 이미지가 1 MB 초과 |
| `422` | `meta` 형식 오류, 또는 `violation`인데 이미지가 없음 |

**edge의 실패 처리:** 보내기 전에 같은 `meta`를 Pi의 `/data/events.jsonl`에 한 줄씩 추가합니다. 전송에 실패하면 로그만 남기고 다음 루프로 넘어갑니다(재전송하지 않음).

### 5.2 `PUT /api/frame`: 실시간 화면

```
PUT /api/frame
X-Device-Key: <DEVICE_KEY>
Content-Type: image/jpeg
본문: 박스를 그린 JPEG
→ 204
```

- `FRAME_PUSH_INTERVAL_S`(기본 1초)마다 보냅니다. 실패해도 무시합니다.
- server는 **최신 1장만 메모리에** 보관하고, 따로 기록하지 않습니다.

### 5.3 착용 판정 규칙 (edge 내부. 의미를 공유하기 위해 적어 둠)

- `helmet`: `conf ≥ CONF_TH`인 `Hardhat` 박스의 중심이 사람 박스의 **위쪽 `HEAD_RATIO`(기본 0.3) 영역** 안에 있으면 `true`
- `vest`: `conf ≥ CONF_TH`인 `Safety Vest` 박스의 중심이 사람 박스의 **세로 0.2~0.7 영역** 안에 있으면 `true`
- 위반 확정: "위반자가 1명 이상"인 프레임이 `CONFIRM_FRAMES`(기본 3)번 연속으로 나오면 확정합니다. 해제도 정상 프레임이 같은 횟수만큼 연속으로 나와야 합니다. 위반 상태가 이어지는 동안에는 `violation`을 다시 보내지 않습니다.
- 사람 추적(tracking)은 하지 않습니다.

---

## 6. I4. server → 대시보드

- 대시보드 파일(`dashboard/`)은 server가 `/`에서 직접 서빙합니다. 출처가 같으므로 CORS 설정은 필요 없습니다.
- 대시보드는 **2초마다 폴링**합니다.

### 6.1 `GET /api/latest`

```json
{
  "online": true,
  "ts": "2026-11-02T10:15:30.120Z",
  "person_count": 2,
  "no_helmet": 1,
  "no_vest": 0,
  "persons": [{"bbox": [102, 40, 230, 410], "conf": 0.91, "helmet": true, "vest": true}],
  "frame_ts": "2026-11-02T10:15:31.002Z"
}
```

- 가장 최근 이벤트를 기준으로 합니다.
- `online`: server 시각 기준으로 최근 15초 안에 이벤트나 프레임을 받았으면 `true`입니다.
- `frame_ts`: server가 마지막 프레임을 받은 시각입니다. 프레임이 없으면 `null`입니다.
- 이벤트가 하나도 없으면 `{"online": false, "ts": null, "person_count": 0, "no_helmet": 0, "no_vest": 0, "persons": [], "frame_ts": null}`을 반환합니다(404가 아님).

### 6.2 `GET /api/events?only_violations=true&limit=50`

```json
{
  "items": [
    {"id": 12, "ts": "2026-11-02T10:15:30.120Z", "trigger": "violation",
     "person_count": 2, "no_helmet": 1, "no_vest": 0, "image_url": "/media/12.jpg"}
  ]
}
```

- `only_violations`의 기본값은 `false`입니다. `true`이면 `trigger == "violation"`인 이벤트만 반환합니다.
- `limit`의 기본값은 50이고, 최대 200입니다.
- 최신 이벤트가 먼저 오도록 정렬합니다.

### 6.3 `GET /api/frame`

- 마지막으로 받은 프레임을 `200 image/jpeg`로 반환합니다. 아직 받은 프레임이 없으면 `404`입니다.
- 브라우저 캐시를 피하려면 `<img src="/api/frame?t=<frame_ts>">`처럼 요청합니다.

### 6.4 `GET /media/<id>.jpg`

- 위반 사진입니다. 응답의 `image_url` 값을 그대로 `<img src>`에 넣어 씁니다.

---

## 7. 환경변수 (이름 고정)

**server** (루트 `.env`)

| 이름 | 예시 | 설명 |
|---|---|---|
| `DEVICE_KEY` | `change-me` | edge와 같은 값 |

server의 데이터 경로는 `/data`로 고정입니다. DB는 `/data/ppe.db`, 위반 사진은 `/data/media/`에 저장됩니다.

**edge** (`edge/.env`)

| 이름 | 예시 | 설명 |
|---|---|---|
| `EDGE_BASE` | `ultralytics/ultralytics:8.4.198-cpu` | Pi에서는 `8.4.198-arm64` |
| `DEVICE_ID` | `pi-01` | |
| `DEVICE_KEY` | `change-me` | |
| `SERVER_URL` | `http://host.docker.internal` | EC2를 쓸 때는 `http://<EC2 IP>`. 끝에 `/` 없음 |
| `SOURCE` | `/ultralytics/ultralytics/assets/bus.jpg` | 개발용 예제 사진. ESP32를 쓸 때는 `http://<ESP32_IP>/capture` |
| `MODEL_PATH` | `/models/best.pt` | NCNN으로 변환했다면 `/models/best_ncnn_model` |
| `IMGSZ` | `640` | Pi에서 느리면 `320` |
| `CONF_TH` | `0.4` | 보정값 |
| `HEAD_RATIO` | `0.3` | 보정값 |
| `CONFIRM_FRAMES` | `3` | 보정값 |
| `REPORT_INTERVAL_S` | `5` | |
| `FRAME_PUSH_INTERVAL_S` | `1` | |

---

## 8. 빠른 확인 (curl)

```bash
S=http://localhost; K=change-me
curl -X POST $S/api/events -H "X-Device-Key: $K" \
  -F 'meta={"device_id":"pi-01","ts":"2026-11-02T10:15:30.120Z","trigger":"interval","frame_w":640,"frame_h":480,"persons":[{"bbox":[1,2,3,4],"conf":0.9,"helmet":false,"vest":true}]}'
curl -X POST $S/api/events -H "X-Device-Key: $K" \
  -F 'meta={"device_id":"pi-01","ts":"2026-11-02T10:15:31.000Z","trigger":"violation","frame_w":640,"frame_h":480,"persons":[]}' \
  -F 'image=@test.jpg;type=image/jpeg'
curl -X PUT $S/api/frame -H "X-Device-Key: $K" -H "Content-Type: image/jpeg" --data-binary @test.jpg
curl $S/api/latest
curl "$S/api/events?only_violations=true"
```
