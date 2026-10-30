// A 담당: Wi-Fi 연결/재연결 + MQTT 발행
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "common.h"
#include "freertos/task.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "mqtt_client.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#define TOPIC          "ztmc/" CONFIG_CAM_ID "/face"
#define MIN_PERIOD_MS  200  // 최대 5Hz

static const char *TAG = "net";

static esp_mqtt_client_handle_t s_mqtt;
static volatile bool s_mqtt_connected;

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        // 끊기면 무한 재시도. MQTT는 esp-mqtt가 자체적으로 재연결한다.
        wifi_event_sta_disconnected_t *ev = data;
        ESP_LOGW(TAG, "Wi-Fi disconnected (reason %d), reconnecting", ev->reason);
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = data;
        ESP_LOGI(TAG, "got ip " IPSTR, IP2STR(&ev->ip_info.ip));
    }
}

static void mqtt_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    switch ((esp_mqtt_event_id_t)id) {
    case MQTT_EVENT_CONNECTED:
        ESP_LOGI(TAG, "MQTT connected, topic %s", TOPIC);
        s_mqtt_connected = true;
        break;
    case MQTT_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "MQTT disconnected");
        s_mqtt_connected = false;
        break;
    default:
        break;
    }
}

static void wifi_init(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL));

    wifi_config_t wc = {0};
    strlcpy((char *)wc.sta.ssid, CONFIG_WIFI_SSID, sizeof(wc.sta.ssid));
    strlcpy((char *)wc.sta.password, CONFIG_WIFI_PASS, sizeof(wc.sta.password));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_ps(WIFI_PS_NONE);  // 절전 끄기: 발행 지연 감소
}

static void mqtt_init(void)
{
    esp_mqtt_client_config_t cfg = {
        .broker.address.uri = CONFIG_MQTT_URI,
        .session.keepalive = 5,                 // 끊김을 빨리 감지
        .network.reconnect_timeout_ms = 2000,
    };
    s_mqtt = esp_mqtt_client_init(&cfg);
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(s_mqtt, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL));
    ESP_ERROR_CHECK(esp_mqtt_client_start(s_mqtt));
}

static void publish_task(void *arg)
{
    QueueHandle_t in = (QueueHandle_t)arg;
    char payload[32];
    float score;

    for (;;) {
        if (xQueueReceive(in, &score, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        int64_t t0 = esp_timer_get_time();

        if (s_mqtt_connected) {  // 미연결 중에는 버린다
            if (score < 0.0f) score = 0.0f;
            if (score > 1.0f) score = 1.0f;
            int c = (int)(score * 100.0f + 0.5f);  // 소수 2자리 (float printf 의존 회피)
            int len = snprintf(payload, sizeof(payload), "{\"score\":%d.%02d}", c / 100, c % 100);
            esp_mqtt_client_publish(s_mqtt, TOPIC, payload, len, 0, 0);
        }

        // 최대 5Hz: 남은 시간 대기. 그 사이 들어온 값은 큐에서 덮어써져 최신 값만 남는다.
        int64_t elapsed_ms = (esp_timer_get_time() - t0) / 1000;
        if (elapsed_ms < MIN_PERIOD_MS) {
            vTaskDelay(pdMS_TO_TICKS(MIN_PERIOD_MS - elapsed_ms));
        }
    }
}

void net_start(QueueHandle_t in)
{
    wifi_init();
    mqtt_init();  // Wi-Fi 연결 전이어도 esp-mqtt가 재시도한다
    xTaskCreate(publish_task, "mqtt_pub", 4096, in, 5, NULL);
}
