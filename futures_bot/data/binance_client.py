"""
Binance USDT-M Futures ccxt 클라이언트 래퍼.
- One-way Mode 전제 (헤지모드 아님, positionSide 파라미터 사용 안 함)
- rate limit / 일시적 네트워크 오류에 대한 재시도를 한 곳에서 처리해서
  strategies/execution 쪽 코드가 예외처리를 반복하지 않도록 한다.
"""
import time
import ccxt

from config.settings import CONFIG, SymbolConfig


RETRYABLE_EXCEPTIONS = (
    ccxt.NetworkError,
    ccxt.RequestTimeout,
    ccxt.ExchangeNotAvailable,
    ccxt.DDoSProtection,
)


class BinanceFuturesClient:
    def __init__(self, config=CONFIG):
        self.config = config
        self.exchange = ccxt.binance({
            "apiKey": config.api_key,
            "secret": config.api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",
            },
        })
        if config.testnet:
            self.exchange.set_sandbox_mode(True)

        self._markets_loaded = False

    def load_markets(self):
        if not self._markets_loaded:
            self.call(self.exchange.load_markets)
            self._markets_loaded = True

    def call(self, fn, *args, max_retries=3, backoff_sec=2, **kwargs):
        """모든 ccxt 호출은 이 메서드를 통해서만 실행한다 (재시도 지점 단일화)."""
        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except RETRYABLE_EXCEPTIONS as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(backoff_sec * attempt)
                    continue
            except ccxt.ExchangeError:
                # 주문거부/잔고부족 등은 재시도해도 결과가 같으므로 즉시 올린다.
                raise
        raise last_err

    def ensure_symbol_setup(self, symbol_cfg: SymbolConfig):
        """전략 시작 시 1회만 호출: 레버리지/마진타입 설정. 이미 포지션이 있으면
        거부(ExchangeError)될 수 있어 그 경우는 무시하고 넘어간다(기존 설정 유지)."""
        self.load_markets()
        market = self.exchange.market(symbol_cfg.symbol)
        try:
            self.call(self.exchange.set_margin_mode, symbol_cfg.margin_type.lower(), symbol_cfg.symbol)
        except ccxt.ExchangeError as e:
            if "No need to change margin type" not in str(e):
                print(f"[WARN] {symbol_cfg.symbol} 마진타입 설정 실패(무시하고 진행): {e}")
        try:
            self.call(self.exchange.set_leverage, symbol_cfg.leverage, symbol_cfg.symbol)
        except ccxt.ExchangeError as e:
            print(f"[WARN] {symbol_cfg.symbol} 레버리지 설정 실패(무시하고 진행): {e}")
        return market

    def fetch_ohlcv(self, symbol, timeframe, limit=300, since=None):
        return self.call(self.exchange.fetch_ohlcv, symbol, timeframe=timeframe, limit=limit, since=since)

    def fetch_position(self, symbol):
        """One-way Mode 기준 현재 포지션 1개(없으면 None)를 반환."""
        positions = self.call(self.exchange.fetch_positions, [symbol])
        for p in positions:
            contracts = float(p.get("contracts") or 0)
            if contracts != 0:
                return p
        return None

    def fetch_balance_usdt(self):
        balance = self.call(self.exchange.fetch_balance)
        return float(balance.get("USDT", {}).get("total") or 0)

    def fetch_open_orders(self, symbol):
        return self.call(self.exchange.fetch_open_orders, symbol)

    def fetch_order(self, order_id, symbol):
        return self.call(self.exchange.fetch_order, order_id, symbol)

    def cancel_order(self, order_id, symbol):
        return self.call(self.exchange.cancel_order, order_id, symbol)

    def create_market_order(self, symbol, side, amount, reduce_only=False):
        params = {"reduceOnly": reduce_only}
        return self.call(self.exchange.create_order, symbol, "market", side, amount, None, params)

    def create_stop_market_order(self, symbol, side, amount, stop_price, reduce_only=True):
        params = {"stopPrice": stop_price, "reduceOnly": reduce_only, "closePosition": False}
        return self.call(self.exchange.create_order, symbol, "STOP_MARKET", side, amount, None, params)

    def create_take_profit_market_order(self, symbol, side, amount, stop_price, reduce_only=True):
        params = {"stopPrice": stop_price, "reduceOnly": reduce_only, "closePosition": False}
        return self.call(self.exchange.create_order, symbol, "TAKE_PROFIT_MARKET", side, amount, None, params)

    def amount_to_precision(self, symbol, amount):
        return float(self.exchange.amount_to_precision(symbol, amount))

    def price_to_precision(self, symbol, price):
        return float(self.exchange.price_to_precision(symbol, price))

    def min_notional(self, symbol):
        market = self.exchange.market(symbol)
        limits = market.get("limits", {})
        return float((limits.get("cost") or {}).get("min") or 5.0)
