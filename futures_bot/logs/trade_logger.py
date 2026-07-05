"""
거래/에러 로그. CSV로 남겨서 실제 체결 내역(바이낸스 거래내역)과의 대사(reconciliation)를
쉽게 할 수 있게 한다. 동시에 사람이 보기 좋은 형식으로 텔레그램 알림을 보낸다.
"""
import csv
import os
from datetime import datetime, timezone


def _display_symbol(symbol: str) -> str:
    return symbol.split(":")[0]  # "BTC/USDT:USDT" -> "BTC/USDT"


def _fmt_num(x, decimals=2) -> str:
    if x is None:
        return "-"
    formatted = f"{x:,.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def _fmt_qty(x) -> str:
    return _fmt_num(x, decimals=6)


def _fmt_signed(x, decimals=2) -> str:
    return f"{x:+,.{decimals}f}"


def _fmt_pct(x, decimals=2) -> str:
    return f"{x:+.{decimals}f}%"


class TradeLogger:
    def __init__(self, log_dir: str, notifier=None):
        os.makedirs(log_dir, exist_ok=True)
        self.trade_log_path = os.path.join(log_dir, "trades.csv")
        self.error_log_path = os.path.join(log_dir, "errors.log")
        self.notifier = notifier
        self._ensure_trade_log_header()

    def _ensure_trade_log_header(self):
        if not os.path.exists(self.trade_log_path):
            with open(self.trade_log_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp_utc", "symbol", "action", "side", "quantity",
                                  "price", "stop_price", "take_profit_price", "reason"])

    def _write_csv_row(self, symbol: str, action: str, side: str, quantity: float, price: float,
                        stop_price: float = None, take_profit_price: float = None, reason: str = ""):
        with open(self.trade_log_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now(timezone.utc).isoformat(), symbol, action, side, quantity,
                price, stop_price, take_profit_price, reason,
            ])

    def _notify(self, message: str):
        if self.notifier is not None:
            self.notifier.send(message)

    def log_open(self, symbol: str, side, quantity: float, price: float, stop_price: float,
                 take_profit_price: float, risk_pct: float, daily_pnl_pct: float, reason: str):
        self._write_csv_row(symbol, "open", side.value, quantity, price, stop_price, take_profit_price, reason)
        lines = [
            f"\U0001F7E2 [진입] {_display_symbol(symbol)} {side.value.upper()}",
            f"가격: {_fmt_num(price)}",
            f"수량: {_fmt_qty(quantity)}",
            f"손절: {_fmt_num(stop_price)}",
            f"익절: {_fmt_num(take_profit_price)}",
            f"리스크: 계좌 {risk_pct:.1f}%",
            f"오늘 손익: {_fmt_pct(daily_pnl_pct)}",
            f"사유: {reason}",
        ]
        self._notify("\n".join(lines))

    def log_close(self, symbol: str, side, entry_price: float, exit_price: float, quantity: float,
                  pnl_usdt: float, pnl_pct: float, daily_pnl_pct: float, reason: str):
        self._write_csv_row(symbol, "close", side.value, quantity, exit_price, reason=reason)
        lines = [
            f"\U0001F534 [청산] {_display_symbol(symbol)} {side.value.upper()}",
            f"진입: {_fmt_num(entry_price)}",
            f"청산: {_fmt_num(exit_price)}",
            f"손익: {_fmt_signed(pnl_usdt)} USDT ({_fmt_pct(pnl_pct)})",
            f"오늘 손익: {_fmt_pct(daily_pnl_pct)}",
            f"사유: {reason}",
        ]
        self._notify("\n".join(lines))

    def log_reverse(self, symbol: str, old_side, new_side, old_quantity: float, close_price: float,
                    new_quantity: float, entry_price: float, stop_price: float, take_profit_price: float,
                    daily_pnl_pct: float, reason: str):
        self._write_csv_row(symbol, "close", old_side.value, old_quantity, close_price, reason="reverse_close")
        self._write_csv_row(symbol, "open", new_side.value, new_quantity, entry_price,
                             stop_price, take_profit_price, reason="reverse_open")
        lines = [
            f"\U0001F501 [반전] {_display_symbol(symbol)} {old_side.value.upper()} -> {new_side.value.upper()}",
            f"청산가: {_fmt_num(close_price)}",
            f"신규진입: {_fmt_num(entry_price)}",
            f"손절: {_fmt_num(stop_price)}",
            f"익절: {_fmt_num(take_profit_price)}",
            f"오늘 손익: {_fmt_pct(daily_pnl_pct)}",
            f"사유: {reason}",
        ]
        self._notify("\n".join(lines))

    def log_blocked(self, symbol: str, side, price: float, daily_pnl_pct: float, reason: str):
        self._write_csv_row(symbol, "entry_blocked", side.value, 0, price, reason=reason)
        lines = [
            f"⏸️ [진입 차단] {_display_symbol(symbol)} {side.value.upper()}",
            f"가격: {_fmt_num(price)}",
            f"오늘 손익: {_fmt_pct(daily_pnl_pct)}",
            f"사유: {reason}",
        ]
        self._notify("\n".join(lines))

    def log_skipped(self, symbol: str, side, price: float, reason: str):
        self._write_csv_row(symbol, "entry_skipped", side.value, 0, price, reason=reason)
        lines = [
            f"⏭️ [진입 스킵] {_display_symbol(symbol)} {side.value.upper()}",
            f"가격: {_fmt_num(price)}",
            f"사유: {reason}",
        ]
        self._notify("\n".join(lines))

    def log_error(self, symbol: str, message: str, action_hint: str = "포지션/보호주문 수동 확인 필요"):
        with open(self.error_log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} | {symbol} | {message}\n")
        lines = [
            f"⚠️ [에러] {_display_symbol(symbol)}" if symbol else "⚠️ [에러]",
            f"내용: {message[:300]}",
            f"조치: {action_hint}",
        ]
        self._notify("\n".join(lines))
