# C 담당: 디바운스 상태머신 (I/O 없음). 규칙은 README 참조


class Presence:
    def __init__(self, score_th, present_ms, absent_ms, stale_ms):
        self.th, self.present_ms, self.absent_ms, self.stale_ms = score_th, present_ms, absent_ms, stale_ms
        self.state = "offline"
        self.last_msg = None  # 마지막 메시지 시각(ms)
        self.cand = None      # 현재 연속 중인 후보 상태
        self.since = None     # 후보가 시작된 시각(ms)

    def update(self, now, score=None):
        """now: ms. score: 새 메시지면 float, tick이면 None. 현재 상태 반환."""
        if score is not None:
            self.last_msg = now
            cand = "present" if score >= self.th else "absent"
            if cand != self.cand:
                self.cand, self.since = cand, now
        if self.last_msg is None or now - self.last_msg >= self.stale_ms:
            self.state, self.cand = "offline", None  # 복귀 시 디바운스 처음부터
            return self.state
        hold = self.present_ms if self.cand == "present" else self.absent_ms
        if self.cand != self.state and now - self.since >= hold:
            self.state = self.cand
        return self.state
