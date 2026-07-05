"""
실거래 루프 진입점. One-way Mode, 심볼별 독립 처리.

흐름 (strategy_design.md 4.1 파이프라인 그대로):
  캔들 수집 -> 지표/시그널 계산 -> 포지션 상태 조회 -> 상태전이 판단
  -> 리스크 계산(사이즈/손절/익절) -> 주문 실행 -> 로그

주의: 이 파일은 실거래 코드다. 반드시 .env의 BINANCE_TESTNET=true 상태로
Binance Futures Testnet에서 먼저 충분히 검증한 뒤 실계좌로 전환할 것
(strategy_design.md 9번 "실거래 전 검증 단계" 참고).
"""
import sys
import time
import traceback

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 기본 코드페이지에서도 한글 로그가 깨지지 않도록

from config.settings import CONFIG
from data.binance_client import BinanceFuturesClient
from data.candle_fetcher import fetch_recent_candles
from strategies.trend_breakout import TrendBreakoutStrategy
from strategies.base_strategy import Side
from execution.position_manager import get_position_state, decide_action, Action, OpenPositionSnapshot
from execution.order_manager import open_position_with_protection, close_position_market, cancel_reduce_only_orders
from risk.position_sizing import compute_position_size
from risk.stop_loss import compute_stop_price, is_stop_safely_inside_liquidation
from risk.take_profit import compute_take_profit_price
from risk.account_guard import AccountGuard
from logs.trade_logger import TradeLogger
from notifications.telegram_notifier import TelegramNotifier


def _korean_entry_reason(side: Side) -> str:
    return "EMA상승 + 볼린저밴드 상단돌파 + RSI상승" if side == Side.LONG else "EMA하락 + 볼린저밴드 하단돌파 + RSI하락"


def _korean_reverse_reason(new_side: Side) -> str:
    return "상승 시그널 발생" if new_side == Side.LONG else "하락 시그널 발생"


def _friendly_block_reason(code: str) -> str:
    if code.startswith("daily_loss_limit_hit"):
        return "일일 손실 한도 도달"
    if code.startswith("cooldown_active_until"):
        return "연속 손실 쿨다운 중"
    return code


def _friendly_sizing_reason(code: str) -> str:
    if code == "invalid_stop_distance":
        return "손절폭 계산 불가"
    if code.startswith("notional"):
        return "최소 주문금액 미달"
    return code


def process_symbol(client, symbol_cfg, strategy, guard, logger, last_candle_ts, snapshots):
    symbol = symbol_cfg.symbol

    # 캔들 확정 여부와 무관하게, 거래소에서 SL/TP가 조용히 체결됐는지는 매 폴링마다 확인한다.
    # (다음 15분봉 확정까지 기다리면 알림이 최대 15분 늦어짐)
    _check_exchange_closed_position(client, symbol, snapshots, guard, logger)

    df = fetch_recent_candles(client, symbol, CONFIG.strategy.timeframe, limit=300)
    if len(df) < 2:
        return last_candle_ts

    last_closed_ts = df.index[-2]  # 마지막 확정 캔들의 타임스탬프
    if last_candle_ts.get(symbol) == last_closed_ts:
        return last_candle_ts  # 이미 처리한 캔들이면 스킵 (캔들 확정시에만 판단)
    last_candle_ts[symbol] = last_closed_ts

    signal = strategy.generate_signal(df)
    current = get_position_state(client, symbol)
    action = decide_action(current, signal.side)

    if action in (Action.NONE, Action.HOLD, Action.KEEP_WATCHING):
        return last_candle_ts

    if action == Action.REVERSE:
        _reverse_position(client, symbol, symbol_cfg, current, signal, snapshots, guard, logger)
        return last_candle_ts

    can_trade, block_reason = guard.can_open_new_position()
    if not can_trade:
        logger.log_blocked(symbol, signal.side, signal.close, guard.daily_pnl_pct(),
                            _friendly_block_reason(block_reason))
        return last_candle_ts

    snapshot = _open_and_log(client, symbol, symbol_cfg, signal, guard, logger)
    if snapshot:
        snapshots[symbol] = snapshot

    return last_candle_ts


def _check_exchange_closed_position(client, symbol, snapshots, guard, logger):
    snapshot = snapshots.get(symbol)
    if snapshot is None:
        return

    current = get_position_state(client, symbol)
    if current.side != Side.NONE:
        return  # 아직 보유중

    exit_price, reason = _resolve_exchange_exit(client, symbol, snapshot)
    cancel_reduce_only_orders(client, symbol)  # 반대쪽에 남은 예약주문 정리(둘 다 reduceOnly라 OCO가 아님)

    equity = client.fetch_balance_usdt()
    direction = 1 if snapshot.side == Side.LONG else -1
    pnl_usdt = (exit_price - snapshot.entry_price) * snapshot.quantity * direction
    pnl_pct = (pnl_usdt / equity * 100) if equity > 0 else 0.0
    guard.record_trade_result(pnl_pct)

    logger.log_close(symbol, snapshot.side, snapshot.entry_price, exit_price, snapshot.quantity,
                      pnl_usdt, pnl_pct, guard.daily_pnl_pct(), reason)
    snapshots.pop(symbol, None)


def _resolve_exchange_exit(client, symbol, snapshot):
    """TP/SL 예약주문 중 어느 게 체결됐는지 조회해서 사유와 실제 체결가를 판정한다."""
    tp_order = client.fetch_order(snapshot.take_profit_order_id, symbol)
    if tp_order.get("status") == "closed":
        return float(tp_order.get("average") or tp_order.get("price") or snapshot.take_profit_price), "익절"

    stop_order = client.fetch_order(snapshot.stop_order_id, symbol)
    if stop_order.get("status") == "closed":
        return float(stop_order.get("average") or stop_order.get("price") or snapshot.stop_price), "손절"

    return snapshot.entry_price, "알수없음(수동 청산 추정)"


