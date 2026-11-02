# PPE Monitor (하루 프로젝트)

작업 현장 인원의 안전모·조끼 착용 여부를 판정하고, 그 결과를 클라우드(EC2)에 자동으로 기록합니다.

```
[모니터: 대시보드 + YouTube] → [ESP32-CAM] ─GET /capture─▶ [Raspberry Pi: edge 컨테이너] ─HTTP─▶ [EC2: server 컨테이너] ─▶ 브라우저
                               (Arduino IDE)                  YOLOv8n(best.pt) + 착용 판정        FastAPI + SQLite + 대시보드
```

**데이터 형식은 [`docs/interface.md`](docs/interface.md)가 유일한 기준입니다.**

## 실행

준비 (각자 한 번):
```sh
curl -L -o edge/models/best.pt https://huggingface.co/Hansung-Cho/yolov8-ppe-detection/resolve/main/best.pt
cp .env.example .env
cp edge/.env.example edge/.env
# edge/data/sample.mp4 : E가 공유한 시연 영상을 각자 화면 녹화해서 저장 (ESP32 없이 개발할 때 사용, 아래 '시연 영상' 참고)
```

server와 대시보드 (노트북 또는 EC2):
```sh
docker compose up -d --build        # http://localhost
```

edge (노트북 또는 Pi):
```sh
cd edge
docker compose up                   # 코드 수정 후에는 docker compose restart
docker compose run --rm edge python tests/test_compliance.py
```

Pi 속도 확인 (A, 오전에 한 번):
```sh
docker run --rm -v $PWD/edge/models:/models -v $PWD/edge/data:/data ultralytics/ultralytics:8.4.198-arm64 \
  yolo predict model=/models/best.pt source=/data/sample.mp4 imgsz=640
# 로그의 프레임당 처리 시간이 1000ms 안쪽이면 그대로 진행.
# 느리면 ① edge/.env 에서 IMGSZ=320 ② 그래도 느리면 노트북에서 NCNN 변환 후 MODEL_PATH만 변경 (코드 그대로)
#   yolo export model=edge/models/best.pt format=ncnn imgsz=640   → MODEL_PATH=/models/best_ncnn_model
```

## 시연 영상

**E가 시작 30분 안에 시연 영상을 골라 팀 채널에 URL을 공유합니다.**

고르는 기준:
- **퍼가기 허용:** 아래 명령 결과가 `200`이면 대시보드에서 재생 가능, `401`이면 퍼가기 금지입니다.
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=<영상ID>&format=json"
  ```
- **사람이 크고 선명하게:** 정면이나 측면으로 크게 나오는 밝은 낮 장면. 멀리 작게 찍힌 사람은 모니터를 다시 찍으면 검출이 어렵습니다.
- **정상과 위반이 모두 나오게:** 한 영상에 둘 다 나오거나, 정상용·위반용 2개로 나눕니다. 안전모 미착용 장면이 있으면 가장 좋습니다.
- **박스나 자막이 덧씌워진 영상은 제외:** 다른 AI 검출 데모 영상은 이미 박스가 그려져 있어서 우리 모델을 헷갈리게 합니다.

| 후보 | 내용 |
|---|---|
| [`DLknkTG1EpE`](https://www.youtube.com/watch?v=DLknkTG1EpE) | 실제 공사 현장 투어. 안전모와 형광 조끼를 모두 착용한 사람이 정면으로 크게 나옴(정상 장면 위주) |
| [`O9F4rXp1Ogc`](https://www.youtube.com/watch?v=O9F4rXp1Ogc) | 공사 현장 클립 모음. 안전모는 썼지만 조끼 없이 정장·셔츠 차림(조끼 미착용 장면 위주) |

두 후보 모두 퍼가기 허용은 확인했지만, 장면은 영상당 3~4곳만 확인했습니다. 안전모 미착용이 뚜렷한 영상은 아직 찾지 못했습니다.

- 시연 흐름 예시: 정상 장면(초록) → 위반 장면(빨강, 위반 기록 증가) → 다른 노트북에서 기록 확인
- **개발용 `sample.mp4`는 각자 만듭니다.** E가 공유한 영상을 브라우저에서 틀어 놓고 OS 기본 화면 녹화(Ubuntu `Ctrl+Shift+Alt+R`, Windows `Win+Alt+R`, macOS `Cmd+Shift+5`)로 1분 정도 녹화해서 `edge/data/sample.mp4`로 저장합니다.
- **YouTube 영상을 다운로드 도구(`yt-dlp` 등)로 받거나 코드에서 YouTube URL을 직접 읽지 않습니다.** YouTube 약관 위반입니다.
- 다른 장소의 노트북에서 대시보드를 보려면 그 공인 IP를 EC2 보안 그룹의 80번에 추가합니다.

## 역할

| | 담당 | 파일 | 완료 기준 |
|---|---|---|---|
| A | ESP32-CAM, 시연 환경, Pi (Pi 보유자) | `firmware/`, `docs/demo-setup.md` | `curl http://<ESP32_IP>/capture`로 640×480 JPEG 수신, 오전에 Pi FPS 확인, Pi에서 edge 컨테이너 실행, 카메라가 대시보드 플레이어를 정면으로 촬영 |
| B | 모델 확인, 착용 판정 로직 | `edge/app/compliance.py`, `edge/tests/test_compliance.py` | `test_compliance.py` 통과, 시연 영상에서 `CONF_TH`·`HEAD_RATIO` 값을 정해 팀에 공유 |
| C | edge 메인 루프, 통합 리드 | `edge/app/main.py`, `edge/compose.yml`, `edge/.env.example` | `SOURCE=/data/sample.mp4`로 실행하면 server에 interval·violation 이벤트와 프레임이 도착 |
| D | server, EC2 배포 | `server/`, `docker-compose.yml`, `.env.example` | `docs/interface.md` 8장의 curl이 모두 정상 응답, EC2에서 집 IP로만 접속 가능 |
| E | 대시보드, 시연 영상 선정 | `dashboard/` | 시연 영상 URL 공유(시작 30분 안), 큰 YouTube 플레이어(영상 버튼 전환), 실시간 프레임, 인원·미착용 수, offline 표시, 위반 목록(사진 포함) 동작 |

