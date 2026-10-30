// B 담당: esp32-camera + human_face_detect
#include "common.h"
#include "esp_camera.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "human_face_detect.hpp"

static const char *TAG = "detect";

// XIAO ESP32S3 Sense 핀맵 (Seeed camera_pins.h, CAMERA_MODEL_XIAO_ESP32S3)
#define CAM_PIN_PWDN  -1
#define CAM_PIN_RESET -1
#define CAM_PIN_XCLK  10
#define CAM_PIN_SIOD  40
#define CAM_PIN_SIOC  39
#define CAM_PIN_D7    48
#define CAM_PIN_D6    11
#define CAM_PIN_D5    12
#define CAM_PIN_D4    14
#define CAM_PIN_D3    16
#define CAM_PIN_D2    18
#define CAM_PIN_D1    17
#define CAM_PIN_D0    15
#define CAM_PIN_VSYNC 38
#define CAM_PIN_HREF  47
#define CAM_PIN_PCLK  13

#define FPS_LOG_FRAMES 50

static esp_err_t camera_init(void)
{
    camera_config_t cfg = {};
    cfg.pin_pwdn = CAM_PIN_PWDN;
    cfg.pin_reset = CAM_PIN_RESET;
    cfg.pin_xclk = CAM_PIN_XCLK;
    cfg.pin_sccb_sda = CAM_PIN_SIOD;
    cfg.pin_sccb_scl = CAM_PIN_SIOC;
    cfg.pin_d7 = CAM_PIN_D7;
    cfg.pin_d6 = CAM_PIN_D6;
    cfg.pin_d5 = CAM_PIN_D5;
    cfg.pin_d4 = CAM_PIN_D4;
    cfg.pin_d3 = CAM_PIN_D3;
    cfg.pin_d2 = CAM_PIN_D2;
    cfg.pin_d1 = CAM_PIN_D1;
    cfg.pin_d0 = CAM_PIN_D0;
    cfg.pin_vsync = CAM_PIN_VSYNC;
    cfg.pin_href = CAM_PIN_HREF;
    cfg.pin_pclk = CAM_PIN_PCLK;
    cfg.xclk_freq_hz = 20000000;
    cfg.ledc_timer = LEDC_TIMER_0;
    cfg.ledc_channel = LEDC_CHANNEL_0;
    cfg.pixel_format = PIXFORMAT_RGB565;  // JPEG는 디코딩 비용 추가
    cfg.frame_size = FRAMESIZE_QVGA;
    cfg.fb_count = 2;
    cfg.fb_location = CAMERA_FB_IN_PSRAM;
    cfg.grab_mode = CAMERA_GRAB_LATEST;   // 추론 중 쌓인 오래된 프레임 대신 최신 프레임
    return esp_camera_init(&cfg);
}

static void detect_task(void *arg)
{
    QueueHandle_t out = (QueueHandle_t)arg;
    HumanFaceDetect *detector = new HumanFaceDetect();
    int frames = 0;
    int64_t t0 = esp_timer_get_time();

    while (true) {
        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) {
            ESP_LOGW(TAG, "frame capture failed");
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        dl::image::img_t img = {
            .data = fb->buf,
            .width = (uint16_t)fb->width,
            .height = (uint16_t)fb->height,
            .pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB565BE,  // esp32-camera RGB565는 빅엔디언
        };
        float score = 0.0f;
        for (const auto &r : detector->run(img)) {
            if (r.score > score) {
                score = r.score;
            }
        }
        esp_camera_fb_return(fb);
        xQueueOverwrite(out, &score);

        if (++frames == FPS_LOG_FRAMES) {
            int64_t t1 = esp_timer_get_time();
            ESP_LOGI(TAG, "%.1f fps, last score %.2f", frames * 1e6 / (t1 - t0), score);
            frames = 0;
            t0 = t1;
        }
    }
}

void detect_start(QueueHandle_t out)
{
    esp_err_t err = camera_init();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "camera init failed: %s", esp_err_to_name(err));
        return;
    }
    // Wi-Fi는 core 0에서 돌므로 추론은 core 1
    xTaskCreatePinnedToCore(detect_task, "detect", 8192, out, 5, NULL, 1);
}
