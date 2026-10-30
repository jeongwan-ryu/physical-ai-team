#!/bin/sh
# ESP32 없이 테스트: present 3초 → absent 3초 → 중단(2초 뒤 offline)
# 사용: zero-touch-media/ 에서 docker compose up -d 후 ./tools/fake_esp32.sh
pub() { docker compose exec -T mosquitto mosquitto_pub -t ztmc/cam1/face -m "{\"score\":$1}"; }
for i in $(seq 15); do pub 0.9; sleep 0.2; done
for i in $(seq 15); do pub 0;   sleep 0.2; done
