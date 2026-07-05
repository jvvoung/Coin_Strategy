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
from execution.position_manager import get_position_state, decide_action, Action
from execution.order_manager import open_position_with_protection, close_position_market
from risk.position_sizing import compute_position_size
from risk.stop_loss import compute_stop_price, is_stop_safely_inside_liquidation
from risk.take_profit import compute_take_profit_price
from risk.account_guard import AccountGuard
from logs.trade_logger import TradeLogger


def process_symbol(client, symbol_cfg, strategy, guard, logger, last_candle_ts):
    symbol = symbol_cfg.symbol

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
        _close_and_log(client, symbol, current, guard, logger, reason="reverse_signal")
        current = get_position_state(client, symbol)  # 청산 반영된 최신 상태 재조회

    if action in (Action.OPEN, Action.REVERSE):
        can_trade, block_reason = guard.can_open_new_position()
        if not can_trade:
            logger.log_trade(symbol, "entry_blocked", signal.side.value, 0, signal.close, reason=block_reason)
            return last_candle_ts
        _open_and_log(client, symbol, symbol_cfg, signal, logger)

    return last_candle_ts


def _close_and_log(client, symbol, current, guard, logger, reason):
    if current.side == Side.NONE:
        return
    pos = client.fetch_position(symbol)
    unrealized_pnl = float((pos or {}).get("unrealizedPnl") or 0)
    equity = client.fetch_balance_usdt()
    pnl_pct = (unrealized_pnl / equity * 100) if equity > 0 else 0.0

    close_position_market(client, symbol, current.side, current.contracts)
    guard.record_trade_result(pnl_pct)
    logger.log_trade(symbol, "close", current.side.value, current.contracts, current.entry_price, reason=reason)


def _open_and_log(client, symbol, symbol_cfg, signal, logger):
    equity = client.fetch_balance_usdt()
    stop_price = compute_stop_price(signal.close, signal.atr, signal.side, CONFIG.risk.atr_stop_multiplier)

    if not is_stop_safely_inside_liquidation(signal.close, stop_price, symbol_cfg.leverage, signal.side,
                                              CONFIG.risk.liquidation_safety_margin_pct):
        logger.log_trade(symbol, "entry_skipped", signal.side.value, 0, signal.close,
                          reason="stop_too_close_to_liquidation")
        return

    sizing = compute_position_size(equity, CONFIG.risk.risk_per_trade_pct, signal.close, stop_price,
                                    symbol_cfg.leverage, client.min_notional(symbol))
    if sizing.quantity <= 0:
        logger.log_trade(symbol, "entry_skipped", signal.side.value, 0, signal.close, reason=sizing.skipped_reason)
        return

    take_profit_price = compute_take_profit_price(signal.close, stop_price, signal.side,
                                                   CONFIG.risk.reward_risk_ratio)

    open_position_with_protection(client, symbol, signal.side, sizing.quantity, stop_price, take_profit_price)
    logger.log_trade(symbol, "open", signal.side.value, sizing.quantity, signal.close,
                      stop_price=stop_price, take_profit_price=take_profit_price, reason=signal.reason)


def main():
    client = BinanceFuturesClient(CONFIG)
    strategy = TrendBreakoutStrategy(CONFIG.strategy)
    guard = AccountGuard(CONFIG.log_dir, CONFIG.risk.max_daily_loss_pct,
                          CONFIG.risk.max_consecutive_losses, CONFIG.risk.cooldown_minutes)
    logger = TradeLogger(CONFIG.log_dir)

    for symbol_cfg in CONFIG.symbols:
        client.ensure_symbol_setup(symbol_cfg)

    last_candle_ts = {}
    print(f"[START] testnet={CONFIG.testnet} symbols={[s.symbol for s in CONFIG.symbols]}")

    while True:
        for symbol_cfg in CONFIG.symbols:
            try:
                process_symbol(client, symbol_cfg, strategy, guard, logger, last_candle_ts)
            except Exception as e:
                logger.log_error(f"{symbol_cfg.symbol}: {e}\n{traceback.format_exc()}")
                print(f"[ERROR] {symbol_cfg.symbol}: {e}")
        time.sleep(CONFIG.poll_interval_sec)


if __name__ == "__main__":
    main()
