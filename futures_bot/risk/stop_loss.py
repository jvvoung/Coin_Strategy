from strategies.base_strategy import Side


def compute_stop_price(entry_price: float, atr: float, side: Side, atr_multiplier: float) -> float:
    if side == Side.LONG:
        return entry_price - atr * atr_multiplier
    if side == Side.SHORT:
        return entry_price + atr * atr_multiplier
    raise ValueError(f"stop price is undefined for side={side}")


def estimate_liquidation_price(entry_price: float, leverage: int, side: Side, maintenance_margin_rate: float = 0.005) -> float:
    """근사치 청산가 계산 (격리마진, 단순화된 공식). 실제 청산가는 유지증거금률 구간(bracket)에
    따라 달라지므로, 여기서는 안전마진 점검용 보수적 근사치로만 사용한다."""
    if side == Side.LONG:
        return entry_price * (1 - 1 / leverage + maintenance_margin_rate)
    if side == Side.SHORT:
        return entry_price * (1 + 1 / leverage - maintenance_margin_rate)
    raise ValueError(f"liquidation price is undefined for side={side}")


def is_stop_safely_inside_liquidation(entry_price: float, stop_price: float, leverage: int, side: Side,
                                       safety_margin_pct: float) -> bool:
    """손절가가 청산가보다 safety_margin_pct(%)만큼 더 안쪽(진입가에 가까운 쪽)에 있는지 확인.
    아니라면 레버리지가 손절폭 대비 과도하다는 뜻 — 진입을 스킵해야 한다."""
    liq_price = estimate_liquidation_price(entry_price, leverage, side)

    if side == Side.LONG:
        loss_to_stop = entry_price - stop_price
        loss_to_liq = entry_price - liq_price
    else:
        loss_to_stop = stop_price - entry_price
        loss_to_liq = liq_price - entry_price

    if loss_to_liq <= 0:
        return False

    margin_ratio = 1 - (loss_to_stop / loss_to_liq)
    return margin_ratio * 100 >= safety_margin_pct
