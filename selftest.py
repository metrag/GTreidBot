"""
Офлайн-проверка полного цикла бота без сети.

Строит синтетический восходящий ряд с откатом к EMA, прогоняет
2 цикла: (1) сигнал -> 8 фильтров -> риск -> вход,
(2) падение ниже стопа -> close_by_stop.
"""

from datetime import datetime, time as dtime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from GTreidLib import DataFeedCandle as Candle, OrderBook, RiskConfig

from .config import BotConfig
from .journal import TradeLogger

MSK = ZoneInfo("Europe/Moscow")

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=MSK)  # четверг, дневная сессия


class FakeFeed:
    """Подменный DataFeed: синтетические свечи и стакан."""

    def __init__(self, candles: List[Candle], price: float):
        self.candles = candles
        self.price = price  # текущая «рыночная» цена

    def is_market_open(self, ticker: str) -> bool:
        return True

    def get_candles(self, ticker: str, interval: str = "1min",
                    days_ago: Optional[int] = None, **kw) -> List[Candle]:
        return self.candles

    def get_orderbook(self, ticker: str, depth: int = 10) -> OrderBook:
        p = self.price
        return OrderBook(
            bids=[(round(p - 0.02, 2), 500)],
            asks=[(round(p + 0.03, 2), 400)],
            spread=0.05,
            mid_price=p,
        )

    def get_last_price(self, ticker: str) -> float:
        return self.price


def make_candles(n: int = 60) -> List[Candle]:
    """
    Синтетика: рост 0.2 руб/бар, последняя свеча — откат к EMA
    (low касается EMA, close остаётся выше — pullback_to_ma срабатывает).
    """
    bars: List[Candle] = []
    for i in range(n - 1):
        o = 100.0 + 0.2 * i
        bars.append(Candle(NOW, o, o + 0.3, o - 0.2, o + 0.25, 1000))

    # Последняя свеча: бычья, объём выше среднего
    last_open = 111.85
    last_close = 112.10
    bars.append(Candle(NOW, last_open, 112.30, 110.0, last_close, 1500))

    # low последней свечи -> в зону EMA (ema ~110.2)
    from GTreidLib import ema
    values = ema([c.close for c in bars], 20)
    ema_now = next(v for v in reversed(values) if v is not None)
    last = bars[-1]
    bars[-1] = Candle(NOW, last.open, last.high, round(ema_now - 0.05, 4),
                      last.close, last.volume)
    return bars


def run_selftest() -> int:
    """Возвращает 0 при успехе, 1 при провале."""
    from .bot import TradingBot

    candles = make_candles()
    price = candles[-1].close + 0.05          # ~112.15
    feed = FakeFeed(candles, price)
    journal = TradeLogger(path=None, quiet=True)

    config = BotConfig(
        mode="paper",
        tickers=["TEST"],
        capital=100_000.0,
        lot_sizes={"TEST": 1},
        journal_path=None,
        # для синтетики ослабляем стоп-коридор: монотонный рост даёт
        # структурный стоп в 3.9% (в реальных данных он ближе)
        risk=RiskConfig(max_stop_pct=0.05),
    )
    bot = TradingBot(config, feed=feed, journal=journal)

    # ── Цикл 1: вход ────────────────────────────────────
    bot.cycle(now=NOW)
    errors = []

    if "TEST" not in bot.state.positions:
        errors.append("позиция не открылась (сигнал/фильтры/риск?)")
    if not journal.find("entry"):
        errors.append("нет события entry в журнале")
    if not journal.find("signal"):
        errors.append("нет события signal в журнале")

    # ── Цикл 2: стоп сработал ───────────────────────────
    feed.price = 107.00                      # ниже стопа ~107.75
    bot.cycle(now=NOW.replace(minute=1))

    if "TEST" in bot.state.positions:
        errors.append("позиция не закрылась по стопу")
    exits = journal.find("exit")
    if not exits:
        errors.append("нет события exit в журнале")
    elif exits[0].get("reason") != "close_by_stop":
        errors.append(f"причина выхода: {exits[0].get('reason')}")
    if bot.state.capital >= config.capital:
        errors.append("капитал не уменьшился после стопа")

    # ── Итог ────────────────────────────────────────────
    if errors:
        print("[FAIL] selftest:")
        for e in errors:
            print(f"   - {e}")
        print("   события журнала:", [r["event"] for r in journal.records])
        return 1

    entry = journal.find("entry")[0]
    exit_ = journal.find("exit")[0]
    print("[OK] selftest: полный цикл работает")
    print(f"   вход:  {entry['shares']} акц. по {entry['price']}, "
          f"стоп {entry['stop']}, риск {entry['risk']} руб")
    print(f"   выход: {exit_['reason']}, pnl {exit_['pnl']} руб")
    print(f"   капитал: {config.capital} -> {round(bot.state.capital, 2)}")
    return 0
