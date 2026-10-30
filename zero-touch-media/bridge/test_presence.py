# C 담당: presence.py 테스트. 실행: docker compose run --rm bridge python test_presence.py
from presence import Presence


def new():
    return Presence(0.5, 300, 1500, 2000)


# 초기 offline, tick만으로는 그대로
p = new()
assert p.update(0) == "offline"
assert p.update(5000) == "offline"

# present: 300ms 연속이어야 전환 (tick에서도 판정)
p = new()
assert p.update(0, 0.9) == "offline"
assert p.update(200, 0.9) == "offline"
assert p.update(299) == "offline"
assert p.update(300) == "present"

# 경계: score == SCORE_TH 는 present 쪽
p = new()
p.update(0, 0.5)
assert p.update(300) == "present"

# 중간에 끊기면 연속 카운트 리셋
p = new()
p.update(0, 0.9); p.update(200, 0.1); p.update(250, 0.9)
assert p.update(500) == "offline"
assert p.update(550) == "present"

# absent: 1500ms 연속, 짧은 누락(깜빡임)은 무시
p = new()
p.update(0, 0.9); p.update(300, 0.9)
assert p.state == "present"
p.update(400, 0.0); p.update(1000, 0.0)
assert p.update(1800, 0.9) == "present"  # 1400ms 만에 복귀 → 유지
p.update(2000, 0.0)
for t in range(2200, 3400, 200):
    assert p.update(t, 0.0) == "present"
assert p.update(3500, 0.0) == "absent"

# 첫 메시지가 0 → absent (시연 2단계: ESP32 켜짐)
p = new()
p.update(0, 0.0); p.update(1000, 0.0)
assert p.update(1500) == "absent"

# stale: 메시지가 2000ms 없으면 offline
p = new()
p.update(0, 0.9); p.update(300, 0.9)
assert p.update(2299) == "present"
assert p.update(2300) == "offline"

# offline 복귀 후에는 디바운스 처음부터 (예전 since로 즉시 전환되면 안 됨)
assert p.update(3000, 0.9) == "offline"
assert p.update(3299) == "offline"
assert p.update(3300) == "present"

print("ok")
