# ESP32 카메라 펌웨어 (A)

Arduino `CameraWebServer` 예제를 기반으로 만든 펌웨어입니다. edge가 사용하는 기능은 `GET /capture`(640×480 JPEG) 하나입니다([docs/interface.md](../../docs/interface.md) 3장).

## 환경

| 항목 | 값 |
|---|---|
| 보드 | Seeed **XIAO ESP32S3 Sense** (`board_config.h`의 `CAMERA_MODEL_XIAO_ESP32S3`) |
| IDE | Arduino IDE 2 |
| 코어 | `esp32 by Espressif` **3.3.12** |
| Tools → Board | `XIAO_ESP32S3` |
| Tools → PSRAM | **`OPI PSRAM`** (끄면 카메라 초기화가 실패하거나 해상도가 제한됨) |
| Tools → Partition Scheme | `Default with spiffs (3MB APP/1.5MB SPIFFS)`. 스케치 폴더의 `partitions.csv`가 빌드할 때 자동으로 적용됩니다. |

## 업로드

1. Wi-Fi 정보 파일을 만듭니다. `secrets.h`는 Git에서 제외되어 있으니 **절대 커밋하지 않습니다.**
   ```sh
   cd CameraWebServer
   cp secrets.h.example secrets.h      # WIFI_SSID, WIFI_PASS 입력 (2.4GHz만 지원, Pi와 같은 Wi-Fi)
   ```
2. Arduino IDE에서 `CameraWebServer/CameraWebServer.ino`를 열고 위 Tools 설정을 맞춘 뒤 업로드합니다.
3. 시리얼 모니터(115200)를 열면 아래처럼 출력됩니다. 마지막 줄을 `edge/.env`에 그대로 붙여 넣으면 됩니다.
   ```
   WiFi connected
   Camera Ready! Use 'http://192.168.0.50' to connect
   edge SOURCE=http://192.168.0.50/capture
   ```
4. 같은 Wi-Fi의 노트북이나 Pi에서 확인합니다. 결과에 `640x480`이 나와야 합니다.
   ```sh
   curl -o a.jpg http://<ESP32_IP>/capture && file a.jpg
   ```
5. IP가 바뀌지 않도록 공유기에서 이 ESP32의 IP를 고정(DHCP 예약)하고, `docs/demo-setup.md`에 기록합니다.

## 예제에서 바꾼 것 (`CameraWebServer.ino`만 수정)

| 변경 | 이유 |
|---|---|
| Wi-Fi 정보를 `secrets.h`로 분리 | 비밀번호가 레포에 올라가지 않게 |
| 시작 시 해상도 QVGA → **VGA(640×480)**, JPEG 품질 12 고정 | interface 3장. 웹 UI에서 바꾼 값은 재부팅하면 사라지므로 코드에서 고정 |
| `FIX_EXPOSURE`, `AEC_VALUE` 추가 (기본: 자동 노출) | 모니터 촬영 화면이 너무 밝거나 어두울 때 노출을 고정하는 조절값 |
| `WiFi.setAutoReconnect(true)` | 공유기가 잠깐 끊겨도 다시 연결 |
| 시리얼에 `edge SOURCE=...` 출력 | edge 설정에 바로 쓰도록 |

`app_httpd.cpp`(엔드포인트), `board_config.h`, `camera_pins.h`, `camera_index.h`, `partitions.csv`는 예제 그대로입니다. 공식 예제의 CI 설정 파일(`ci.yml`)은 필요 없어서 넣지 않았습니다.

## 노출 보정

1. 기본(자동 노출)으로 대시보드의 YouTube 플레이어를 찍어서 `/capture` 사진을 확인합니다.
2. 화면이 하얗게 뜨거나 너무 어두우면 `FIX_EXPOSURE`를 `1`로 바꾸고 `AEC_VALUE`를 조정해 다시 업로드합니다. 밝으면 값을 낮추고, 어두우면 높입니다.
   - 값을 빨리 찾으려면 브라우저에서 `http://<ESP32_IP>`를 열고 AEC 슬라이더로 맞춰 본 뒤, 그 값을 코드에 넣습니다.
3. 정한 값을 `docs/demo-setup.md`에 기록합니다.

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| `Camera init failed with error 0x...` | Tools → PSRAM이 `OPI PSRAM`인지, 카메라 리본 케이블이 제대로 꽂혀 있는지 |
| `WiFi connecting.....`에서 멈춤 | 2.4GHz Wi-Fi인지, `secrets.h`의 SSID와 비밀번호 |
| `secrets.h: No such file or directory` | 업로드 1단계(`cp secrets.h.example secrets.h`) |
| `/capture` 사진이 640×480이 아님 | 웹 UI에서 해상도를 바꿨다면 재부팅하면 VGA로 돌아옴 |
