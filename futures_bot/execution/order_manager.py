"""
주문 실행. 폴더 43(바이낸스무한돌파봇) 패턴을 참고: 진입 즉시 STOP_MARKET 손절과
TAKE_PROFIT_MARKET 익절을 동시에 예약해서, 프로세스가 죽어도 거래소 서버에 걸린
주문으로 손절/익절이 보장되도록 한다(로컬 프로세스에만 의존하는 손절은 위험).
"""
from strategies.base_strategy import Side


def _entry_order_side(side: Side) -> str:
    return "buy" if side == Side.LONG else "sell"


def _exit_order_side(side: Side) -> str:
    """포지션을 닫는 주문의 side는 진입과 반대 방향이다."""
    return "sell" if side == Side.LONG else "buy"


def cancel_reduce_only_orders(client, symbol: str):
    open_orders = client.fetch_open_orders(symbol)
    for order in open_orders:
        if order.get("reduceOnly") or (order.get("info", {}).get("reduceOnly") in ("true", True)):
            client.cancel_order(order["id"], symbol)


def open_position_with_protection(client, symbol: str, side: Side, quantity: float,
                                   stop_price: float, take_profit_price: float) -> dict:
    """시장가 진입 + 손절/익절 예약주문을 순서대로 실행. 손절/익절 주문 실패시
    보유 포지션이 무방비로 남지 않도록 예외를 그대로 올려서 호출부(main.py)가
    즉시 알림을 보내고 수동 대응할 수 있게 한다."""
    quantity = client.amount_to_precision(symbol, quantity)
    stop_price = client.price_to_precision(symbol, stop_price)
    take_profit_price = client.price_to_precision(symbol, take_profit_price)

    entry_order = client.create_market_order(symbol, _entry_order_side(side), quantity, reduce_only=False)

    exit_side = _exit_order_side(side)
    stop_order = client.create_stop_market_order(symbol, exit_side, quantity, stop_price, reduce_only=True)
    tp_order = client.create_take_profit_market_order(symbol, exit_side, quantity, take_profit_price, reduce_only=True)

    return {"entry_order": entry_order, "stop_order": stop_order, "take_profit_order": tp_order}


def close_position_market(client, symbol: str, side: Side, quantity: float) -> dict:
    """side는 '현재 보유 중인 포지션'의 방향이다. 반대 방향 reduceOnly 시장가로 청산."""
    cancel_reduce_only_orders(client, symbol)
    quantity = client.amount_to_precision(symbol, quantity)
    return client.create_market_order(symbol, _exit_order_side(side), quantity, reduce_only=True)
