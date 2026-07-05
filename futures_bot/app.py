"""
읽기 전용 Streamlit 대시보드. main.py의 실거래 루프와는 완전히 분리된 파일이며,
config/settings.py와 logs/ 아래 파일들을 조회만 한다 — 여기서 주문을 내거나
봇을 시작/중지하지 않는다 (그건 터미널에서 python main.py로 직접 실행).

실행:
    cd futures_bot
    streamlit run app.py
"""
import os

import pandas as pd
import streamlit as st

from config.settings import CONFIG
from risk.account_guard import AccountGuard
from notifications.telegram_notifier import TelegramNotifier

st.set_page_config(page_title="Futures Bot Dashboard", page_icon="📊", layout="wide")


def _mask_secret(value: str) -> str:
    if not value:
        return "(미설정)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def _load_daily_pnl_pct() -> float:
    try:
        guard = AccountGuard(CONFIG.log_dir, CONFIG.risk.max_daily_loss_pct,
                              CONFIG.risk.max_consecutive_losses, CONFIG.risk.cooldown_minutes)
        return guard.daily_pnl_pct()
    except Exception:
        return 0.0


def _read_trades_csv(n: int) -> pd.DataFrame:
    path = os.path.join(CONFIG.log_dir, "trades.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    return df.tail(n).iloc[::-1].reset_index(drop=True)


def _read_error_lines(n: int) -> list:
    path = os.path.join(CONFIG.log_dir, "errors.log")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return [line.rstrip("\n") for line in lines[-n:]][::-1]


st.title("📊 Futures Bot Dashboard")
st.caption("읽기 전용 화면입니다. 설정/로그 조회만 하며, 주문 실행이나 봇 시작·중지는 여기서 할 수 없습니다.")

tab_dashboard, tab_strategy, tab_logs, tab_notification, tab_deploy = st.tabs(
    ["Dashboard", "Strategy", "Logs", "Notification", "Deployment Guide"]
)

# ---------------------------------------------------------------- Dashboard
with tab_dashboard:
    st.subheader("실행 모드")
    col1, col2, col3 = st.columns(3)
    col1.metric("모드", "Testnet" if CONFIG.testnet else "실계좌")
    col2.metric("타임프레임", CONFIG.strategy.timeframe)
    col3.metric("폴링 주기", f"{CONFIG.poll_interval_sec}초")
    if not CONFIG.testnet:
        st.warning("현재 실계좌(BINANCE_TESTNET=false) 설정입니다. 실제 자금으로 주문이 나갑니다.")

    st.subheader("대상 종목")
    symbols_df = pd.DataFrame([
        {"심볼": s.symbol, "레버리지": f"{s.leverage}x", "마진타입": s.margin_type}
        for s in CONFIG.symbols
    ])
    st.dataframe(symbols_df, width='stretch', hide_index=True)

    st.subheader("리스크 설정")
    risk = CONFIG.risk
    risk_df = pd.DataFrame([
        {"항목": "1회 거래당 손실 한도", "값": f"{risk.risk_per_trade_pct}%"},
        {"항목": "일일 손실 한도", "값": f"{risk.max_daily_loss_pct}%"},
        {"항목": "연속 손절 허용 횟수", "값": f"{risk.max_consecutive_losses}회"},
        {"항목": "쿨다운 시간", "값": f"{risk.cooldown_minutes}분"},
        {"항목": "손절폭", "값": f"ATR × {risk.atr_stop_multiplier}"},
        {"항목": "익절폭 (Risk:Reward)", "값": f"손절폭 × {risk.reward_risk_ratio}"},
        {"항목": "청산가 안전마진", "값": f"{risk.liquidation_safety_margin_pct}%"},
    ])
    st.dataframe(risk_df, width='stretch', hide_index=True)

    st.subheader("오늘 손익률")
    daily_pnl = _load_daily_pnl_pct()
    st.metric("일일 누적 손익 (계좌자본 대비 %)", f"{daily_pnl:+.2f}%")
    st.caption("logs/account_guard_state.json 기준. 봇이 아직 한 번도 실행되지 않았다면 0%로 표시됩니다.")

# ---------------------------------------------------------------- Strategy
with tab_strategy:
    cfg = CONFIG.strategy
    st.subheader("전략: trend_breakout")
    st.markdown(
        "EMA 추세 필터 + 볼린저밴드 돌파 + RSI 모멘텀 확인, 3개 조건을 **모두** 만족해야 신호가 발생합니다 "
        "(AND 결합 — 단일 지표 신호보다 휩쏘를 줄이는 목적)."
    )

    col_long, col_short = st.columns(2)
    with col_long:
        st.markdown("### 🟢 LONG 진입 조건")
        st.markdown(f"""
- EMA{cfg.ema_fast} > EMA{cfg.ema_slow} (상승 추세)
- 종가 > 볼린저밴드 상단 (기간 {cfg.bb_period}, {cfg.bb_num_std}σ)
- RSI({cfg.rsi_period}) > {cfg.rsi_long_threshold} 이고 상승 중
""")
    with col_short:
        st.markdown("### 🔴 SHORT 진입 조건")
        st.markdown(f"""
- EMA{cfg.ema_fast} < EMA{cfg.ema_slow} (하락 추세)
- 종가 < 볼린저밴드 하단 (기간 {cfg.bb_period}, {cfg.bb_num_std}σ)
- RSI({cfg.rsi_period}) < {cfg.rsi_short_threshold} 이고 하락 중
""")

    st.subheader("손절 / 익절 기준")
    risk = CONFIG.risk
    st.markdown(f"""
- 손절가 = 진입가 ∓ ATR({cfg.atr_period}) × {risk.atr_stop_multiplier}
- 익절가 = 진입가 ∓ (손절폭 × {risk.reward_risk_ratio})
- 포지션 수량은 "1회 손실 한도({risk.risk_per_trade_pct}% of 계좌자본)"를 손절폭으로 역산해서 결정
- 진입 전 손절가가 추정 청산가보다 최소 {risk.liquidation_safety_margin_pct}% 안쪽에 있는지 확인 (아니면 진입 스킵)
""")
    st.caption("자세한 설계 배경은 README.md, 전체 흐름은 FLOW.md 참고.")

# ---------------------------------------------------------------- Logs
with tab_logs:
    st.subheader("최근 거래 로그 (trades.csv)")
    n_trades = st.slider("표시할 최근 거래 수", min_value=10, max_value=200, value=50, step=10)
    trades_df = _read_trades_csv(n_trades)
    if trades_df.empty:
        st.info("아직 거래 기록이 없습니다 (logs/trades.csv 없음). 봇을 실행하면 여기 쌓입니다.")
    else:
        st.dataframe(trades_df, width='stretch', hide_index=True)

    st.subheader("최근 에러 로그 (errors.log)")
    n_errors = st.slider("표시할 최근 에러 줄 수", min_value=10, max_value=200, value=30, step=10)
    error_lines = _read_error_lines(n_errors)
    if not error_lines:
        st.success("에러 로그가 없습니다.")
    else:
        st.code("\n".join(error_lines), language="text")

    if st.button("새로고침"):
        st.rerun()

# ---------------------------------------------------------------- Notification
with tab_notification:
    st.subheader("텔레그램 알림 설정 상태")
    notif = CONFIG.notification
    notifier = TelegramNotifier(notif.telegram_bot_token, notif.telegram_chat_id, notif.telegram_enabled)

    if notifier.enabled:
        st.success("텔레그램 알림 활성화됨")
    else:
        st.warning("텔레그램 알림 비활성화됨 (TELEGRAM_ENABLED=false 이거나 토큰/chat_id 미설정)")

    info_df = pd.DataFrame([
        {"항목": "TELEGRAM_ENABLED", "값": str(notif.telegram_enabled)},
        {"항목": "TELEGRAM_BOT_TOKEN", "값": _mask_secret(notif.telegram_bot_token)},
        {"항목": "TELEGRAM_CHAT_ID", "값": _mask_secret(notif.telegram_chat_id)},
    ])
    st.dataframe(info_df, width='stretch', hide_index=True)
    st.caption("토큰/chat_id는 앞 4자리·뒤 4자리만 표시하고 나머지는 마스킹합니다.")

    st.markdown("""
**알림이 오는 시점**: 진입 성공, 청산(자동 SL/TP 체결 포함), 반전, 진입 차단, 진입 스킵, 에러 발생 시.
자세한 내용은 [FLOW.md](FLOW.md) 참고.
""")

# ---------------------------------------------------------------- Deployment Guide
with tab_deploy:
    st.subheader("로컬 실행 방법")
    st.code("""cd futures_bot
pip install -r requirements.txt
cp .env.example .env   # API 키/텔레그램 값 입력 (BINANCE_TESTNET=true 유지 권장)

# 이 대시보드 실행
streamlit run app.py

# 실거래 봇 실행 (별도 터미널)
python main.py
""", language="bash")

    st.warning(
        "이 대시보드에는 봇을 시작/중지하거나 주문을 내는 버튼이 없습니다. "
        "실거래 루프는 반드시 별도 터미널에서 `python main.py`로 직접 실행하세요."
    )

    st.subheader("AWS 업로드 시 필요한 파일")
    st.markdown("자세한 목록은 `futures_bot/AWS_UPLOAD_FILES.txt`를 참고하세요. 요약:")
    st.markdown("""
- **업로드**: `config/`, `data/`, `indicators/`, `strategies/`, `risk/`, `execution/`,
  `notifications/`, `logs/`(빈 폴더), `main.py`, `app.py`, `requirements.txt`
- **업로드 안 함**: `.env`(서버에서 직접 생성), `logs/*.csv`·`*.log`·`*.json`(실행 중 생성),
  `__pycache__/`, `.git/`, `backtest/`·`run_backtest.py`(로컬 검증용, 서버에 불필요)
""")
    st.error("`.env` 파일(API 키, 텔레그램 토큰)은 절대 Git이나 AWS 이미지에 올리지 마세요.")
