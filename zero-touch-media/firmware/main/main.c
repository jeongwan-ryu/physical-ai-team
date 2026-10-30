#include "common.h"

void app_main(void)
{
    QueueHandle_t q = xQueueCreate(1, sizeof(float));
    detect_start(q);
    net_start(q);
}
