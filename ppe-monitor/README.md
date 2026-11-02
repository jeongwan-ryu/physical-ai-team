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
# edge/data/sample.mp4 를 넣어 두면 ESP32 없이 개발할 수 있음 (E가 공유)
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

## 역할

| | 담당 | 파일 | 완료 기준 |
|---|---|---|---|
| A | ESP32-CAM, 시연 환경, Pi (Pi 보유자) | `firmware/`, `docs/demo-setup.md` | `curl http://<ESP32_IP>/capture`로 640×480 JPEG 수신, Pi에서 edge 컨테이너 실행, 카메라가 대시보드 플레이어를 정면으로 촬영 |
| B | 모델 확인, 착용 판정 로직 | `edge/app/compliance.py`, `edge/tests/test_compliance.py` | `test_compliance.py` 통과, 시연 영상에서 `CONF_TH`·`HEAD_RATIO` 값을 정해 팀에 공유 |
| C | edge 메인 루프, 통합 리드 | `edge/app/main.py`, `edge/compose.yml`, `edge/.env.example` | `SOURCE=/data/sample.mp4`로 실행하면 server에 interval·violation 이벤트와 프레임이 도착 |
| D | server, EC2 배포 | `server/`, `docker-compose.yml`, `.env.example` | `docs/interface.md` 8장의 curl이 모두 정상 응답, EC2에서 집 IP로만 접속 가능 |
| E | 대시보드, 시연 영상 | `dashboard/` | 큰 YouTube 플레이어, 실시간 프레임, 인원·미착용 수, offline 표시, 위반 목록(사진 포함) 동작 |

## 시간표

| 시간 | 할 일 |
|---|---|
| 0:00–0:30 | 전원: interface.md 읽기, `best.pt` 받기. **A: Pi에서 `docker pull ultralytics/ultralytics:8.4.198-arm64` 먼저 시작** (약 1 GB). **E: 시연 영상을 정하고 `sample.mp4` 공유** |
| 0:30–3:30 | 각자 개발 (LLM 사용). **1:30 중간 점검:** D의 curl 응답, A의 `/capture`, B의 판정 함수 테스트 |
| 3:30–4:00 | 점심 |
| 4:00–5:30 | **노트북에서 1차 통합:** sample.mp4 → edge → server → 대시보드. 그다음 SOURCE를 ESP32로 바꿔서 확인 |
| 5:30–6:30 | Pi와 EC2로 옮겨서 실행 |
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