def _reverse_position(client, symbol, symbol_cfg, current, signal, snapshots, guard, logger):
    old_snapshot = snapshots.pop(symbol, None)
    old_side = current.side
    old_quantity = current.contracts
    old_entry_price = old_snapshot.entry_price if old_snapshot else current.entry_price

    equity = client.fetch_balance_usdt()
    close_order = close_position_market(client, symbol, old_side, old_quantity)
    exit_price = float(close_order.get("average") or close_order.get("price") or signal.close)

    direction = 1 if old_side == Side.LONG else -1
    pnl_usdt = (exit_price - old_entry_price) * old_quantity * direction
    pnl_pct = (pnl_usdt / equity * 100) if equity > 0 else 0.0
    guard.record_trade_result(pnl_pct)

    can_trade, block_reason = guard.can_open_new_position()
    if not can_trade:
        logger.log_close(symbol, old_side, old_entry_price, exit_price, old_quantity, pnl_usdt, pnl_pct,
                          guard.daily_pnl_pct(),
                          f"반대 시그널 발생 (재진입 차단: {_friendly_block_reason(block_reason)})")
        return

    new_snapshot, skip_reason = _try_open(client, symbol, symbol_cfg, signal)
    if new_snapshot is None:
        logger.log_close(symbol, old_side, old_entry_price, exit_price, old_quantity, pnl_usdt, pnl_pct,
                          guard.daily_pnl_pct(), f"반대 시그널 발생 (재진입 실패: {skip_reason})")
        return

    snapshots[symbol] = new_snapshot
    logger.log_reverse(symbol, old_side, signal.side, old_quantity, exit_price,
                        new_snapshot.quantity, new_snapshot.entry_price, new_snapshot.stop_price,
                        new_snapshot.take_profit_price, guard.daily_pnl_pct(),
                        _korean_reverse_reason(signal.side))


def _try_open(client, symbol, symbol_cfg, signal):
    """리스크 계산 + 주문 실행만 담당. 로깅/알림은 호출부가 처리(반전 시 통합 메시지가 필요해서 분리)."""
    equity = client.fetch_balance_usdt()
    stop_price = compute_stop_price(signal.close, signal.atr, signal.side, CONFIG.risk.atr_stop_multiplier)

    if not is_stop_safely_inside_liquidation(signal.close, stop_price, symbol_cfg.leverage, signal.side,
                                              CONFIG.risk.liquidation_safety_margin_pct):
        return None, "손절가가 청산가에 너무 근접함"

    sizing = compute_position_size(equity, CONFIG.risk.risk_per_trade_pct, signal.close, stop_price,
                                    symbol_cfg.leverage, client.min_notional(symbol))
    if sizing.quantity <= 0:
        return None, _friendly_sizing_reason(sizing.skipped_reason)

    take_profit_price = compute_take_profit_price(signal.close, stop_price, signal.side,
                                                   CONFIG.risk.reward_risk_ratio)
    orders = open_position_with_protection(client, symbol, signal.side, sizing.quantity, stop_price,
                                            take_profit_price)

    snapshot = OpenPositionSnapshot(
        side=signal.side, entry_price=signal.close, quantity=sizing.quantity,
        stop_price=stop_price, take_profit_price=take_profit_price,
        stop_order_id=orders["stop_order"]["id"], take_profit_order_id=orders["take_profit_order"]["id"],
    )
    return snapshot, ""


def _open_and_log(client, symbol, symbol_cfg, signal, guard, logger):
    snapshot, skip_reason = _try_open(client, symbol, symbol_cfg, signal)
    if snapshot is None:
        logger.log_skipped(symbol, signal.side, signal.close, skip_reason)
        return None

    logger.log_open(symbol, signal.side, snapshot.quantity, signal.close, snapshot.stop_price,
                     snapshot.take_profit_price, CONFIG.risk.risk_per_trade_pct, guard.daily_pnl_pct(),
                     _korean_entry_reason(signal.side))
    return snapshot


def main():
    client = BinanceFuturesClient(CONFIG)
    strategy = TrendBreakoutStrategy(CONFIG.strategy)
    guard = AccountGuard(CONFIG.log_dir, CONFIG.risk.max_daily_loss_pct,
                          CONFIG.risk.max_consecutive_losses, CONFIG.risk.cooldown_minutes)
    notifier = TelegramNotifier(CONFIG.notification.telegram_bot_token, CONFIG.notification.telegram_chat_id,
                                 CONFIG.notification.telegram_enabled)
    logger = TradeLogger(CONFIG.log_dir, notifier=notifier)

    for symbol_cfg in CONFIG.symbols:
        client.ensure_symbol_setup(symbol_cfg)

    last_candle_ts = {}
    open_snapshots = {}
    print(f"[START] testnet={CONFIG.testnet} symbols={[s.symbol for s in CONFIG.symbols]}")

    while True:
        for symbol_cfg in CONFIG.symbols:
            try:
                process_symbol(client, symbol_cfg, strategy, guard, logger, last_candle_ts, open_snapshots)
            except Exception as e:
                logger.log_error(symbol_cfg.symbol, str(e))
                print(f"[ERROR] {symbol_cfg.symbol}: {e}\n{traceback.format_exc()}")
        time.sleep(CONFIG.poll_interval_sec)


if __name__ == "__main__":
    main()
