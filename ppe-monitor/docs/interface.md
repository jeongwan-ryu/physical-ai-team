# 팀 간 데이터 인터페이스 명세

> 버전: v0.1 (2026-11-02) · 상태: 초안. 첫 회의에서 확정합니다.

PPE(안전모·조끼) 착용 모니터링 서비스의 **구성요소끼리 주고받는 데이터 형식**을 정의합니다.
각 구성요소의 내부 구현은 담당자가 자유롭게 정하되, 이 문서에 적힌 경계는 반드시 지킵니다.

---

## 0. 규칙 (사람과 LLM 모두 따를 것)

1. **이 문서가 기준입니다.** 코드와 이 문서가 다르면 문서가 맞고, 코드를 고쳐야 합니다.
2. **필드 이름, 타입, 엔드포인트 경로는 이 문서의 철자 그대로** 사용합니다. 비슷한 이름을 새로 만들지 않습니다.
3. 여기에 없는 필드나 엔드포인트가 필요하면, 코드보다 **이 문서를 고치는 PR을 먼저** 올리고 관련 담당자의 승인을 받습니다.
4. **받는 쪽은 모르는 필드를 무시합니다.** 필드가 추가되어도 기존 코드가 깨지지 않게 하기 위해서입니다. 보내는 쪽은 필수 필드를 절대 빠뜨리지 않습니다.
5. 변경하면 맨 아래 **변경 이력**에 기록하고 버전을 올립니다.

---

## 1. 전체 구조와 연결 지점

```
[모니터: 대시보드 + YouTube] ──(카메라로 화면 촬영)──▶ [ESP32-CAM]
                                                          │ I1. GET /capture → JPEG
                                                          ▼
                     I2. 모델 파일 ──────────────▶ [Raspberry Pi: edge]
                                                          │ I3. POST /api/events
                                                          │     PUT  /api/devices/{id}/frame
                                                          ▼
                                                    [서버: FastAPI]
                                                          │ I4. GET /api/latest, /api/events, /api/stats ...
                                                          ▼
                                                    [대시보드]
```

| ID | 보내는 쪽 → 받는 쪽 | 형태 | 담당 |
|---|---|---|---|
| I1 | ESP32-CAM → edge | HTTP (edge가 요청해서 가져감) | A ↔ C |
| I2 | ML → edge | 모델 파일 + 클래스 정의 | B ↔ C |
| I3 | edge → 서버 | HTTPS REST | C ↔ D |
| I4 | 서버 → 대시보드 | HTTPS REST | D ↔ E |

외부 API는 **YouTube IFrame Player API** 하나뿐이며 대시보드에서만 사용합니다(7장 참고). 이 문서에서 "서버 API"라고 하면 우리가 만드는 `/api/...` 엔드포인트를 뜻합니다.

---

## 2. 공통 규약

| 항목 | 규칙 |
|---|---|
| 문자 인코딩 | UTF-8 |
| JSON 키 이름 | `snake_case` |
| 시각 | ISO 8601, **UTC**, `Z`로 끝남, 밀리초까지 가능. 예: `2026-11-02T10:15:30.120Z` |
| 시각의 의미 | `ts`는 **edge가 프레임을 캡처한 시각**입니다(서버가 받은 시각이 아님). Pi에는 RTC가 없으므로 NTP 동기화가 필수입니다. |
| bbox 좌표 | `[x1, y1, x2, y2]` 정수 픽셀. 기준은 **원본 프레임**(`frame_w` × `frame_h`)이고, 원점은 좌상단, `x1 < x2`, `y1 < y2` |
| 신뢰도 | `conf`는 0.0 ~ 1.0 사이 float |
| ID | `device_id`: `pi-01`처럼 소문자·숫자·하이픈만 사용. `event_id`: UUID v4 문자열 |
| 이미지 | JPEG, 1장당 **1 MB 이하** |
| 에러 응답 | FastAPI 기본 형식인 `{"detail": "<메시지>"}` |
| 인증 (edge → 서버) | HTTP 헤더 `X-Device-Key: <기기 토큰>` |

---

## 3. I1. ESP32-CAM → edge

edge가 ESP32-CAM에 **요청해서 한 장씩 가져갑니다**(pull). ESP32는 요청에 응답만 하고, 먼저 데이터를 보내지 않습니다.

```
GET http://<ESP32_IP>/capture
→ 200 OK
  Content-Type: image/jpeg
  Body: JPEG 바이트
```

