"""
전체 설정: API 인증, 심볼/타임프레임, 레버리지, 리스크 파라미터.
값은 여기 기본값을 쓰되, 운영 중 바꿔야 하는 값(심볼, 리스크%)은 이 파일만 고치면 된다.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class SymbolConfig:
    symbol: str            # ccxt 표기, 예: "BTC/USDT:USDT"
    leverage: int
    margin_type: str = "ISOLATED"   # ISOLATED 권장 (한 심볼 청산이 계좌 전체로 번지지 않도록)


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_pct: float = 0.5      # 1회 거래당 계좌 자본 대비 손실 한도 (%)
    max_daily_loss_pct: float = 3.0      # 일일 누적 손실 한도 (%) 도달 시 당일 신규진입 중단
    max_consecutive_losses: int = 4      # 연속 손절 허용 횟수, 초과 시 쿨다운
    cooldown_minutes: int = 120          # 연속손절 초과 시 신규진입 중단 시간(분)
    atr_stop_multiplier: float = 1.5     # 손절폭 = ATR * 이 배수
    reward_risk_ratio: float = 1.8       # 익절폭 = 손절폭 * 이 배수
    liquidation_safety_margin_pct: float = 20.0  # 손절가가 청산가 대비 최소 이만큼(%) 안쪽에 있어야 함


@dataclass(frozen=True)
class StrategyConfig:
    timeframe: str = "15m"
    ema_fast: int = 20
    ema_slow: int = 60
    atr_period: int = 14                   # 손절/익절폭 계산(risk 레이어)에 계속 사용
    bb_period: int = 20                    # 볼린저밴드 돌파 필터 (ATR 돌파 대체)
    bb_num_std: float = 2.0
    rsi_period: int = 14
    rsi_long_threshold: float = 52.0       # 이 값 초과 + 상승 중이어야 롱 모멘텀 확인
    rsi_short_threshold: float = 48.0      # 이 값 미만 + 하락 중이어야 숏 모멘텀 확인


@dataclass(frozen=True)
class NotificationConfig:
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    telegram_enabled: bool = os.getenv("TELEGRAM_ENABLED", "true").lower() == "true"


@dataclass(frozen=True)
class BacktestConfig:
    taker_fee_rate: float = 0.0005          # 진입/청산 왕복 각각에 적용 (바이낸스 USDT-M 기본 taker)
    slippage_bps: float = 2.0               # 체결가에 적용할 슬리피지 (bp = 0.01%)
    funding_rate_per_8h: float = 0.0001     # 평균 펀딩비 근사치(실제 과거 펀딩비 대신 보수적 상수 사용)
    signal_window_size: int = 300           # main.py의 fetch_recent_candles(limit=300)와 동일하게 유지
    initial_equity_usdt: float = 10_000.0


@dataclass(frozen=True)
class AppConfig:
    api_key: str = os.getenv("BINANCE_API_KEY", "")
    api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    testnet: bool = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

    poll_interval_sec: int = 30   # 캔들 확정 여부를 체크하는 주기 (실제 진입판단은 캔들 확정시에만)

    symbols: tuple = field(default_factory=lambda: (
        SymbolConfig(symbol="BTC/USDT:USDT", leverage=5),
        SymbolConfig(symbol="ETH/USDT:USDT", leverage=5),
    ))

    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    notification: NotificationConfig = field(default_factory=NotificationConfig)

    log_dir: str = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


CONFIG = AppConfig()
