"""
GTreidBot — скелет торгового бота (7 этапов цикла, BOT_STRUCTURE.md).

Цикл:
    1. DATA FEED     — свечи, стакан, статус рынка (GTreidLib.datafeed)
    2. STATE UPDATE  — equity, просадка, дневной PnL (state.py)
    3. ANALYZE       — сигналы + 8 фильтров (GTreidLib.signals)
    4. DECIDE & RISK — стоп, безубыточность, риск-лимиты, размер позиции
    5. MONITOR       — стоп / time-stop / обратный сигнал / трейлинг
    6. EXECUTE       — вход/выход (executor.py, paper)
    7. LOG           — журнал всех событий (journal.py)

Профиль: MOEX акции, long-only, без плеча, без ТП.
Выход: стоп-лосс / обратный сигнал / time-stop / EOD-flatten.
"""

import time as _time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from GTreidLib import (
    Candle,
    DataFeed,
    OrderBook,
    apply_filters,
    break_even_summary,
    calculate_atr,
    calculate_position_size,
    check_risk_limits,
    combined_stop,
    eod_flatten,
    momentum_candle,
    pullback_to_ma,
    reverse_signal_exit,
    session_filter,
    spread_filter,
    time_stop,
    trend_filter,
    trailing_stop,
    volume_filter,
    volatility_filter,
    market_open_filter,
    news_filter,
    zone_filter,
)

from .config import BotConfig
from .executor import Executor
from .journal import TradeLogger
from .state import Position, StateManager

MSK = ZoneInfo("Europe/Moscow")


