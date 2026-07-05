from strategies.base_strategy import Side


def compute_take_profit_price(entry_price: float, stop_price: float, side: Side, reward_risk_ratio: float) -> float:
    risk_distance = abs(entry_price - stop_price)
    reward_distance = risk_distance * reward_risk_ratio
    if side == Side.LONG:
        return entry_price + reward_distance
    if side == Side.SHORT:
        return entry_price - reward_distance
    raise ValueError(f"take profit is undefined for side={side}")
