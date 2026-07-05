"""
One-way Mode 기준 포지션 상태 조회 + "현재 포지션 vs 새 시그널" 상태 전이 판단.
전이 규칙은 strategy_design.md 6.3의 표를 그대로 구현한다.
"""
from dataclasses import dataclass
from enum import Enum

from strategies.base_strategy import Side


class Action(Enum):
    OPEN = "open"                 # 포지션 없음 -> 신규 진입
    HOLD = "hold"                 # 같은 방향 유지 (피라미딩 없음)
    REVERSE = "reverse"           # 반대 시그널 -> 기존 청산 후 반대로 신규 진입
    KEEP_WATCHING = "keep_watching"  # 시그널 없음, 손절/익절만 감시
    NONE = "none"                 # 포지션도 없고 시그널도 없음


@dataclass(frozen=True)
class PositionState:
    side: Side
    contracts: float
    entry_price: float


@dataclass(frozen=True)
class OpenPositionSnapshot:
    """진입 시점의 정보를 기억해뒀다가, 거래소에서 SL/TP가 조용히 체결됐을 때
    (봇이 직접 청산 주문을 내지 않은 경우) 손익/사유를 계산하는 데 사용한다."""
    side: Side
    entry_price: float
    quantity: float
    stop_price: float
    take_profit_price: float
    stop_order_id: str
    take_profit_order_id: str


def get_position_state(client, symbol: str) -> PositionState:
    """ccxt의 unified position 필드에서 'contracts'는 보통 절댓값이라 부호로 방향을
    판단할 수 없다. 방향은 unified 'side' 필드를 우선 쓰고, 없으면 원시 응답의
    positionAmt 부호로 보정한다(One-way Mode에서 positionAmt는 롱이면 +, 숏이면 -)."""
    pos = client.fetch_position(symbol)
    if pos is None:
        return PositionState(Side.NONE, 0.0, 0.0)

    contracts = abs(float(pos.get("contracts") or 0))
    entry_price = float(pos.get("entryPrice") or 0)

    raw_side = pos.get("side")
    if raw_side == "long":
        side = Side.LONG
    elif raw_side == "short":
        side = Side.SHORT
    else:
        position_amt = float(pos.get("info", {}).get("positionAmt") or 0)
        side = Side.LONG if position_amt > 0 else Side.SHORT

    return PositionState(side, contracts, entry_price)


def decide_action(current: PositionState, signal_side: Side) -> Action:
    if current.side == Side.NONE:
        return Action.OPEN if signal_side != Side.NONE else Action.NONE

    if signal_side == Side.NONE:
        return Action.KEEP_WATCHING

    if signal_side == current.side:
        return Action.HOLD

    return Action.REVERSE
