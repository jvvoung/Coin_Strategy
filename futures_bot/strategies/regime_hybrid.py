"""
레짐필터 + 평균회귀 하이브리드 전략.

trend_breakout(EMA추세+볼린저돌파+RSI모멘텀) 단독으로는 그리드서치(2026-07-08,
BTC 15m 270일 TRAIN/VAL/TEST)에서 108개 파라미터 조합 전부가 VALIDATION 기준
마이너스였다. TEST 자본곡선을 보면 급락이 아니라 완만한 우하향 — 레인지장에서
가짜돌파에 계속 걸려 잘게 썰리는 패턴이었다.

이 전략은 ADX로 "지금이 추세장인지 레인지장인지"를 먼저 판정해서 로직을 나눈다.
  - 추세장 (ADX >= adx_trend_threshold): trend_breakout과 동일한 로직에 스퀴즈
    전제조건을 추가 — EMA 정배열/역배열 + 볼린저밴드 돌파 + RSI 모멘텀 확인 +
    "돌파 직전에 밴드가 압축(스퀴즈)돼 있었는지"까지 맞아야 진입. 밴드가 계속
    넓은 채로 추세 중간에 발생하는 흔한 가짜돌파를 거르기 위함 (2026-07-09 추가,
    출처: 변동성 돌파 매매법 — 스퀴즈 이후 돌파 시 진입).
    추가로 MFI(거래량 가중 모멘텀)가 같은 방향인지도 확인 — RSI는 가격만 보고
    "힘이 붙었는지"를 판단하지만, MFI는 그 힘을 거래량이 실제로 뒷받침하는지
    확인한다 (2026-07-10 추가, 출처: 추세추종 매매법 — %B+MFI 조합).
  - 레인지장 (ADX < adx_trend_threshold): 반대로 해석 — 볼린저밴드 이탈을
    "돌파 시작"이 아니라 "과도한 이탈이니 되돌아올 것"으로 본다. 기본값은 %B(밴드 내
    상대위치)가 극단(0 근처/1 근처)이면서 II%(거래강도, 봉 안에서 종가가 고저 어느
    쪽에 가깝게 마감했는지를 거래량으로 가중)가 반대 방향을 가리킬 때 — 즉 "가격은
    바닥인데 숨은 매수세가 있다"를 확인해서 반전 방향으로 진입 (2026-07-10 추가,
    출처: 추세반전 매매법 — W/M 패턴의 실전 규칙화 버전). mr_use_pb_ii=False로 두면
    이전의 RSI 단독 방식으로 되돌아간다(A/B 비교용).

세 번째 독립 경로로 가격-RSI 다이버전스를 추가한다: 위 둘 다 신호가 없을 때만 확인한다
(2026-07-10 추가, 출처: 다이버전스 매매법). 좌우 divergence_swing_lookback봉씩 비교해서
국소 저점/고점(스윙포인트)을 찾고, 가장 최근 두 스윙포인트를 비교한다.
  - 강세 다이버전스: 가격은 더 낮은 저점을 찍었는데 RSI는 더 높은 저점 -> LONG
  - 약세 다이버전스: 가격은 더 높은 고점을 찍었는데 RSI는 더 낮은 고점 -> SHORT
이건 지연지표(가격 패턴)가 아니라 선행성 신호(모멘텀 약화)라 trend_regime/range_regime과
질적으로 다른 정보를 준다.

손절/익절/포지션사이즈는 이 모듈이 관여하지 않고 risk/ 레이어가 전담한다
(base_strategy.py 설계 원칙 그대로 유지 — 다이버전스도 예외 없이 동일한 ATR 기반 손절을 쓴다).
"""
import pandas as pd

from strategies.base_strategy import Signal, Side, Strategy
from indicators.moving_average import ema
from indicators.momentum import rsi
from indicators.volatility import atr as atr_indicator, bollinger_bands, bollinger_bandwidth
from indicators.trend_strength import adx as adx_indicator
from indicators.volume import money_flow_index, intraday_intensity_pct
from config.settings import StrategyConfig


