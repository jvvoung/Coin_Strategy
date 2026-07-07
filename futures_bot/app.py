"""
읽기 전용 Streamlit 대시보드. main.py의 실거래 루프와는 완전히 분리된 파일이며,
config/settings.py와 logs/ 아래 파일들을 조회만 한다 — 여기서 주문을 내거나
봇을 시작/중지하지 않는다 (그건 터미널에서 python main.py로 직접 실행).

실행:
    cd futures_bot
    streamlit run app.py
"""
import os
import time
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from config.settings import CONFIG
from risk.account_guard import AccountGuard
from notifications.telegram_notifier import TelegramNotifier
from data.binance_client import BinanceFuturesClient
from data.candle_fetcher import fetch_historical_candles, fetch_recent_candles
from strategies.trend_breakout import TrendBreakoutStrategy
from backtest.backtest_engine import run_backtest
from backtest.performance_metrics import compute_performance

st.set_page_config(page_title="Futures Bot Dashboard", page_icon="📊", layout="wide")


def _expected_password() -> str:
    """비밀번호 = 현재 시각 YYYYMMDDHH (10자리, 매 시간 바뀜)."""
    return datetime.now().strftime("%Y%m%d%H")


def _require_login():
    if st.session_state.get("authenticated"):
        return

    _, center, _ = st.columns([1, 1, 1])
    with center:
        st.title("🔒 Secret")
        st.caption("이 대시보드는 비밀번호로 보호되어 있습니다.")
        with st.form("login_form"):
            pwd = st.text_input("비밀번호", type="password", max_chars=10, label_visibility="collapsed")
            submitted = st.form_submit_button("입장", width="stretch")
        if submitted:
            if pwd == _expected_password():
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
    st.stop()


_require_login()


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


def _run_symbol_backtest(symbol: str, days: int, train_ratio: float) -> dict:
    """run_backtest.py와 동일한 로직. 과거 캔들을 읽어오기만 하고 주문은 전혀 내지 않는다."""
    symbol_cfg = next(s for s in CONFIG.symbols if s.symbol == symbol)
    client = BinanceFuturesClient(CONFIG)

    since_ms = int((time.time() - days * 86400) * 1000)
    df = fetch_historical_candles(client, symbol, CONFIG.strategy.timeframe, since_ms)
    if len(df) < 50:
        raise ValueError(f"수집된 캔들이 너무 적습니다 ({len(df)}개). 기간을 늘려보세요.")

    split_idx = int(len(df) * train_ratio)
    train_df, test_df = df.iloc[:split_idx], df.iloc[split_idx:]
    strategy = TrendBreakoutStrategy(CONFIG.strategy)

    parts = {}
    for label, part_df in (("TRAIN", train_df), ("TEST", test_df)):
        result = run_backtest(part_df, strategy, symbol_cfg, CONFIG.risk, CONFIG.backtest)
        report = compute_performance(result, CONFIG.backtest.initial_equity_usdt)
        parts[label] = {"range": (str(part_df.index[0]), str(part_df.index[-1])),
                         "report": report, "result": result}

    return {"symbol": symbol, "candle_count": len(df),
            "range": (str(df.index[0]), str(df.index[-1])), "parts": parts}


@st.cache_data(ttl=10, show_spinner=False)
def _fetch_live_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    client = BinanceFuturesClient(CONFIG)
    return fetch_recent_candles(client, symbol, timeframe, limit=limit).reset_index()


def _candlestick_chart(df: pd.DataFrame):
    df = df.copy()
    df["direction"] = df.apply(lambda r: "상승" if r["close"] >= r["open"] else "하락", axis=1)
    color_scale = alt.Scale(domain=["상승", "하락"], range=["#26a69a", "#ef5350"])
    base = alt.Chart(df).encode(x=alt.X("timestamp:T", title=None))
    wick = base.mark_rule().encode(
        y=alt.Y("low:Q", title="가격(USDT)", scale=alt.Scale(zero=False)),
        y2="high:Q",
        color=alt.Color("direction:N", scale=color_scale, legend=None),
    )
    body = base.mark_bar(size=4).encode(
        y="open:Q", y2="close:Q",
        color=alt.Color("direction:N", scale=color_scale, legend=None),
    )
    return (wick + body).properties(height=280)


@st.fragment(run_every="10s")
def _live_price_section():
    live_symbols = [s.symbol for s in CONFIG.symbols if any(k in s.symbol for k in ("BTC", "ETH"))]
    if not live_symbols:
        return

    timeframe_options = ["1m", "5m", "15m", "1h"]
    default_tf = CONFIG.strategy.timeframe if CONFIG.strategy.timeframe in timeframe_options else "15m"
    col_tf, col_n, col_ts = st.columns([1, 1, 2])
    with col_tf:
        tf = st.selectbox("차트 타임프레임", timeframe_options, index=timeframe_options.index(default_tf),
                           key="live_tf")
    with col_n:
        n = st.number_input("캔들 개수", min_value=30, max_value=300, value=100, step=10, key="live_n")
    with col_ts:
        st.caption(f"10초마다 자동 갱신 · 마지막 조회 {datetime.now().strftime('%H:%M:%S')}")

    cols = st.columns(len(live_symbols))
    for symbol, col in zip(live_symbols, cols):
        with col:
            try:
                df = _fetch_live_ohlcv(symbol, tf, int(n))
                last, prev = df.iloc[-1], df.iloc[-2] if len(df) > 1 else df.iloc[-1]
                change_pct = (last["close"] - prev["close"]) / prev["close"] * 100 if prev["close"] else 0.0
                st.metric(symbol.split(":")[0], f"{last['close']:,.2f} USDT", f"{change_pct:+.2f}%")
                st.altair_chart(_candlestick_chart(df), width="stretch")
            except Exception as e:
                st.error(f"{symbol} 시세 조회 실패: {e}")


