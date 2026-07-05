"""
65개 기존 전략 분석(strategy_analysis_table.md)에서 이식 등급 "상"으로 평가된
로직들의 핵심 아이디어를 결합한 통합 Long/Short 진입 전략.

결합한 3가지 원형:
  1. 추세 필터: EMA(fast) vs EMA(slow) 정배열/역배열 (폴더 33, 11, 23, 27 계열)
  2. 변동성 돌파: 볼린저밴드 상/하단 이탈 시 진입 (폴더 30, 32 계열 — 원래는 ATR 배수
     돌파를 썼으나, 같은 "최근 변동성 대비 이탈" 성격이라 표현을 볼린저밴드로 교체)
  3. 모멘텀 확인 필터: RSI가 방향과 같은 쪽에 있고 같은 방향으로 움직이는 중인지
     확인 (65개 전략 전반에서 RSI는 역추세가 아니라 항상 이 용도로만 쓰였음)

이 3개를 모두 만족해야 신호가 발생하도록 AND 결합해서, 단일 지표 신호보다
휩쏘(가짜 신호) 빈도를 낮추는 것이 목표다. 손절/익절/포지션사이즈는 이 모듈이
관여하지 않고 risk/ 레이어가 전담한다(설계 원칙: 전략 로직과 리스크 로직 분리).
ATR은 진입 신호에는 더 이상 쓰이지 않지만, risk 레이어의 손절폭 계산에 필요해서
계속 계산해 Signal.atr로 넘긴다.
"""
import pandas as pd

from strategies.base_strategy import Signal, Side, Strategy
from indicators.moving_average import ema
from indicators.momentum import rsi
from indicators.volatility import atr as atr_indicator, bollinger_bands
from config.settings import StrategyConfig


class TrendBreakoutStrategy(Strategy):
    name = "trend_breakout"

    def __init__(self, cfg: StrategyConfig):
        self.cfg = cfg

    def _min_bars_required(self) -> int:
        return max(self.cfg.ema_slow, self.cfg.atr_period, self.cfg.bb_period, self.cfg.rsi_period) + 5

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """df는 아직 확정되지 않은 마지막(진행중) 캔들을 포함할 수 있으므로
        여기서 마지막 행을 제외하고 '확정된 캔들'만 사용한다."""
        closed = df.iloc[:-1] if len(df) > 0 else df
        if len(closed) < self._min_bars_required():
            return Signal(Side.NONE, "insufficient_data", float("nan"), float("nan"))

        close = closed["close"]
        ema_fast = ema(close, self.cfg.ema_fast)
        ema_slow = ema(close, self.cfg.ema_slow)
        atr_series = atr_indicator(closed, self.cfg.atr_period)
        upper_band, _, lower_band = bollinger_bands(close, self.cfg.bb_period, self.cfg.bb_num_std)
        rsi_series = rsi(close, self.cfg.rsi_period)

        last_close = close.iloc[-1]
        last_atr = atr_series.iloc[-1]
        # 돌파선은 "직전 확정봉까지의" 밴드로 계산(마지막 종가가 자기 자신의 밴드에 영향주지 않도록 전방참조 방지)
        breakout_up = upper_band.iloc[-2]
        breakout_down = lower_band.iloc[-2]
        last_rsi = rsi_series.iloc[-1]
        prev_rsi = rsi_series.iloc[-2]

        if pd.isna(last_atr) or pd.isna(breakout_up) or pd.isna(breakout_down) or pd.isna(last_rsi) or pd.isna(prev_rsi):
            return Signal(Side.NONE, "indicator_warmup", last_close, float("nan"))

        trend_up = ema_fast.iloc[-1] > ema_slow.iloc[-1]
        trend_down = ema_fast.iloc[-1] < ema_slow.iloc[-1]

        rsi_bullish = last_rsi > self.cfg.rsi_long_threshold and last_rsi > prev_rsi
        rsi_bearish = last_rsi < self.cfg.rsi_short_threshold and last_rsi < prev_rsi

        if last_close > breakout_up and trend_up and rsi_bullish:
            return Signal(Side.LONG, "ema_uptrend+bb_breakout_up+rsi_bullish", last_close, last_atr)

        if last_close < breakout_down and trend_down and rsi_bearish:
            return Signal(Side.SHORT, "ema_downtrend+bb_breakout_down+rsi_bearish", last_close, last_atr)

        return Signal(Side.NONE, "no_condition_met", last_close, last_atr)
