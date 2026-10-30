#!/bin/sh
# ESP32 없이 테스트: present 3초 → absent 3초 → 중단(2초 뒤 offline)
# 사용: zero-touch-media/ 에서 docker compose up -d 후 ./tools/fake_esp32.sh
# 컨테이너 안에서 루프를 돌려 5Hz 간격을 지킨다 (메시지마다 exec하면 느려짐)
docker compose exec -T mosquitto sh -c '
pub() { mosquitto_pub -t ztmc/cam1/face -m "{\"score\":$1}"; }
i=0; while [ $i -lt 15 ]; do pub 0.9; sleep 0.2; i=$((i+1)); done
i=0; while [ $i -lt 15 ]; do pub 0;   sleep 0.2; i=$((i+1)); done
'
