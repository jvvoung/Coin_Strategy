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
    atr_stop_multiplier: float = 2.0     # 손절폭 = ATR * 이 배수 (그리드서치 튜닝값, 2026-07-08)
    reward_risk_ratio: float = 2.8       # 익절폭 = 손절폭 * 이 배수 (그리드서치 튜닝값, 2026-07-08)
    liquidation_safety_margin_pct: float = 20.0  # 손절가가 청산가 대비 최소 이만큼(%) 안쪽에 있어야 함


@dataclass(frozen=True)
class StrategyConfig:
    timeframe: str = "15m"
    ema_fast: int = 20
    ema_slow: int = 60
    atr_period: int = 14                   # 손절/익절폭 계산(risk 레이어)에 계속 사용
    bb_period: int = 20                    # 볼린저밴드 돌파 필터 (ATR 돌파 대체)
    bb_num_std: float = 2.5                # 그리드서치 튜닝값 (2026-07-08, BTC 15m 270일 TRAIN/VAL/TEST)
    rsi_period: int = 14
    rsi_long_threshold: float = 58.0       # 이 값 초과 + 상승 중이어야 롱 모멘텀 확인 (튜닝값)
    rsi_short_threshold: float = 42.0      # 이 값 미만 + 하락 중이어야 숏 모멘텀 확인 (튜닝값)

    # regime_hybrid 전용: ADX로 추세장/레인지장을 구분 (2026-07-08 추가)
    adx_period: int = 14
    adx_trend_threshold: float = 25.0      # 이 값 이상이면 추세장 -> trend_breakout 로직
    mr_rsi_oversold: float = 30.0          # 레인지장에서 이 미만이면 평균회귀 LONG 후보
    mr_rsi_overbought: float = 70.0        # 레인지장에서 이 초과면 평균회귀 SHORT 후보

    # 스퀴즈(변동성 압축) 돌파 전제조건: 추세장 진입 시 "돌파 직전 밴드가 눌려있었는지"를
    # 추가로 요구해서 추세 중간의 흔한 가짜돌파를 거른다 (2026-07-09 추가)
    squeeze_enabled: bool = True
    squeeze_lookback: int = 100            # 밴드폭 백분위수 계산에 쓰는 과거 봉 수
    squeeze_percentile: float = 0.2        # 이 백분위수(하위 20%) 이하면 "눌린 상태"로 판정
    squeeze_recent_bars: int = 5           # 돌파 직전 이 봉 수 이내에 스퀴즈가 있었어야 함

    # MFI(거래량 가중 모멘텀) 추가 확인: 추세장 진입 시 가격 방향을 거래량이
    # 실제로 뒷받침하는지 확인 (2026-07-10 추가, RSI와 같이 AND로 결합)
    mfi_enabled: bool = True
    mfi_period: int = 14
    mfi_long_threshold: float = 55.0       # 이 값 초과해야 롱 방향 자금유입 확인
    mfi_short_threshold: float = 45.0      # 이 값 미만이어야 숏 방향 자금유출 확인

    # 레인지장(평균회귀) 진입 로직: %B + II%(거래강도) 기반으로 교체 가능
    # (2026-07-10 추가, 출처: 추세반전 매매법 — 밴드 근접 + 숨은 매수/매도세 확인)
    # A/B 검증 결과 TRAIN/VAL/TEST 전 구간에서 기존 RSI 방식보다 나빠서(2026-07-10)
    # 기본값은 False로 유지. 코드는 남겨두고 필요시 다시 켜서 실험 가능.
    mr_use_pb_ii: bool = False             # True면 %B+II% 방식, False면 기존 RSI 단독 방식
    mr_pb_threshold: float = 0.05          # %B가 0+이값 이하 / 1-이값 이상이면 밴드 근접으로 판정
    ii_period: int = 21                    # Intraday Intensity % 계산 기간

    # 가격-RSI 다이버전스: 추세/레인지 신호가 없을 때(NONE)만 추가로 확인하는
    # 독립적인 세 번째 진입 경로 — 가격은 신저가인데 RSI는 더 높은 저점(강세 다이버전스),
    # 또는 그 반대(약세 다이버전스)일 때 진입 (2026-07-10 추가, 출처: 다이버전스 매매법)
    # A/B 검증 결과 swing_lookback=3이 노이즈에 너무 민감해서(TRAIN 거래 73->368건
    # 폭증, MDD 17.5%->50.4%) 전 구간 대폭 악화. 기본값은 False로 유지, 코드는 보존
    # (swing_lookback을 늘려 재시도할 수 있게).
    divergence_enabled: bool = False
    divergence_swing_lookback: int = 3     # 국소 고점/저점 판정 시 좌우 비교 봉 수
    divergence_recent_bars: int = 10       # 두 번째 스윙포인트가 이 봉 수 이내여야 "신선한" 신호로 인정


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
