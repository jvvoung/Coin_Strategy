"""
모든 하위 전략이 지켜야 하는 공통 인터페이스.
65개 기존 전략을 분석한 결과(strategy_analysis_table.md) 공통적으로 반복된 패턴은:
  - 이동평균 정배열/크로스 기반 추세 필터
  - RSI는 역추세가 아니라 "추세 방향 확인" 용도로만 사용
  - 명시적 가격 기반 손절이 거의 없었다는 점(가장 큰 공통 약점)
이 인터페이스는 시그널 로직과 리스크 로직을 분리해서, 마지막 약점을 risk/ 레이어에서
전략과 무관하게 항상 보정하도록 강제한다.
"""
from dataclasses import dataclass
from enum import Enum


class Side(Enum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"


@dataclass(frozen=True)
class Signal:
    side: Side
    reason: str
    close: float
    atr: float          # risk 레이어가 손절/익절/포지션사이즈 계산에 사용


class Strategy:
    """하위 전략은 이 클래스를 상속하고 generate_signal만 구현하면 된다."""

    name: str = "base"

    def generate_signal(self, df) -> Signal:
        raise NotImplementedError
