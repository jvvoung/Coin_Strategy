"""
거래/에러 로그. CSV로 남겨서 실제 체결 내역(바이낸스 거래내역)과의 대사(reconciliation)를
쉽게 할 수 있게 한다.
"""
import csv
import os
from datetime import datetime, timezone


class TradeLogger:
    def __init__(self, log_dir: str):
        os.makedirs(log_dir, exist_ok=True)
        self.trade_log_path = os.path.join(log_dir, "trades.csv")
        self.error_log_path = os.path.join(log_dir, "errors.log")
        self._ensure_trade_log_header()

    def _ensure_trade_log_header(self):
        if not os.path.exists(self.trade_log_path):
            with open(self.trade_log_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp_utc", "symbol", "action", "side", "quantity",
                                  "price", "stop_price", "take_profit_price", "reason"])

    def log_trade(self, symbol: str, action: str, side: str, quantity: float, price: float,
                   stop_price: float = None, take_profit_price: float = None, reason: str = ""):
        with open(self.trade_log_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now(timezone.utc).isoformat(), symbol, action, side, quantity,
                price, stop_price, take_profit_price, reason,
            ])

    def log_error(self, message: str):
        with open(self.error_log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} | {message}\n")
