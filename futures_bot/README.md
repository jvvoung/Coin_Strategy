# futures_bot — Binance USDT-M Futures 양방향 통합 전략

[strategy_design.md](../strategy_design.md)와 [strategy_analysis_table.md](../strategy_analysis_table.md)에서
"이식 등급 상"으로 평가된 로직들을 결합해서 만든 실제 동작 코드다.

## 전략 로직 (strategies/trend_breakout.py)

기존 65개 전략 중 이식 등급이 높았던 3가지 원형을 AND로 결합했다.

| 구성요소 | 참고한 기존 폴더 | 내용 |
|---|---|---|
| 추세 필터 | 33, 11, 23, 27 | EMA(20) vs EMA(60) 정배열/역배열 |
| 변동성 돌파 | 30, 32 | 전봉 종가 대비 ATR×0.5 이상 이탈 (32번의 "K값 돌파"를 24시간 크립토에 맞게 ATR 기반으로 대체) |
| 모멘텀 확인 | 65개 전반 | RSI가 방향과 같은 쪽 + 같은 방향으로 움직이는 중인지 확인 (기존 코드들의 RSI 용례 그대로 — 역추세 아님) |

세 조건을 모두 만족해야 LONG/SHORT 신호가 나온다. 65개 분석에서 드러난 가장 큰 공통 약점인
"명시적 가격 기반 손절 부재"는 이 전략 자체가 아니라 `risk/` 레이어가 모든 신호에 예외 없이
강제로 적용한다(ATR 기반 손절 + STOP_MARKET 서버 예약).

## 디렉터리 구조

```
futures_bot/
├── config/settings.py       # API키, 심볼/레버리지, 리스크%, 전략 파라미터 — 대부분 여기만 고치면 됨
├── data/                    # ccxt Binance Futures 클라이언트, 캔들 수집
├── indicators/              # MA, RSI, MACD, ATR, Bollinger, 거래대금
├── strategies/              # 시그널 로직 (base_strategy.py 인터페이스 + trend_breakout.py)
├── risk/                    # 포지션사이즈, 손절/익절가, 청산가 안전마진, 일일/연속손실 가드
├── execution/               # 포지션 상태전이 판단(One-way Mode) + 주문 실행
├── backtest/                # 백테스트 엔진 + 성과지표(승률/PF/MDD/Sharpe/청산횟수)
├── logs/                    # trades.csv, errors.log, account_guard_state.json (실행 중 생성)
├── main.py                  # 실거래 진입점
└── run_backtest.py          # 백테스트 진입점 (main.py와 완전히 분리, 서로 호출 안 함)
```

## 설치

```bash
cd futures_bot
pip install -r requirements.txt
cp .env.example .env   # 발급받은 API 키 입력, BINANCE_TESTNET=true 유지
```

## 실행 순서 (반드시 이 순서로— strategy_design.md 9번)

1. **백테스트**
   ```bash
   python run_backtest.py --symbol "BTC/USDT:USDT" --days 180 --train-ratio 0.7
   ```
   TRAIN/TEST 구간을 나눠서 각각 출력한다. **TEST 구간 성과만으로 채택 여부를 판단할 것** —
   TRAIN 성과가 좋아도 TEST가 나쁘면 과최적화다.

2. **파라미터 점검**: `config/settings.py`의 `StrategyConfig`, `RiskConfig` 값을 ±10~20% 흔들어
   같은 백테스트를 다시 돌려보고, 성과가 급격히 무너지면 과최적화 신호이니 채택하지 말 것.

3. **Binance Futures Testnet 실거래 리허설**
   - `.env`의 `BINANCE_TESTNET=true` 상태로 [testnet.binancefuture.com](https://testnet.binancefuture.com)에서
     발급한 키를 넣고 `python main.py` 실행.
   - 계정을 **One-way Mode**로 설정할 것(코드가 One-way Mode를 전제로 동작한다. Hedge Mode 계정이면
     `positionSide` 파라미터가 없어 주문이 거부된다).
   - `logs/trades.csv`, `logs/errors.log`를 보며 진입/청산/에러가 의도대로 기록되는지 확인.

4. **소액 실거래**: Testnet에서 최소 2~4주 또는 충분한 거래 횟수 이상 문제가 없으면
   `.env`를 실계좌 키로 교체하고 `BINANCE_TESTNET=false`로 바꾼 뒤, 계좌 자본의 1~2% 수준의
   소액으로 시작. 이후 단계적으로만 확대한다.

## 주의사항

- **레버리지 계정 자동 청산 위험**은 항상 존재한다. `risk/stop_loss.py`가 손절가와 추정 청산가 사이의
  안전마진을 매 진입 전 확인하지만, 이는 근사치(유지증거금률 구간을 단순화한 공식)다. 실제 청산가는
  Binance의 notional bracket에 따라 달라지므로, 레버리지를 낮게(`config/settings.py`의 `leverage`) 유지하는 것이
  가장 확실한 방어책이다.
- `logs/account_guard_state.json`은 일일 손실 한도·연속 손실 쿨다운 상태를 저장한다. 이 파일을 手動으로
  지우면 안전장치가 리셋되니 주의할 것.
- 이 코드는 교육/개인 연구 목적의 예시이며 수익을 보장하지 않는다. 실거래 손실에 대한 책임은
  사용자 본인에게 있다.