| 항목 | 값 |
|---|---|
| 포트 | 80 (CameraWebServer 예제 기본값). 스트림 포트 81은 사용하지 않습니다. |
| 해상도 | **VGA 640×480으로 고정** (펌웨어에서 설정) |
| JPEG 품질 | `jpeg_quality` 10~12 (ESP32는 숫자가 낮을수록 고화질) |
| 노출·화이트밸런스 | 모니터를 촬영하므로 **자동 끄고 고정**. 값은 `docs/demo-setup.md`에 기록 |
| 주소 | **DHCP 예약으로 IP 고정** (Docker 컨테이너 안에서는 mDNS `.local` 이름 해석이 불안정함) |
| edge 요청 타임아웃 | 3초. 실패하면 1초 뒤 재시도, 무한 반복. 10회 연속 실패하면 ERROR 로그 |

**개발 모드:** edge의 `SOURCE`가 `http`로 시작하지 않으면 영상 파일 경로로 간주하고 파일에서 프레임을 읽습니다. ESP32가 없어도 전체 흐름을 테스트할 수 있습니다.

---

## 4. I2. ML → edge (모델 파일)

### 클래스 정의 (인덱스 고정, 바꾸지 않음)

| index | name | 의미 |
|---|---|---|
| 0 | `person` | 사람 전신 또는 상반신 |
| 1 | `helmet` | 안전모 (머리에 쓴 것만. 손에 든 것은 라벨링하지 않음) |
| 2 | `vest` | 안전조끼 (입은 것만) |

- 데이터셋에 `no-helmet`, `no-vest` 같은 클래스가 있으면 **학습 전에 버리거나 위 3개로 다시 매핑**합니다.
- 미착용 여부는 모델이 직접 판단하지 않고 edge가 계산합니다(5.3 참고).

### 산출물 형식

| 항목 | 값 |
|---|---|
| 형식 | Ultralytics NCNN export 디렉터리 (`model.ncnn.param`, `model.ncnn.bin`, `metadata.yaml`) |
| 이름 | `ppe-v<major>.<minor>_ncnn_model/`. 예: `ppe-v1.0_ncnn_model/` |
| 입력 크기 | export할 때 쓴 `imgsz`(기본 640)를 릴리스 노트에 기록 |
| 전달 방법 | Git에는 커밋하지 않음. **GitHub Release**에 `model-v1.0` 태그로 zip 업로드 |
| 릴리스 노트 필수 항목 | 학습 데이터 구성, `imgsz`, val mAP50 (클래스별), Pi 5에서 측정한 FPS |
| edge 로드 방법 | `YOLO("<MODEL_PATH>")` |

**edge 시작 시 검증:** `model.names`가 `{0:'person', 1:'helmet', 2:'vest'}`와 다르면 **즉시 종료**합니다. 클래스 순서가 어긋난 모델이 조용히 잘못된 결과를 내는 것을 막기 위해서입니다.

---

## 5. I3. edge → 서버

### 5.1 이벤트 기록: `POST /api/events`

판정 결과를 서버 DB에 **영구 기록**합니다.

**보내는 시점**
- `trigger: "interval"`: `REPORT_INTERVAL_S`(기본 5초)마다 현재 상태를 요약해서 보냄. 사람이 0명이어도 보냄.
- `trigger: "violation"`: 위반이 **새로 확정되는 순간** 즉시 보냄. 위반이 계속 이어지는 동안에는 다시 보내지 않고 interval 이벤트에만 반영됨.

**요청 형식:** `multipart/form-data`

| 파트 | 필수 | 내용 |
|---|---|---|
| `meta` | ✅ | 아래 JSON을 **문자열로** 담음 |
| `image` | 조건부 | 박스를 그려 넣은 JPEG. **`trigger`가 `"violation"`이면 필수**, `"interval"`이면 넣지 않음 |

