"""
백테스트 엔진. main.py와 동일한 strategies/, risk/ 함수를 그대로 호출해서
"백테스트에서는 이겼는데 실거래 로직이 달라서 결과가 다른" 문제를 원천 차단한다
(strategy_design.md 4.2 설계원칙).

시그널 계산 시점 정합성:
  main.py는 fetch_recent_candles가 반환한 마지막 행(진행 중 캔들)을 strategy가
  내부에서 잘라내는 방식으로 "직전 확정 캔들까지"의 정보만 쓴다. 백테스트에서
  bar i의 종가 확정 시점 신호를 재현하려면, strategy에 넘기는 윈도우의 마지막 행이
  bar i+1(아직 확정 안 된 캔들 역할)이 되도록 슬라이스해야 한다. 그래야 strategy가
  마지막 행을 잘라낸 뒤 실제로 bar i까지의 데이터로 계산한다.
  신호가 발생하면 체결은 bar i+1의 시가로 이뤄진다(다음 봉 시가 체결 = 표준 백테스트 관행,
  같은 봉 종가에 바로 체결시키면 미래참조 편향이 생긴다).

청산가(강제청산) 갭 리스크:
  손절 주문이 걸려 있어도 갭(캔들 시가가 손절가를 뛰어넘는 급락/급등)이 발생하면
  거래소는 손절가가 아니라 청산가 근방에서 강제청산한다. 이 엔진은 매 봉마다
  고저가가 추정 청산가를 침범했는지 먼저 확인해서 이 리스크를 반영한다.
"""
from dataclasses import dataclass, field

import pandas as pd

from strategies.base_strategy import Side
from execution.position_manager import PositionState, decide_action, Action
from risk.position_sizing import compute_position_size
from risk.stop_loss import compute_stop_price, is_stop_safely_inside_liquidation, estimate_liquidation_price
from risk.take_profit import compute_take_profit_price
from config.settings import RiskConfig, BacktestConfig, SymbolConfig


@dataclass
class OpenPosition:
    side: Side
    quantity: float
    entry_price: float
    stop_price: float
    take_profit_price: float
    entry_index: int


@dataclass
class Trade:
    side: Side
    entry_price: float
    exit_price: float
    quantity: float
    entry_index: int
    exit_index: int
    exit_reason: str
    pnl_usdt: float
    pnl_pct_of_equity: float


@dataclass
class BacktestResult:
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)  # (index, equity) 튜플 리스트
    final_equity: float = 0.0
    liquidation_events: int = 0


def _apply_slippage(price: float, side_is_buy: bool, slippage_bps: float) -> float:
    factor = slippage_bps / 10_000
    return price * (1 + factor) if side_is_buy else price * (1 - factor)


def run_backtest(df: pd.DataFrame, strategy, symbol_cfg: SymbolConfig,
                  risk_cfg: RiskConfig, bt_cfg: BacktestConfig) -> BacktestResult:
    equity = bt_cfg.initial_equity_usdt
    position: OpenPosition | None = None
    result = BacktestResult()

    window = bt_cfg.signal_window_size
    n = len(df)

    for i in range(1, n - 1):
        bar = df.iloc[i]
        next_bar = df.iloc[i + 1]

        # ---- 1) 보유 포지션이 있으면 이번 봉에서 청산가/손절/익절 도달 여부 먼저 확인 ----
        if position is not None:
            position, equity, closed_trade = _check_exit_this_bar(
                position, bar, i, equity, symbol_cfg, result, bt_cfg)
            if closed_trade is not None:
                result.trades.append(closed_trade)

        # ---- 2) 신호 계산 (bar i 종가 확정 시점 기준) ----
        start = max(0, i + 2 - window)
        sig_window = df.iloc[start:i + 2]  # 마지막 행(i+1)은 strategy가 "미확정"으로 잘라냄
        signal = strategy.generate_signal(sig_window)

        current_state = (PositionState(position.side, position.quantity, position.entry_price)
                          if position else PositionState(Side.NONE, 0.0, 0.0))
        action = decide_action(current_state, signal.side)

        # ---- 3) 반대 시그널이면 다음 봉 시가에 청산 후 신규 진입 ----
        if action == Action.REVERSE and position is not None:
            exit_price = _apply_slippage(next_bar["open"], side_is_buy=(position.side == Side.SHORT),
                                          slippage_bps=bt_cfg.slippage_bps)
            trade, equity = _close_position(position, exit_price, i + 1, "reverse_signal", equity, bt_cfg)
            result.trades.append(trade)
            position = None

        # ---- 4) 신규 진입 (OPEN 또는 REVERSE 이후) ----
        if action in (Action.OPEN, Action.REVERSE) and position is None:
            position, equity = _try_open_position(signal, next_bar, i + 1, equity, symbol_cfg, risk_cfg, bt_cfg)

        result.equity_curve.append((i, equity))

    result.final_equity = equity
    return result