st.title("📊 Futures Bot Dashboard")
st.caption("읽기 전용 화면입니다. 설정/로그 조회만 하며, 주문 실행이나 봇 시작·중지는 여기서 할 수 없습니다.")

tab_dashboard, tab_strategy, tab_backtest, tab_logs, tab_notification, tab_deploy = st.tabs(
    ["Dashboard", "Strategy", "Backtest", "Logs", "Notification", "Deployment Guide"]
)

# ---------------------------------------------------------------- Dashboard
with tab_dashboard:
    st.subheader("실시간 시세")
    _live_price_section()

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

# ---------------------------------------------------------------- Backtest
with tab_backtest:
    st.subheader("백테스트")
    st.caption(
        "바이낸스에서 과거 캔들만 읽어와 로컬에서 시뮬레이션합니다. 실거래 주문은 전혀 발생하지 않습니다. "
        "기간이 길수록 캔들 수집에 시간이 걸릴 수 있습니다."
    )

    symbol_options = [s.symbol for s in CONFIG.symbols]
    col1, col2, col3 = st.columns(3)
    with col1:
        bt_symbol = st.selectbox("종목", symbol_options)
    with col2:
        bt_days = st.number_input("조회 기간(일)", min_value=7, max_value=730, value=180, step=1)
    with col3:
        bt_train_ratio = st.slider("Train 비율", min_value=0.1, max_value=0.9, value=0.7, step=0.05)

    if st.button("백테스트 실행", type="primary"):
        with st.spinner(f"{bt_symbol} 과거 {bt_days}일 캔들 수집 및 시뮬레이션 실행 중..."):
            try:
                st.session_state["backtest_result"] = _run_symbol_backtest(bt_symbol, bt_days, bt_train_ratio)
            except Exception as e:
                st.session_state["backtest_result"] = None
                st.error(f"백테스트 실행 중 오류: {e}")

    bt = st.session_state.get("backtest_result")
    if not bt:
        st.info("종목/기간을 선택하고 '백테스트 실행'을 눌러주세요.")
    else:
        st.caption(f"{bt['symbol']} · 캔들 {bt['candle_count']}개 ({bt['range'][0]} ~ {bt['range'][1]})")

        col_train, col_test = st.columns(2)
        for label, col in (("TRAIN", col_train), ("TEST", col_test)):
            part = bt["parts"][label]
            report = part["report"]
            with col:
                st.markdown(f"#### {label} 구간")
                st.caption(f"{part['range'][0]} ~ {part['range'][1]}")
                metrics_df = pd.DataFrame([
                    {"지표": "총 거래횟수", "값": str(report.total_trades)},
                    {"지표": "승률", "값": f"{report.win_rate_pct:.2f}%"},
                    {"지표": "평균 손익비(R:R)", "값": f"{report.avg_reward_risk:.2f}"},
                    {"지표": "Profit Factor", "값": f"{report.profit_factor:.2f}"},
                    {"지표": "최대낙폭(MDD)", "값": f"{report.max_drawdown_pct:.2f}%"},
                    {"지표": "Sharpe Ratio", "값": f"{report.sharpe_ratio:.3f}"},
                    {"지표": "Sortino Ratio", "값": f"{report.sortino_ratio:.3f}"},
                    {"지표": "강제청산 발생횟수", "값": str(report.liquidation_events)},
                    {"지표": "최종 자본", "값": f"{report.final_equity:,.2f} USDT"},
                    {"지표": "총 수익률", "값": f"{report.total_return_pct:.2f}%"},
                ])
                st.dataframe(metrics_df, width="stretch", hide_index=True)

        st.warning("TRAIN 구간 성과가 좋아도, 채택 여부는 반드시 TEST 구간 성과만으로 판단하세요 (과최적화 방지).")

        st.markdown("#### TEST 구간 자본 곡선")
        test_curve = bt["parts"]["TEST"]["result"].equity_curve
        if test_curve:
            curve_df = pd.DataFrame(test_curve, columns=["bar_index", "equity"]).set_index("bar_index")
            st.line_chart(curve_df)
        else:
            st.info("TEST 구간에 거래가 없어 자본 곡선을 그릴 수 없습니다.")

        st.markdown("#### TEST 구간 거래 내역")
        test_trades = bt["parts"]["TEST"]["result"].trades
        if test_trades:
            trades_df = pd.DataFrame([
                {
                    "방향": t.side.value, "진입가": t.entry_price, "청산가": t.exit_price,
                    "수량": t.quantity, "손익(USDT)": round(t.pnl_usdt, 2),
                    "손익(%)": round(t.pnl_pct_of_equity, 2), "사유": t.exit_reason,
                }
                for t in test_trades
            ])
            st.dataframe(trades_df, width="stretch", hide_index=True)
        else:
            st.info("TEST 구간에서 발생한 거래가 없습니다.")

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
  `notifications/`, `backtest/`(이 대시보드의 Backtest 탭이 직접 import함), `logs/`(빈 폴더),
  `main.py`, `app.py`, `requirements.txt`
- **업로드 안 함**: `.env`(서버에서 직접 생성), `logs/*.csv`·`*.log`·`*.json`(실행 중 생성),
  `__pycache__/`, `.git/`, `run_backtest.py`(CLI 전용, 이 대시보드가 같은 로직을 내장함)
""")
    st.error("`.env` 파일(API 키, 텔레그램 토큰)은 절대 Git이나 AWS 이미지에 올리지 마세요.")