```json
{
  "event_id": "3f1c2a9e-8b7d-4c1e-9a55-0d2f6b1e7c42",
  "device_id": "pi-01",
  "ts": "2026-11-02T10:15:30.120Z",
  "trigger": "violation",
  "model_version": "ppe-v1.0",
  "frame_w": 640,
  "frame_h": 480,
  "persons": [
    {"bbox": [102, 40, 230, 410], "conf": 0.91, "helmet": true,  "vest": true},
    {"bbox": [300, 55, 420, 400], "conf": 0.87, "helmet": false, "vest": true},
    {"bbox": [450, 60, 600, 430], "conf": 0.78, "helmet": false, "vest": false}
  ]
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `event_id` | string(UUID v4) | ✅ | edge가 생성. **재전송해도 같은 값을 유지**(중복 방지 키) |
| `device_id` | string | ✅ | |
| `ts` | string(ISO 8601 UTC) | ✅ | 판정에 사용한 프레임의 캡처 시각 |
| `trigger` | `"interval"` \| `"violation"` | ✅ | |
| `model_version` | string | ✅ | 예: `ppe-v1.0` |
| `frame_w`, `frame_h` | int | ✅ | bbox 기준이 되는 프레임 크기 |
| `persons` | array | ✅ | 검출된 **모든** 사람. 0명이면 `[]` |
| `persons[].bbox` | int[4] | ✅ | 2장 규약 참고 |
| `persons[].conf` | float | ✅ | person 검출 신뢰도 |
| `persons[].helmet` | bool | ✅ | 안전모를 쓰고 있다고 판정되면 `true` |
| `persons[].vest` | bool | ✅ | 조끼를 입고 있다고 판정되면 `true` |

**위반의 정의:** `helmet == false` 또는 `vest == false`인 사람을 위반자로 봅니다. 인원 수와 위반 수는 **서버가 `persons`를 보고 계산**하며, edge는 별도로 보내지 않습니다.

**응답**

| 코드 | 의미 | edge의 처리 |
|---|---|---|
| `201` | 새로 기록됨. 본문: `{"event_id": "...", "image_url": "..." \| null}` | 큐에서 삭제 |
| `200` | 같은 `event_id`가 이미 기록되어 있음(중복). 본문은 201과 같음 | 큐에서 삭제 |
| `400` / `422` | 형식 오류 | 큐에서 빼서 `failed.jsonl`에 기록하고 ERROR 로그. **재시도하지 않음** |
| `401` | 기기 토큰 오류 | 큐에 남겨 두고 ERROR 로그 (설정 문제이므로 고칠 때까지 보관) |
| `413` | 이미지가 1 MB 초과 | 400과 같이 처리 |
| `5xx`, 네트워크 오류 | 서버나 네트워크 문제 | 큐에 남겨 두고 지수 백오프로 재시도 (1초에서 시작, 최대 60초) |

**오프라인 큐:** edge는 이벤트를 **먼저 로컬 SQLite에 저장한 뒤** 전송하고, 2xx 응답을 받아야 삭제합니다. 컨테이너가 재시작되어도 큐는 볼륨에 남아 있어야 합니다.

### 5.2 실시간 프레임: `PUT /api/devices/{device_id}/frame`

대시보드에 보여 줄 **최신 프레임 한 장**을 덮어씁니다. 이 데이터는 기록용이 아닙니다.

```
PUT /api/devices/pi-01/frame
X-Device-Key: <토큰>
X-Frame-Ts: 2026-11-02T10:15:30.120Z
Content-Type: image/jpeg
Body: 박스를 그려 넣은 JPEG (1 MB 이하)
→ 204 No Content
```

- 주기: `FRAME_PUSH_INTERVAL_S`(기본 1초)
- 서버는 기기마다 **최신 1장만** 보관(메모리 또는 파일). DB나 S3에는 저장하지 않음.
- 전송에 실패해도 **재시도하지 않고 버림**. 다음 프레임이 곧 올라오기 때문입니다.

### 5.3 착용 판정 규칙 (참고: edge 내부 구현이지만 의미를 공유하기 위해 적어 둠)

- `helmet`: `conf ≥ CONF_TH`인 helmet 박스의 중심이 person 박스의 **위쪽 `HEAD_RATIO`(기본 0.3) 영역** 안에 있으면 `true`
- `vest`: `conf ≥ CONF_TH`인 vest 박스의 중심이 person 박스의 **세로 0.2~0.7 영역** 안에 있으면 `true`
- 위반 확정: 같은 위반 상태가 `CONFIRM_FRAMES`(기본 3)프레임 연속으로 나와야 `trigger: "violation"`으로 보냄
- 사람 추적(tracking)은 v0.1에서 하지 않습니다. 따라서 "같은 사람"을 식별하는 ID는 없습니다.

---

## 6. I4. 서버 → 대시보드

- 모든 응답은 JSON입니다. 단, 프레임 이미지 엔드포인트만 JPEG를 반환합니다.
- 대시보드는 **2초 간격 폴링**으로 갱신합니다. WebSocket은 사용하지 않습니다.
- `image_url`과 `frame_url`은 **그대로 `<img src>`에 넣어 쓰는 값**입니다. 운영 환경에서는 S3 presigned URL(유효 1시간), 개발 환경에서는 `/media/...` 경로이므로 대시보드가 URL을 직접 조립하지 않습니다.

### 6.1 `GET /api/latest?device_id=pi-01`

```json
{
  "device_id": "pi-01",
  "online": true,
  "ts": "2026-11-02T10:15:30.120Z",
  "person_count": 3,
  "no_helmet": 2,
  "no_vest": 1,
  "persons": [ {"bbox": [102,40,230,410], "conf": 0.91, "helmet": true, "vest": true} ],
  "frame_url": "/api/devices/pi-01/frame",
  "frame_ts": "2026-11-02T10:15:31.002Z"
}
```

- 가장 최근 이벤트를 기준으로 합니다. `persons`의 각 항목은 5.1과 같은 형식입니다.
- `online`: 최근 15초 안에 이벤트나 프레임을 받았으면 `true`
- `no_helmet`: `helmet == false`인 사람 수, `no_vest`: `vest == false`인 사람 수 (한 사람이 두 값에 모두 포함될 수 있음)
- 이벤트가 하나도 없으면 `404`를 반환합니다.

### 6.2 `GET /api/devices/{device_id}/frame`

- `200 image/jpeg`: 가장 최근에 받은 프레임
- `404`: 아직 받은 프레임이 없음
- 브라우저 캐시를 피하려면 `?t=<frame_ts>`를 붙여서 요청합니다.

### 6.3 `GET /api/events`

| 쿼리 | 기본값 | 설명 |
|---|---|---|
| `device_id` | 전체 | |
| `only_violations` | `false` | `true`이면 위반자가 1명 이상인 이벤트만 |
| `before` | 없음 | 이 시각보다 이전 이벤트만 (페이지 넘기기용) |
| `limit` | 50 | 최대 500 |

```json
{
  "items": [
    {
      "event_id": "3f1c2a9e-8b7d-4c1e-9a55-0d2f6b1e7c42",
      "device_id": "pi-01",
      "ts": "2026-11-02T10:15:30.120Z",
      "trigger": "violation",
      "person_count": 3,
      "no_helmet": 2,
      "no_vest": 1,
      "image_url": "https://...presigned..."
    }
  ],
  "next_before": "2026-11-02T10:10:02.000Z"
}
```

- `items`는 `ts` 내림차순(최신이 먼저)으로 정렬됩니다.
- `image_url`은 이미지가 없으면 `null`입니다.
- `next_before`가 `null`이면 마지막 페이지입니다. 아니면 그 값을 다음 요청의 `before`에 넣습니다.

### 6.4 `GET /api/stats?device_id=pi-01&range=1h`

| `range` | 집계 단위(bucket) |
|---|---|
| `1h` | 1분 |
| `24h` | 1시간 |
| `7d` | 1일 |

```json
{
  "range": "1h",
  "bucket_seconds": 60,
  "buckets": [
    {"start": "2026-11-02T10:15:00Z", "person_samples": 36, "helmet_rate": 0.72, "vest_rate": 0.91, "violation_events": 2}
  ]
}
```

- `person_samples`: 해당 구간의 `interval` 이벤트들에 나온 `persons` 수의 합
- `helmet_rate` = `helmet == true`인 사람 수 ÷ `person_samples`. **`person_samples`가 0이면 `null`**이며, 0.0이 아닙니다.
- `vest_rate`: `helmet_rate`와 같은 방식으로 계산
- `violation_events`: 해당 구간의 `trigger == "violation"` 이벤트 수
- 비율은 `interval` 이벤트만으로 계산합니다. `violation` 이벤트는 시점이 몰려 있어서 비율을 왜곡하기 때문입니다.

---

## 7. 외부 API: YouTube (대시보드 전용)

- **YouTube IFrame Player API**를 사용합니다. API 키가 필요 없습니다.
- 재생할 영상은 `VITE_YOUTUBE_VIDEO_ID` 환경변수로 지정합니다. 퍼가기(embed)가 허용된 영상만 사용할 수 있습니다.
- YouTube Data API v3(검색, 목록 조회)는 v0.1에서 사용하지 않습니다.
- 우리 서버와 YouTube 사이에는 데이터가 오가지 않습니다. 영상은 모니터 화면을 거쳐 카메라로만 들어옵니다.

---

## 8. 인증과 공개 범위

| 경로 | 인증 |
|---|---|
| `POST /api/events`, `PUT /api/devices/*/frame` | `X-Device-Key` (서버의 `DEVICE_KEYS`에 등록된 값) |
| 그 외 모든 경로 (대시보드, 조회 API) | 운영 환경에서는 Caddy의 **Basic Auth**. 위 두 쓰기 경로는 Basic Auth 대상에서 제외 |

- 위반 스냅샷에는 사람이 찍히므로 **S3 버킷은 비공개**로 두고 presigned URL로만 접근합니다.
- 토큰과 비밀번호는 `.env`에만 저장하고 Git에는 커밋하지 않습니다(`.env.example`에는 키 이름만 적음).

---

## 9. 환경변수 (이름 고정)

### edge
| 이름 | 예시 | 설명 |
|---|---|---|
| `DEVICE_ID` | `pi-01` | |
| `DEVICE_KEY` | `change-me` | |
| `SERVER_URL` | `https://ppe.example.com` | 끝에 `/` 없음 |
| `SOURCE` | `http://192.168.0.50/capture` 또는 `/data/sample.mp4` | 3장 참고 |
| `MODEL_PATH` | `/models/ppe-v1.0_ncnn_model` | |
| `CONF_TH` | `0.4` | 보정값 |
| `HEAD_RATIO` | `0.3` | 보정값 |
| `CONFIRM_FRAMES` | `3` | 보정값 |
| `REPORT_INTERVAL_S` | `5` | |
| `FRAME_PUSH_INTERVAL_S` | `1` | |
| `QUEUE_PATH` | `/data/queue.db` | 볼륨 마운트 필수 |

### server
| 이름 | 예시 | 설명 |
|---|---|---|
| `DATABASE_URL` | `postgresql://ppe:ppe@db:5432/ppe` | |
| `DEVICE_KEYS` | `pi-01:change-me,pi-02:other` | `device_id:key`를 쉼표로 구분 |
| `S3_BUCKET` | `ppe-snapshots` | **비어 있으면 `MEDIA_DIR`에 로컬로 저장**(개발용) |
| `AWS_REGION` | `ap-northeast-2` | |
| `MEDIA_DIR` | `/data/media` | |

### dashboard
| 이름 | 예시 | 설명 |
|---|---|---|
| `VITE_API_BASE` | `""` (같은 도메인) | 개발 중에는 Vite proxy 사용 |
| `VITE_YOUTUBE_VIDEO_ID` | `dQw4w9WgXcQ` | |

---

## 10. 빠른 확인용 예시

```bash
# 이벤트 전송 (interval)
curl -X POST "$SERVER_URL/api/events" \
  -H "X-Device-Key: $DEVICE_KEY" \
  -F 'meta={"event_id":"3f1c2a9e-8b7d-4c1e-9a55-0d2f6b1e7c42","device_id":"pi-01","ts":"2026-11-02T10:15:30.120Z","trigger":"interval","model_version":"ppe-v1.0","frame_w":640,"frame_h":480,"persons":[]}'

# 위반 이벤트 전송 (image 필수)
curl -X POST "$SERVER_URL/api/events" \
  -H "X-Device-Key: $DEVICE_KEY" \
  -F 'meta=<meta.json' -F 'image=@snapshot.jpg;type=image/jpeg'

# 프레임 업로드
curl -X PUT "$SERVER_URL/api/devices/pi-01/frame" \
  -H "X-Device-Key: $DEVICE_KEY" -H "X-Frame-Ts: 2026-11-02T10:15:31.002Z" \
  -H "Content-Type: image/jpeg" --data-binary @frame.jpg

# 조회
curl "$SERVER_URL/api/latest?device_id=pi-01"
curl "$SERVER_URL/api/events?only_violations=true&limit=20"
curl "$SERVER_URL/api/stats?device_id=pi-01&range=1h"
```

---

## 변경 이력

| 버전 | 날짜 | 변경 내용 | 승인 |
|---|---|---|---|
| v0.1 | 2026-11-02 | 초안 | - |
