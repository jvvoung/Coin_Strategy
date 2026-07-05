"""
백테스트 성과 지표: 승률, 손익비, Profit Factor, MDD, Sharpe/Sortino, 청산 발생 횟수.
"""
import math
from dataclasses import dataclass


@dataclass
class PerformanceReport:
    total_trades: int
    win_rate_pct: float
    avg_reward_risk: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    liquidation_events: int
    final_equity: float
    total_return_pct: float


def compute_performance(result, initial_equity: float) -> PerformanceReport:
    trades = result.trades
    total_trades = len(trades)

    wins = [t for t in trades if t.pnl_usdt > 0]
    losses = [t for t in trades if t.pnl_usdt <= 0]

    win_rate_pct = (len(wins) / total_trades * 100) if total_trades else 0.0

    avg_win = sum(t.pnl_usdt for t in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(t.pnl_usdt for t in losses) / len(losses)) if losses else 0.0
    avg_reward_risk = (avg_win / avg_loss) if avg_loss > 0 else float("inf") if avg_win > 0 else 0.0

    gross_profit = sum(t.pnl_usdt for t in wins)
    gross_loss = abs(sum(t.pnl_usdt for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    max_drawdown_pct = _max_drawdown_pct(result.equity_curve, initial_equity)

    per_trade_returns = [t.pnl_pct_of_equity / 100 for t in trades]
    sharpe_ratio = _sharpe(per_trade_returns)
    sortino_ratio = _sortino(per_trade_returns)

    total_return_pct = (result.final_equity - initial_equity) / initial_equity * 100 if initial_equity > 0 else 0.0

    return PerformanceReport(
        total_trades=total_trades,
        win_rate_pct=win_rate_pct,
        avg_reward_risk=avg_reward_risk,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        liquidation_events=result.liquidation_events,
        final_equity=result.final_equity,
        total_return_pct=total_return_pct,
    )


def _max_drawdown_pct(equity_curve, initial_equity) -> float:
    peak = initial_equity
    max_dd = 0.0
    for _, equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            dd = (peak - equity) / peak * 100
            max_dd = max(max_dd, dd)
    return max_dd


def _sharpe(returns, risk_free=0.0) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    return (mean - risk_free) / std if std > 0 else 0.0


def _sortino(returns, risk_free=0.0) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    downside = [min(0.0, r - risk_free) for r in returns]
    downside_variance = sum(d ** 2 for d in downside) / len(downside)
    downside_std = math.sqrt(downside_variance)
    return (mean - risk_free) / downside_std if downside_std > 0 else 0.0


def format_report(report: PerformanceReport) -> str:
    return (
        f"총 거래횟수        : {report.total_trades}\n"
        f"승률              : {report.win_rate_pct:.2f}%\n"
        f"평균 손익비(R:R)   : {report.avg_reward_risk:.2f}\n"
        f"Profit Factor     : {report.profit_factor:.2f}\n"
        f"최대낙폭(MDD)      : {report.max_drawdown_pct:.2f}%\n"
        f"Sharpe Ratio      : {report.sharpe_ratio:.3f}\n"
        f"Sortino Ratio     : {report.sortino_ratio:.3f}\n"
        f"강제청산 발생횟수  : {report.liquidation_events}\n"
        f"최종 자본          : {report.final_equity:,.2f} USDT\n"
        f"총 수익률          : {report.total_return_pct:.2f}%\n"
    )
