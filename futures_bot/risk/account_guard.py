"""
계좌 단위 안전장치: 일일 최대 손실 제한 + 연속 손실 쿨다운.
전략이 아무리 좋은 신호를 내도 이 두 조건 중 하나라도 걸리면 신규 진입을 막는다.
프로세스가 재시작돼도 당일 손실 상태가 유지되도록 JSON 파일에 저장한다.
"""
import json
import os
from datetime import datetime, timezone, timedelta


class AccountGuard:
    def __init__(self, log_dir: str, max_daily_loss_pct: float, max_consecutive_losses: int, cooldown_minutes: int):
        self.state_path = os.path.join(log_dir, "account_guard_state.json")
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_minutes = cooldown_minutes
        os.makedirs(log_dir, exist_ok=True)
        self._state = self._load_state()

    def _today_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _default_state(self) -> dict:
        return {
            "date": self._today_key(),
            "daily_pnl_pct": 0.0,
            "consecutive_losses": 0,
            "cooldown_until": None,
        }

    def _load_state(self) -> dict:
        if not os.path.exists(self.state_path):
            return self._default_state()
        with open(self.state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if state.get("date") != self._today_key():
            return self._default_state()
        return state

    def _save_state(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    def can_open_new_position(self) -> tuple[bool, str]:
        self._state = self._load_state()

        if self._state["daily_pnl_pct"] <= -abs(self.max_daily_loss_pct):
            return False, f"daily_loss_limit_hit({self._state['daily_pnl_pct']:.2f}%)"

        cooldown_until = self._state.get("cooldown_until")
        if cooldown_until:
            until_dt = datetime.fromisoformat(cooldown_until)
            if datetime.now(timezone.utc) < until_dt:
                return False, f"cooldown_active_until({cooldown_until})"

        return True, ""

    def record_trade_result(self, pnl_pct_of_equity: float):
        """거래 청산 후 호출. pnl_pct_of_equity는 계좌자본 대비 손익률(%, 음수=손실)."""
        self._state = self._load_state()
        self._state["daily_pnl_pct"] += pnl_pct_of_equity

        if pnl_pct_of_equity < 0:
            self._state["consecutive_losses"] += 1
            if self._state["consecutive_losses"] >= self.max_consecutive_losses:
                until = datetime.now(timezone.utc) + timedelta(minutes=self.cooldown_minutes)
                self._state["cooldown_until"] = until.isoformat()
                self._state["consecutive_losses"] = 0
        else:
            self._state["consecutive_losses"] = 0

        self._save_state()
