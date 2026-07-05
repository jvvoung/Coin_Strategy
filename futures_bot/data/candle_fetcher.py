"""
OHLCV 캔들 수집. 실거래(main.py)와 백테스트(backtest/)가 동일한 DataFrame 스키마를
공유해야 strategies/의 시그널 함수를 그대로 재사용할 수 있다.
"""
import pandas as pd


COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def ohlcv_to_dataframe(raw_ohlcv) -> pd.DataFrame:
    df = pd.DataFrame(raw_ohlcv, columns=COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    return df


def fetch_recent_candles(client, symbol, timeframe, limit=300) -> pd.DataFrame:
    """가장 최근 limit개 캔들. 마지막 행은 아직 진행 중인(미확정) 캔들일 수 있으므로
    시그널 계산 시 반드시 완결된 캔들만 쓰도록 strategies 쪽에서 마지막 행을 제외한다."""
    raw = client.fetch_ohlcv(symbol, timeframe, limit=limit)
    return ohlcv_to_dataframe(raw)


def fetch_historical_candles(client, symbol, timeframe, since_ms, until_ms=None, page_limit=1000) -> pd.DataFrame:
    """백테스트용 장기간 캔들 수집. since_ms부터 until_ms(또는 현재)까지 페이지네이션."""
    all_rows = []
    cursor = since_ms
    while True:
        raw = client.fetch_ohlcv(symbol, timeframe, limit=page_limit, since=cursor)
        if not raw:
            break
        all_rows.extend(raw)
        last_ts = raw[-1][0]
        if len(raw) < page_limit:
            break
        if until_ms and last_ts >= until_ms:
            break
        cursor = last_ts + 1

    df = ohlcv_to_dataframe(all_rows)
    if until_ms:
        df = df[df.index <= pd.to_datetime(until_ms, unit="ms", utc=True)]
    return df