## 시간표

| 시간 | 할 일 |
|---|---|
| 0:00–0:30 | 전원: interface.md 읽기, `best.pt` 받기. **A: Pi에서 `docker pull ultralytics/ultralytics:8.4.198-arm64` 먼저 시작** (약 1 GB). **E: 시연 영상을 골라 URL 공유** |
| 0:30 | A·B·C: E가 공유한 영상으로 `sample.mp4` 화면 녹화(A는 Pi의 `edge/data/`에도 복사). 공유가 늦어지면 후보 영상으로 먼저 녹화 |
| 0:30–3:30 | 각자 개발 (LLM 사용). **A: 이미지가 받아지는 대로 Pi FPS 확인.** **1:30 중간 점검:** D의 curl 응답, A의 `/capture`, B의 판정 함수 테스트 |
| 3:30–4:00 | 점심 |
| 4:00–5:30 | **노트북에서 1차 통합:** sample.mp4 → edge → server → 대시보드. 그다음 SOURCE를 ESP32로 바꿔서 확인 |
| 5:30–6:30 | Pi와 EC2로 옮겨서 실행. 느리면 `IMGSZ=320` → NCNN 순서로 대응 |
| 6:30–7:30 | 기준값 조정, 리허설, **백업용 시연 녹화** |

## EC2 배포 (D)

1. Ubuntu 24.04, t3.micro로 인스턴스를 만듭니다. 보안 그룹은 **22와 80 포트를 집 공인 IP만** 허용합니다(`curl ifconfig.me`로 확인).
2. EC2에서 아래 명령을 실행합니다.
   ```sh
   curl -fsSL https://get.docker.com | sudo sh
   git clone <레포 URL> && cd physical-ai-team/ppe-monitor
   cp .env.example .env && nano .env        # DEVICE_KEY 설정
   sudo docker compose up -d --build        # http://<EC2 IP>
   ```
3. 시연이 끝나면 인스턴스를 중지합니다.

## LLM으로 개발할 때

`ppe-monitor/` 폴더에서 도구를 실행하면 `AGENTS.md`/`CLAUDE.md`를 자동으로 참조합니다. 첫 요청에서 자기 역할(A~E)을 밝히세요.

```
나는 C 담당이야. AGENTS.md의 C 항목대로 edge/app/main.py 구현해줘.
```