class RegimeHybridStrategy(Strategy):
    name = "regime_hybrid"

    def __init__(self, cfg: StrategyConfig):
        self.cfg = cfg

    def _min_bars_required(self) -> int:
        bars = [self.cfg.ema_slow, self.cfg.atr_period, self.cfg.bb_period,
                self.cfg.rsi_period, self.cfg.adx_period]
        if self.cfg.squeeze_enabled:
            bars.append(self.cfg.squeeze_lookback)
        if self.cfg.mfi_enabled:
            bars.append(self.cfg.mfi_period)
        if self.cfg.mr_use_pb_ii:
            bars.append(self.cfg.ii_period)
        if self.cfg.divergence_enabled:
            bars.append(self.cfg.divergence_recent_bars + 2 * self.cfg.divergence_swing_lookback)
        return max(bars) + 5

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
        adx_series, _, _ = adx_indicator(closed, self.cfg.adx_period)
        mfi_series = money_flow_index(closed, self.cfg.mfi_period) if self.cfg.mfi_enabled else None
        ii_series = intraday_intensity_pct(closed, self.cfg.ii_period) if self.cfg.mr_use_pb_ii else None

        last_close = close.iloc[-1]
        last_atr = atr_series.iloc[-1]
        breakout_up = upper_band.iloc[-2]   # 직전 확정봉까지의 밴드로 계산(전방참조 방지)
        breakout_down = lower_band.iloc[-2]
        last_rsi = rsi_series.iloc[-1]
        prev_rsi = rsi_series.iloc[-2]
        last_adx = adx_series.iloc[-1]
        last_mfi = mfi_series.iloc[-1] if mfi_series is not None else None
        last_ii = ii_series.iloc[-1] if ii_series is not None else None

        if (pd.isna(last_atr) or pd.isna(breakout_up) or pd.isna(breakout_down)
                or pd.isna(last_rsi) or pd.isna(prev_rsi) or pd.isna(last_adx)
                or (self.cfg.mfi_enabled and pd.isna(last_mfi))
                or (self.cfg.mr_use_pb_ii and pd.isna(last_ii))):
            return Signal(Side.NONE, "indicator_warmup", last_close, float("nan"))

        squeeze_triggered = self._was_squeezed_recently(close)

        if last_adx >= self.cfg.adx_trend_threshold:
            signal = self._trend_signal(last_close, last_atr, breakout_up, breakout_down,
                                         ema_fast.iloc[-1], ema_slow.iloc[-1], last_rsi, prev_rsi,
                                         squeeze_triggered, last_mfi)
        else:
            signal = self._mean_reversion_signal(last_close, last_atr, breakout_up, breakout_down,
                                                  last_rsi, last_ii)

        if signal.side != Side.NONE or not self.cfg.divergence_enabled:
            return signal

        return self._divergence_signal(closed, rsi_series, last_close, last_atr)

    def _was_squeezed_recently(self, close: pd.Series) -> bool:
        """돌파 직전 squeeze_recent_bars 봉 이내에 밴드폭이 자체 과거 분포의
        하위 squeeze_percentile 이하로 압축된 적이 있었는지 확인. 현재(-1) 봉은
        이미 돌파로 밴드가 벌어져 있을 수 있으므로 제외하고 직전 확정봉(-2)까지만 본다."""
        if not self.cfg.squeeze_enabled:
            return True

        bandwidth = bollinger_bandwidth(close, self.cfg.bb_period, self.cfg.bb_num_std)
        threshold = bandwidth.rolling(self.cfg.squeeze_lookback,
                                       min_periods=self.cfg.squeeze_lookback).quantile(self.cfg.squeeze_percentile)
        was_squeezed = bandwidth <= threshold

        window = was_squeezed.iloc[-(1 + self.cfg.squeeze_recent_bars):-1]
        return bool(window.any()) if len(window) > 0 else False

    def _trend_signal(self, last_close, last_atr, breakout_up, breakout_down,
                       ema_fast_last, ema_slow_last, last_rsi, prev_rsi, squeeze_triggered,
                       last_mfi) -> Signal:
        trend_up = ema_fast_last > ema_slow_last
        trend_down = ema_fast_last < ema_slow_last
        rsi_bullish = last_rsi > self.cfg.rsi_long_threshold and last_rsi > prev_rsi
        rsi_bearish = last_rsi < self.cfg.rsi_short_threshold and last_rsi < prev_rsi

        if self.cfg.mfi_enabled:
            mfi_bullish = last_mfi > self.cfg.mfi_long_threshold
            mfi_bearish = last_mfi < self.cfg.mfi_short_threshold
        else:
            mfi_bullish = mfi_bearish = True

        if not squeeze_triggered:
            return Signal(Side.NONE, "trend_regime:no_squeeze", last_close, last_atr)

        if last_close > breakout_up and trend_up and rsi_bullish and mfi_bullish:
            return Signal(Side.LONG, "trend_regime:squeeze+ema_uptrend+bb_breakout_up+rsi_bullish+mfi_bullish",
                          last_close, last_atr)
        if last_close < breakout_down and trend_down and rsi_bearish and mfi_bearish:
            return Signal(Side.SHORT, "trend_regime:squeeze+ema_downtrend+bb_breakout_down+rsi_bearish+mfi_bearish",
                          last_close, last_atr)
        return Signal(Side.NONE, "trend_regime:no_condition_met", last_close, last_atr)

    def _mean_reversion_signal(self, last_close, last_atr, breakout_up, breakout_down, last_rsi, last_ii) -> Signal:
        if self.cfg.mr_use_pb_ii:
            return self._mean_reversion_pb_ii(last_close, last_atr, breakout_up, breakout_down, last_ii)
        return self._mean_reversion_rsi(last_close, last_atr, breakout_up, breakout_down, last_rsi)

    def _mean_reversion_pb_ii(self, last_close, last_atr, breakout_up, breakout_down, last_ii) -> Signal:
        band_range = breakout_up - breakout_down
        if band_range <= 0:
            return Signal(Side.NONE, "range_regime:invalid_band", last_close, last_atr)
        pb = (last_close - breakout_down) / band_range  # %B: 0=하단, 1=상단

        near_lower = pb <= self.cfg.mr_pb_threshold
        near_upper = pb >= (1 - self.cfg.mr_pb_threshold)

        if near_lower and last_ii > 0:
            return Signal(Side.LONG, "range_regime:pb_near_lower+ii_positive_fade", last_close, last_atr)
        if near_upper and last_ii < 0:
            return Signal(Side.SHORT, "range_regime:pb_near_upper+ii_negative_fade", last_close, last_atr)
        return Signal(Side.NONE, "range_regime:no_condition_met", last_close, last_atr)

    def _mean_reversion_rsi(self, last_close, last_atr, breakout_up, breakout_down, last_rsi) -> Signal:
        oversold = last_rsi < self.cfg.mr_rsi_oversold
        overbought = last_rsi > self.cfg.mr_rsi_overbought

        if last_close < breakout_down and oversold:
            return Signal(Side.LONG, "range_regime:bb_lower_break+rsi_oversold_fade", last_close, last_atr)
        if last_close > breakout_up and overbought:
            return Signal(Side.SHORT, "range_regime:bb_upper_break+rsi_overbought_fade", last_close, last_atr)
        return Signal(Side.NONE, "range_regime:no_condition_met", last_close, last_atr)

    def _divergence_signal(self, closed: pd.DataFrame, rsi_series: pd.Series,
                            last_close: float, last_atr: float) -> Signal:
        lookback = self.cfg.divergence_swing_lookback
        low = closed["low"].values
        high = closed["high"].values
        rsi_values = rsi_series.values
        n = len(closed)
        recent_cutoff = n - self.cfg.divergence_recent_bars

        swing_lows = self._find_confirmed_swings(low, lookback, find_min=True)
        if len(swing_lows) >= 2:
            i1, i2 = swing_lows[-2], swing_lows[-1]
            if i2 >= recent_cutoff and not (pd.isna(rsi_values[i1]) or pd.isna(rsi_values[i2])):
                price_lower_low = low[i2] < low[i1]
                rsi_higher_low = rsi_values[i2] > rsi_values[i1]
                if price_lower_low and rsi_higher_low:
                    return Signal(Side.LONG, "divergence:bullish_price_lower_low_rsi_higher_low",
                                  last_close, last_atr)

        swing_highs = self._find_confirmed_swings(high, lookback, find_min=False)
        if len(swing_highs) >= 2:
            i1, i2 = swing_highs[-2], swing_highs[-1]
            if i2 >= recent_cutoff and not (pd.isna(rsi_values[i1]) or pd.isna(rsi_values[i2])):
                price_higher_high = high[i2] > high[i1]
                rsi_lower_high = rsi_values[i2] < rsi_values[i1]
                if price_higher_high and rsi_lower_high:
                    return Signal(Side.SHORT, "divergence:bearish_price_higher_high_rsi_lower_high",
                                  last_close, last_atr)

        return Signal(Side.NONE, "divergence:no_pattern", last_close, last_atr)

    @staticmethod
    def _find_confirmed_swings(values, lookback: int, find_min: bool) -> list:
        """좌우 lookback봉과 비교해 국소 극값인 위치의 정수 인덱스 리스트.
        마지막 lookback개 봉은 오른쪽 비교 대상이 부족해 아직 확정할 수 없으므로 제외한다."""
        n = len(values)
        confirmable_end = n - lookback
        swings = []
        for i in range(lookback, confirmable_end):
            window = values[i - lookback:i + lookback + 1]
            center = values[i]
            if find_min:
                if center <= window.min():
                    swings.append(i)
            else:
                if center >= window.max():
                    swings.append(i)
        return swings
