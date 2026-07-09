import pandas as pd


def quote_volume(df: pd.DataFrame) -> pd.Series:
    """대략적인 거래대금(종가*거래량). 유동성 필터에 사용."""
    return df["close"] * df["volume"]


def average_quote_volume(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return quote_volume(df).rolling(window=period, min_periods=period).mean()


def money_flow_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """MFI(Money Flow Index) — RSI와 비슷하지만 거래량으로 가중한 모멘텀.
    가격만으로는 안 보이는 "거래량이 실제로 뒷받침하는 방향"을 확인하는 용도."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    raw_money_flow = typical_price * df["volume"]
    price_diff = typical_price.diff()

    positive_flow = raw_money_flow.where(price_diff > 0, 0.0)
    negative_flow = raw_money_flow.where(price_diff < 0, 0.0)

    positive_sum = positive_flow.rolling(window=period, min_periods=period).sum()
    negative_sum = negative_flow.rolling(window=period, min_periods=period).sum()

    money_ratio = positive_sum / negative_sum.replace(0, float("nan"))
    return 100 - (100 / (1 + money_ratio))


def intraday_intensity_pct(df: pd.DataFrame, period: int = 21) -> pd.Series:
    """Intraday Intensity % (Tom Aspray) — 봉 하나하나에서 종가가 고저 범위의 어느 쪽에
    가깝게 마감했는지를 거래량으로 가중해 누적한다. 양수=매수세 우위, 음수=매도세 우위.
    가격은 밴드 하단을 이탈했는데 이 값이 양수면 "숨은 매수세"로 해석해 반전 신호로 쓴다."""
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    bar_range = (high - low).replace(0, float("nan"))
    raw_ii = ((close - low) - (high - close)) / bar_range
    ii_volume = raw_ii * volume

    volume_sum = volume.rolling(window=period, min_periods=period).sum()
    return ii_volume.rolling(window=period, min_periods=period).sum() / volume_sum.replace(0, float("nan")) * 100
