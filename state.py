"""
Состояние бота: позиции, дневной PnL, просадка (этап 2 цикла).
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Optional


@dataclass
class Position:
    """Открытая позиция (long-only)."""

    ticker: str
    shares: int
    entry_price: float
    stop_price: float          # текущий стоп (может двигаться трейлингом)
    initial_stop: float        # стоп при входе (для расчёта R)
    opened_at: datetime
    signal_name: str
    entry_commission: float    # комиссия входа, руб
    trail_active: bool = False

    @property
    def risk_r(self) -> float:
        """1R = расстояние entry -> initial stop, руб/акция."""
        return self.entry_price - self.initial_stop


class StateManager:
    """
    Хранит позиции и агрегаты: дневной PnL, просадку, статистику.

    capital      — реализованный капитал (стартовый + закрытые сделки)
    equity       — capital + нереализованный PnL (обновляется update_equity)
    peak_equity  — пик equity (для просадки)
    """

    def __init__(self, capital: float):
        self.start_capital = capital
        self.capital = capital
        self.equity = capital
        self.peak_equity = capital

        self.positions: Dict[str, Position] = {}

        self.day: Optional[date] = None
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.halted = False   # True после дневного лимита убытка

        self.stats = {"entries": 0, "exits": 0, "wins": 0, "losses": 0}

    # ── Новый торговый день ──────────────────────────────

    def roll_day(self, now: datetime) -> None:
        """Сброс дневных счётчиков при смене даты."""
        if self.day != now.date():
            self.day = now.date()
            self.daily_pnl = 0.0
            self.trades_today = 0
            self.halted = False

    # ── Equity / просадка ────────────────────────────────

    def update_equity(self, prices: Dict[str, float]) -> None:
        """
        Пересчитать equity с учётом нереализованного PnL
        и обновить пик для просадки.

        Args:
            prices: текущие цены по тикерам {ticker: price}
        """
        unrealized = 0.0
        for ticker, pos in self.positions.items():
            price = prices.get(ticker, pos.entry_price)
            unrealized += (price - pos.entry_price) * pos.shares

        self.equity = self.capital + unrealized
        self.peak_equity = max(self.peak_equity, self.equity)

    @property
    def drawdown_pct(self) -> float:
        """Текущая просадка от пика, в долях (0.05 = 5%)."""
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.equity) / self.peak_equity

    @property
    def has_position(self) -> bool:
        return len(self.positions) > 0

    # ── Открытие / закрытие ──────────────────────────────

    def open_position(self, pos: Position) -> None:
        self.positions[pos.ticker] = pos
        self.stats["entries"] += 1

    def close_position(
        self,
        ticker: str,
        exit_price: float,
        exit_commission: float,
    ) -> float:
        """
        Закрыть позицию, обновить капитал и дневной PnL.

        Returns:
            Чистый PnL сделки (после обеих комиссий)
        """
        pos = self.positions.pop(ticker)
        gross = (exit_price - pos.entry_price) * pos.shares
        net = gross - pos.entry_commission - exit_commission

        self.capital += net
        self.daily_pnl += net
        self.trades_today += 1
        self.stats["exits"] += 1
        if net >= 0:
            self.stats["wins"] += 1
        else:
            self.stats["losses"] += 1

        # equity без позиции = капитал
        self.equity = self.capital
        self.peak_equity = max(self.peak_equity, self.equity)
        return net

    @property
    def win_rate(self) -> float:
        exits = self.stats["exits"]
        return self.stats["wins"] / exits if exits else 0.0
