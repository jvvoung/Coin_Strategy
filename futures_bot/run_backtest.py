"""
백테스트 실행 진입점. main.py(실거래)와 완전히 분리된 프로세스이며 서로 호출하지 않는다.
사용법:
    python run_backtest.py --symbol BTC/USDT:USDT --days 180 --train-ratio 0.7

Train 구간으로 감(느낌)을 잡더라도, 최종 판단은 반드시 Test 구간 결과로 한다
(strategy_design.md 8.5, 과최적화 방지).
"""
import argparse
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 기본 코드페이지에서도 한글 로그가 깨지지 않도록

from config.settings import CONFIG
from data.binance_client import BinanceFuturesClient
from data.candle_fetcher import fetch_historical_candles
from strategies.trend_breakout import TrendBreakoutStrategy
from backtest.backtest_engine import run_backtest
from backtest.performance_metrics import compute_performance, format_report


def _find_symbol_config(symbol: str):
    for s in CONFIG.symbols:
        if s.symbol == symbol:
            return s
    raise ValueError(f"config.settings.CONFIG.symbols에 {symbol} 설정이 없습니다. settings.py에 추가하세요.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=CONFIG.symbols[0].symbol)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--train-ratio", type=float, default=0.7)
    args = parser.parse_args()

    symbol_cfg = _find_symbol_config(args.symbol)
    client = BinanceFuturesClient(CONFIG)

    since_ms = int((time.time() - args.days * 86400) * 1000)
    print(f"[백테스트] {args.symbol} {CONFIG.strategy.timeframe} 최근 {args.days}일 데이터 수집 중...")
    df = fetch_historical_candles(client, args.symbol, CONFIG.strategy.timeframe, since_ms)
    print(f"[백테스트] 캔들 {len(df)}개 수집 완료 ({df.index[0]} ~ {df.index[-1]})")

    split_idx = int(len(df) * args.train_ratio)
    train_df, test_df = df.iloc[:split_idx], df.iloc[split_idx:]

    strategy = TrendBreakoutStrategy(CONFIG.strategy)

    for label, part_df in (("TRAIN", train_df), ("TEST", test_df)):
        result = run_backtest(part_df, strategy, symbol_cfg, CONFIG.risk, CONFIG.backtest)
        report = compute_performance(result, CONFIG.backtest.initial_equity_usdt)
        print(f"\n===== {label} 구간 ({part_df.index[0]} ~ {part_df.index[-1]}) =====")
        print(format_report(report))

    print("주의: TRAIN 구간 성과가 좋아도 최종 채택 여부는 반드시 TEST 구간 성과로 판단할 것.")


if __name__ == "__main__":
    main()
