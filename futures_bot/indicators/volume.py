import pandas as pd


def quote_volume(df: pd.DataFrame) -> pd.Series:
    """대략적인 거래대금(종가*거래량). 유동성 필터에 사용."""
    return df["close"] * df["volume"]


def average_quote_volume(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return quote_volume(df).rolling(window=period, min_periods=period).mean()
