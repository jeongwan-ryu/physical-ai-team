// A·B 공동 계약. 변경 시 README 계약과 함께 PR
#pragma once
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#ifdef __cplusplus
extern "C" {
#endif

// 큐: 길이 1, 항목 float score (얼굴 없으면 0)
void detect_start(QueueHandle_t out);  // B: 프레임마다 xQueueOverwrite(out, &score)
void net_start(QueueHandle_t in);      // A: xQueueReceive → {"score":..} 발행 (최대 5Hz)

#ifdef __cplusplus
}
#endif
