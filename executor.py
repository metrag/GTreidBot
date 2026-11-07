"""
Исполнение ордеров (этап 6 цикла).

paper — симуляция исполнения по котировкам стакана (bid/ask) с учётом
        комиссии config.commission за каждую сторону.
live  — заглушка: реализуется на этапе М2 (исполнение через tcli).
"""

from dataclasses import dataclass
from typing import Optional

from GTreidLib import OrderBook

from .config import BotConfig
from .journal import TradeLogger


@dataclass
class Fill:
    """Результат исполнения ордера."""
    ok: bool
    price: float
    commission: float
    reason: str = ""


class Executor:
    """
    Исполнитель ордеров.

    В paper-режиме покупка исполняется по ask, продажа по bid
    (реалистично для тейкера). Комиссия = оборот * config.commission.
    """

    def __init__(self, config: BotConfig, journal: TradeLogger):
        self.config = config
        self.journal = journal

    # ── Вход ─────────────────────────────────────────────

    def buy(
        self,
        ticker: str,
        shares: int,
        orderbook: Optional[OrderBook] = None,
        fallback_price: Optional[float] = None,
    ) -> Fill:
        """
       Купить (paper: по ask стакана).

        Args:
            ticker: тикер
            shares: количество акций (кратно лоту проверяется снаружи)
            orderbook: стакан для реалистичной цены исполнения
            fallback_price: цена, если стакана нет
        """
        if self.config.mode != "paper":
            self.journal.log("error", stage="execute",
                             reason="live-режим реализуется на этапе М2 (tcli)")
            return Fill(ok=False, price=0.0, commission=0.0,
                        reason="live не реализован")

        price = self._fill_price(orderbook, side="ask",
                                 fallback=fallback_price)
        if price is None:
            return Fill(ok=False, price=0.0, commission=0.0,
                        reason="нет котировок для исполнения")

        value = price * shares
        commission = value * self.config.commission
        self.journal.log("fill_buy", ticker=ticker, shares=shares,
                         price=round(price, 4), value=round(value, 2),
                         commission=round(commission, 2))
        return Fill(ok=True, price=price, commission=commission)

    # ── Выход ────────────────────────────────────────────

    def sell(
        self,
        ticker: str,
        shares: int,
        orderbook: Optional[OrderBook] = None,
        fallback_price: Optional[float] = None,
        reason: str = "exit",
    ) -> Fill:
        """
        Продать (paper: по bid стакана).

        Args:
            reason: причина выхода (close_by_stop, close_by_time, ...)
        """
        if self.config.mode != "paper":
            self.journal.log("error", stage="execute",
                             reason="live-режим реализуется на этапе М2 (tcli)")
            return Fill(ok=False, price=0.0, commission=0.0,
                        reason="live не реализован")

        price = self._fill_price(orderbook, side="bid",
                                 fallback=fallback_price)
        if price is None:
            return Fill(ok=False, price=0.0, commission=0.0,
                        reason="нет котировок для исполнения")

        value = price * shares
        commission = value * self.config.commission
        self.journal.log("fill_sell", ticker=ticker, shares=shares,
                         price=round(price, 4), value=round(value, 2),
                         commission=round(commission, 2), reason=reason)
        return Fill(ok=True, price=price, commission=commission)

    # ── Вспомогательное ──────────────────────────────────

    @staticmethod
    def _fill_price(
        orderbook: Optional[OrderBook],
        side: str,
        fallback: Optional[float],
    ) -> Optional[float]:
        """Цена исполнения: ask/bid стакана или запасная цена."""
        if orderbook is not None:
            if side == "ask" and orderbook.asks:
                return orderbook.asks[0][0]
            if side == "bid" and orderbook.bids:
                return orderbook.bids[0][0]
            if orderbook.mid_price > 0:
                return orderbook.mid_price
        return fallback if fallback and fallback > 0 else None