class TradingBot:
    """Главный класс бота: 7-этапный цикл."""

    def __init__(self, config: BotConfig,
                 feed: Optional[DataFeed] = None,
                 journal: Optional[TradeLogger] = None):
        self.config = config
        self.feed = feed or DataFeed(sandbox=config.sandbox)
        self.journal = journal or TradeLogger(config.journal_path)
        self.state = StateManager(config.capital)
        self.executor = Executor(config, self.journal)
        self._was_paused = False

    # ═════════════════════════════════════════════════════
    # Главный цикл
    # ═════════════════════════════════════════════════════

    def run(self) -> None:
        """Бесконечный цикл с паузой cycle_seconds."""
        cfg = self.config
        self.journal.log("start", mode=cfg.mode, tickers=",".join(cfg.tickers),
                         capital=cfg.capital, interval=cfg.interval)
        if cfg.mode != "paper":
            self.journal.log("error",
                             reason="live-режим не реализован — запустите --mode paper")
            return
        while True:
            try:
                self.cycle()
            except KeyboardInterrupt:
                self.journal.log("stop", reason="keyboard")
                break
            except Exception as exc:  # noqa: BLE001 — цикл не должен падать
                self.journal.log("error", stage="cycle", reason=repr(exc))
            _time.sleep(cfg.cycle_seconds)

    def cycle(self, now: Optional[datetime] = None) -> None:
        """Одна итерация 7 этапов (вызывается и из selftest)."""
        cfg = self.config
        now = now or datetime.now(MSK)

        # Этап 2 (вход в день): сброс дневных счётчиков
        self.state.roll_day(now)

        # Дневной лимит убытка -> halt + закрыть всё
        loss_limit = cfg.risk.max_daily_loss * self.state.start_capital
        if not self.state.halted and self.state.daily_pnl <= -loss_limit:
            self.state.halted = True
            self.journal.log("halt", daily_pnl=round(self.state.daily_pnl, 2),
                             limit=round(-loss_limit, 2))
            self._flatten_all("halt")

        # Пауза вне сессии (свечи/стакан недоступны)
        if not self._in_session(now):
            if self.state.has_position and eod_flatten(now, cfg.flatten_at):
                self._flatten_all("eod")
            if not self._was_paused:
                self.journal.log("paused", reason="вне торговой сессии")
                self._was_paused = True
            return
        self._was_paused = False

        # EOD-flatten (этап 5, глобальный)
        if eod_flatten(now, cfg.flatten_at) and self.state.has_position:
            self._flatten_all("eod")

        # Этап 1-7 по каждому тикеру
        prices: Dict[str, float] = {}
        for ticker in cfg.tickers:
            price = self._process_ticker(ticker, now)
            if price is not None:
                prices[ticker] = price

        # Этап 2: equity + просадка
        self.state.update_equity(prices)

    # ═════════════════════════════════════════════════════
    # Этап 1: DATA FEED
    # ═════════════════════════════════════════════════════

    def _fetch(self, ticker: str) -> Optional[Tuple[List[Candle], OrderBook]]:
        """Свечи + стакан одного тикера. None при ошибке/закрытом рынке."""
        try:
            if not self.feed.is_market_open(ticker):
                return None
            candles = self.feed.get_candles(
                ticker, interval=self.config.interval,
                days_ago=self.config.candles_days)
            orderbook = self.feed.get_orderbook(ticker, depth=10)
        except Exception as exc:  # noqa: BLE001
            self.journal.log("error", stage="data", ticker=ticker,
                             reason=repr(exc))
            return None
        if len(candles) < self.config.ma_period + 5:
            return None
        return candles, orderbook

    # ═════════════════════════════════════════════════════
    # Обработка одного тикера: этапы 3-6
    # ═════════════════════════════════════════════════════

    def _process_ticker(self, ticker: str, now: datetime) -> Optional[float]:
        data = self._fetch(ticker)
        if data is None:
            return None
        candles, orderbook = data
        mid = orderbook.mid_price or candles[-1].close

        # Этап 5: сначала мониторим открытую позицию (закрытие)
        if ticker in self.state.positions:
            self._monitor_position(ticker, candles, orderbook, now)
            return mid

        # Этап 3: ANALYZE — сигнал + стек из 8 фильтров
        if self.state.halted:
            return mid
        setup = self._analyze(ticker, candles, orderbook, now)
        if setup is None or not setup.approved:
            return mid

        # Этап 4: DECIDE & RISK
        plan = self._decide(ticker, setup.signal, candles, orderbook, now)
        if plan is None:
            return mid

        # Этап 6: EXECUTE вход
        self._open_position(ticker, plan, orderbook, candles, now)
        return mid

    # ═════════════════════════════════════════════════════
    # Этап 3: ANALYZE
    # ═════════════════════════════════════════════════════

    def _analyze(self, ticker: str, candles: List[Candle],
                 orderbook: OrderBook, now: datetime):
        """Сигнал входа + 8 фильтров -> TradeSetup (approved = сделка)."""
        cfg = self.config

        # Один сигнал: pullback к EMA (основной) или моментум-свеча
        sig = pullback_to_ma(candles, period=cfg.ma_period, ma="ema")
        if sig is None:
            sig = momentum_candle(candles)
        if sig is None:
            return None

        self.journal.log("signal", ticker=ticker, name=sig.name,
                         price=round(sig.price, 4), reason=sig.reason)

        # 8 фильтров (глава 19: сигнал + все 8 = сделка)
        ema_now = self._ema_now(candles, cfg.ma_period)
        bid = orderbook.bids[0][0] if orderbook.bids else sig.price
        ask = orderbook.asks[0][0] if orderbook.asks else sig.price

        filters = [
            trend_filter(candles, period=cfg.ma_period),              # 19.1
            zone_filter(sig.price, ema_now,                           # 19.2
                        ema_now * (1 + cfg.zone_extension_pct / 100)),
            volume_filter(candles),                                   # 19.3
            volatility_filter(candles,                                # 19.4
                              min_atr_pct=cfg.vol_min_atr_pct,
                              max_atr_pct=cfg.vol_max_atr_pct),
            spread_filter(bid, ask, cfg.max_spread_pct),              # 19.5
            session_filter(now, cfg.session_warmup_min,
                           cfg.session_cooldown_min),                 # 19.6
            news_filter(now, None),                                   # 19.7
            market_open_filter(True),                                 # 19.8
        ]
        for f in filters:
            if not f.passed:
                self.journal.log("filter", ticker=ticker, name=f.name,
                                 passed=False, reason=f.reason)

        return apply_filters(sig, filters)

    # ═════════════════════════════════════════════════════
    # Этап 4: DECIDE & RISK
    # ═════════════════════════════════════════════════════

    def _decide(self, ticker: str, signal, candles: List[Candle],
                orderbook: OrderBook, now: datetime) -> Optional[dict]:
        """Торговый план: стоп, безубыточность, риск-лимиты, размер."""
        cfg = self.config
        entry = (orderbook.asks[0][0] if orderbook.asks
                 else signal.price)

        # Стоп: максимум структурного и ATR-стопа (GTreidLib)
        atr = calculate_atr(candles, cfg.atr_period)
        stop = combined_stop(entry, candles, atr_value=atr,
                             lookback=cfg.stop_lookback,
                             atr_multiplier=cfg.atr_multiplier,
                             buffer=cfg.stop_buffer)
        if stop.stop_price >= entry:
            self.journal.log("reject", ticker=ticker, reason="стоп выше entry")
            return None

        # R:R-цель только для проверки (без ТП-ордера! 20.6: цель = структура)
        take_for_check = entry + 2.0 * stop.distance

        # Безубыточность: ожидаемое движение (2R) должно покрыть расходы
        lot = cfg.lot_size(ticker)
        shares_guess = max(lot, 100)
        be = break_even_summary(entry, c=cfg.commission,
                                monthly_service=cfg.monthly_service,
                                trades_per_day=5,
                                lots=shares_guess, lot_size=1)
        expected_move_pct = 2.0 * stop.distance / entry
        if expected_move_pct < be.delta_pct:
            self.journal.log("reject", ticker=ticker,
                             reason=f"движение {expected_move_pct:.4%} "
                                    f"не покрывает безубыток {be.delta_pct:.4%}")
            return None

        # Дневной лимит сделок
        if self.state.trades_today >= cfg.risk.max_daily_trades:
            self.journal.log("reject", ticker=ticker,
                             reason="дневной лимит сделок исчерпан")
            return None

        # Комплексная проверка риск-лимитов
        risk = check_risk_limits(
            capital=self.state.equity,
            daily_pnl=self.state.daily_pnl,
            current_positions=len(self.state.positions),
            peak_capital=self.state.peak_equity,
            entry_price=entry,
            stop_price=stop.stop_price,
            take_price=take_for_check,
            config=cfg.risk,
        )
        if not risk.allowed:
            self.journal.log("reject", ticker=ticker,
                             reason="; ".join(risk.violations))
            return None

        # Размер позиции (фиксированный риск % капитала)
        sizing = calculate_position_size(
            capital=self.state.equity,
            entry_price=entry,
            stop_price=stop.stop_price,
            risk_per_trade=cfg.risk_per_trade,
            lot_size=lot,
            max_position_pct=cfg.risk.max_position_pct,
        )
        if sizing.shares < lot:
            self.journal.log("reject", ticker=ticker,
                             reason=f"позиция меньше лота ({sizing.shares} < {lot})")
            return None

        return {
            "entry": entry,
            "stop": stop.stop_price,
            "shares": sizing.shares,
            "risk_amount": sizing.risk_amount,
            "signal": signal.name,
            "atr": atr,
            "be_pct": be.delta_pct,
        }

    # ═════════════════════════════════════════════════════
    # Этап 6: EXECUTE — вход
    # ═════════════════════════════════════════════════════

    def _open_position(self, ticker: str, plan: dict,
                       orderbook: OrderBook, candles: List[Candle],
                       now: datetime) -> None:
        fill = self.executor.buy(ticker, plan["shares"], orderbook,
                                 fallback_price=plan["entry"])
        if not fill.ok:
            self.journal.log("reject", ticker=ticker, reason=fill.reason)
            return

        pos = Position(
            ticker=ticker,
            shares=plan["shares"],
            entry_price=fill.price,
            stop_price=plan["stop"],
            initial_stop=plan["stop"],
            opened_at=now,
            signal_name=plan["signal"],
            entry_commission=fill.commission,
        )
        self.state.open_position(pos)
        self.journal.log(
            "entry", ticker=ticker, shares=pos.shares,
            price=round(fill.price, 4), stop=round(plan["stop"], 4),
            risk=round(plan["risk_amount"], 2),
            be_pct=round(plan["be_pct"] * 100, 4),
            signal=pos.signal_name,
        )

    # ═════════════════════════════════════════════════════
    # Этап 5: MONITOR POSITION
    # ═════════════════════════════════════════════════════

    def _monitor_position(self, ticker: str, candles: List[Candle],
                          orderbook: OrderBook, now: datetime) -> None:
        """Проверка условий выхода (без ТП): стоп/time/reverse/trailing."""
        cfg = self.config
        pos = self.state.positions.get(ticker)
        if pos is None:
            return

        bid = orderbook.bids[0][0] if orderbook.bids else candles[-1].close
        atr = calculate_atr(candles, cfg.atr_period)
        in_profit = bid > pos.entry_price

        # 1) Стоп-лосс (жёсткий, обязателен всегда — 20.1)
        if bid <= pos.stop_price:
            self._close_position(ticker, orderbook, "close_by_stop")
            return

        # 2) Обратный сигнал (20.3)
        if reverse_signal_exit(candles, period=cfg.ma_period):
            self._close_position(ticker, orderbook, "close_by_signal")
            return

        # 3) Time-stop: не в плюс за N минут (20.2)
        if time_stop(pos.opened_at, now, in_profit,
                     max_minutes=cfg.max_hold_minutes):
            self._close_position(ticker, orderbook, "close_by_time")
            return

        # 4) Трейлинг после +1R (20.4): стоп двигается только вверх
        if not pos.trail_active and pos.risk_r > 0:
            if bid - pos.entry_price >= cfg.trail_activate_r * pos.risk_r:
                pos.trail_active = True
                self.journal.log("trail", ticker=ticker, activated=True)
        if pos.trail_active:
            new_stop = trailing_stop(
                entry_price=pos.entry_price,
                current_price=bid,
                atr_value=atr,
                multiplier=cfg.trail_atr_mult,
                current_stop=pos.stop_price,
            ).stop_price
            if new_stop > pos.stop_price:
                pos.stop_price = new_stop
                self.journal.log("trail", ticker=ticker,
                                 stop=round(new_stop, 4))

    # ═════════════════════════════════════════════════════
    # Этап 6: EXECUTE — выход
    # ═════════════════════════════════════════════════════

    def _close_position(self, ticker: str, orderbook: Optional[OrderBook],
                        reason: str) -> None:
        pos = self.state.positions.get(ticker)
        if pos is None:
            return
        fill = self.executor.sell(ticker, pos.shares, orderbook,
                                  fallback_price=pos.entry_price,
                                  reason=reason)
        if not fill.ok:
            self.journal.log("error", stage="exit", ticker=ticker,
                             reason=fill.reason)
            return
        net = self.state.close_position(ticker, fill.price, fill.commission)
        self.journal.log("exit", ticker=ticker, reason=reason,
                         price=round(fill.price, 4),
                         commission=round(fill.commission, 2),
                         pnl=round(net, 2),
                         daily_pnl=round(self.state.daily_pnl, 2))

    def _flatten_all(self, reason: str) -> None:
        """Закрыть все позиции (EOD / halt)."""
        for ticker in list(self.state.positions):
            self._close_position(ticker, None, reason)

    # ═════════════════════════════════════════════════════
    # Вспомогательные
    # ═════════════════════════════════════════════════════

    @staticmethod
    def _ema_now(candles: List[Candle], period: int) -> float:
        """EMA последних close (для зоны входа)."""
        from GTreidLib import ema
        closes = [c.close for c in candles]
        values = ema(closes, period)
        for v in reversed(values):
            if v is not None:
                return float(v)
        return closes[-1]

    def _in_session(self, now: datetime) -> bool:
        """Есть ли сейчас открытая сессия MOEX (дневная/вечерняя)."""
        return session_filter(now, 0, 0).passed