def _try_open_position(signal, next_bar, entry_index, equity, symbol_cfg, risk_cfg, bt_cfg):
    entry_price = _apply_slippage(next_bar["open"], side_is_buy=(signal.side == Side.LONG),
                                   slippage_bps=bt_cfg.slippage_bps)
    stop_price = compute_stop_price(entry_price, signal.atr, signal.side, risk_cfg.atr_stop_multiplier)

    if not is_stop_safely_inside_liquidation(entry_price, stop_price, symbol_cfg.leverage, signal.side,
                                              risk_cfg.liquidation_safety_margin_pct):
        return None, equity

    min_notional = 5.0  # 백테스트에서는 실제 거래소 조회가 불가하므로 바이낸스 표준 최소값으로 근사
    sizing = compute_position_size(equity, risk_cfg.risk_per_trade_pct, entry_price, stop_price,
                                    symbol_cfg.leverage, min_notional)
    if sizing.quantity <= 0:
        return None, equity

    take_profit_price = compute_take_profit_price(entry_price, stop_price, signal.side, risk_cfg.reward_risk_ratio)
    equity -= sizing.notional * bt_cfg.taker_fee_rate  # 진입 수수료

    position = OpenPosition(signal.side, sizing.quantity, entry_price, stop_price, take_profit_price, entry_index)
    return position, equity


def _check_exit_this_bar(position: OpenPosition, bar, bar_index, equity, symbol_cfg, result: BacktestResult, bt_cfg):
    liq_price = estimate_liquidation_price(position.entry_price, symbol_cfg.leverage, position.side)

    hit_liquidation = ((position.side == Side.LONG and bar["low"] <= liq_price) or
                        (position.side == Side.SHORT and bar["high"] >= liq_price))
    if hit_liquidation:
        result.liquidation_events += 1
        trade, equity = _close_position(position, liq_price, bar_index, "LIQUIDATION", equity, bt_cfg)
        return None, equity, trade

    hit_stop = ((position.side == Side.LONG and bar["low"] <= position.stop_price) or
                (position.side == Side.SHORT and bar["high"] >= position.stop_price))
    hit_tp = ((position.side == Side.LONG and bar["high"] >= position.take_profit_price) or
              (position.side == Side.SHORT and bar["low"] <= position.take_profit_price))

    if hit_stop:
        # 같은 봉에 손절/익절이 동시에 닿을 수 있으면 보수적으로 손절을 먼저 맞았다고 가정
        trade, equity = _close_position(position, position.stop_price, bar_index, "stop_loss", equity, bt_cfg)
        return None, equity, trade

    if hit_tp:
        trade, equity = _close_position(position, position.take_profit_price, bar_index, "take_profit", equity, bt_cfg)
        return None, equity, trade

    return position, equity, None


def _close_position(position: OpenPosition, exit_price, exit_index, reason, equity, bt_cfg):
    if position.side == Side.LONG:
        pnl_usdt = (exit_price - position.entry_price) * position.quantity
    else:
        pnl_usdt = (position.entry_price - exit_price) * position.quantity

    notional = position.entry_price * position.quantity
    fee = notional * bt_cfg.taker_fee_rate if bt_cfg.taker_fee_rate else notional * 0.0005
    pnl_usdt -= fee

    equity_before = equity
    equity += pnl_usdt
    pnl_pct_of_equity = (pnl_usdt / equity_before * 100) if equity_before > 0 else 0.0

    trade = Trade(position.side, position.entry_price, exit_price, position.quantity,
                  position.entry_index, exit_index, reason, pnl_usdt, pnl_pct_of_equity)
    return trade, equity
