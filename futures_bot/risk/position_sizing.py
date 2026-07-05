"""
포지션 사이즈 = "1회 손실 한도"를 손절폭으로 역산한 수량.
size = (계좌자본 * 1회손실한도%) / |진입가 - 손절가|
레버리지는 사이즈 자체를 늘리는 데 쓰지 않고(그러면 손실한도% 원칙이 깨짐),
"이 손실한도%가 요구하는 명목포지션을 실제로 열 수 있는 증거금이 되는지"의
상한선 검증에만 쓴다.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PositionSizeResult:
    quantity: float
    notional: float
    skipped_reason: str = ""


def compute_position_size(equity: float, risk_per_trade_pct: float, entry_price: float, stop_price: float,
                           leverage: int, min_notional: float) -> PositionSizeResult:
    price_distance = abs(entry_price - stop_price)
    if price_distance <= 0:
        return PositionSizeResult(0.0, 0.0, "invalid_stop_distance")

    risk_amount = equity * (risk_per_trade_pct / 100)
    quantity = risk_amount / price_distance
    notional = quantity * entry_price

    max_notional_by_margin = equity * leverage
    if notional > max_notional_by_margin:
        # 손절폭이 너무 좁아 요구 수량이 증거금 한도를 넘는 경우: 증거금 한도로 캡.
        # (사실상 손절폭 대비 레버리지가 부족하다는 신호이므로 상한선에서 멈춘다)
        notional = max_notional_by_margin
        quantity = notional / entry_price

    if notional < min_notional:
        return PositionSizeResult(0.0, 0.0, f"notional {notional:.2f} < min_notional {min_notional:.2f}")

    return PositionSizeResult(quantity, notional)
