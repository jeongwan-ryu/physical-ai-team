#include "common.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#if CONFIG_FAKE_DETECT
// 카메라 없이 테스트: 1초마다 0.9 / 0 토글
static void fake_detect_task(void *arg)
{
    QueueHandle_t out = (QueueHandle_t)arg;
    float score = 0.9f;
    for (;;) {
        xQueueOverwrite(out, &score);
        score = (score > 0.0f) ? 0.0f : 0.9f;
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
#endif

void app_main(void)
{
    QueueHandle_t q = xQueueCreate(1, sizeof(float));
#if CONFIG_FAKE_DETECT
    xTaskCreate(fake_detect_task, "fake_detect", 2048, q, 5, NULL);
#else
    detect_start(q);
#endif
    net_start(q);
}
