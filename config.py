"""
Конфигурация бота GTreidBot.

Профиль: MOEX акции, интрадей, long-only, без плеча и без ТП.
Выход: стоп-лосс / обратный сигнал / time-stop / EOD-flatten.
"""

from dataclasses import dataclass, field
from datetime import time
from typing import Dict, List, Optional

from GTreidLib import RiskConfig


@dataclass
class BotConfig:
    """Конфигурация торгового бота."""

    # --- Режим ---
    mode: str = "paper"                     # "paper" | "live"
    sandbox: bool = True                    # sandbox-контур tcli

    # --- Инструменты ---
    tickers: List[str] = field(default_factory=lambda: ["SBER"])
    interval: str = "1min"                  # 1min | 5min | 15min | 1hour
    cycle_seconds: int = 60                 # период цикла (сек)
    candles_days: int = 2                   # сколько дней свечей запрашивать
    lot_sizes: Dict[str, int] = field(default_factory=dict)  # ticker -> акций в лоте

    # --- Деньги и риск ---
    capital: float = 100_000.0
    risk_per_trade: float = 0.01            # 1% капитала на сделку
    commission: float = 0.0005              # 0.05% за сделку (тариф «Трейдер»)
    monthly_service: float = 390.0          # обслуживание тарифа, руб/мес
    risk: RiskConfig = field(default_factory=RiskConfig)

    # --- Стоп-лосс ---
    stop_lookback: int = 20                 # окно структурного стопа
    atr_period: int = 14
    atr_multiplier: float = 2.0
    stop_buffer: float = 0.05               # буфер под стопом, руб

    # --- Выходы без ТП ---
    ma_period: int = 20                     # EMA для pullback / обратного сигнала
    max_hold_minutes: int = 30              # time-stop
    trail_activate_r: float = 1.0           # трейлинг после +1R
    trail_atr_mult: float = 2.0             # трейлинг = price - mult*ATR
    flatten_at: time = time(23, 35)         # EOD-flatten (МСК)

    # --- Фильтры ---
    session_warmup_min: int = 5             # не входить в первые минуты
    session_cooldown_min: int = 10          # не входить в последние минуты
    zone_extension_pct: float = 2.0         # зона входа: не выше EMA*(1+N%)
    vol_min_atr_pct: float = 0.05           # ATR-коридор: минимум («не тишина»)
    vol_max_atr_pct: float = 2.0            # ATR-коридор: максимум («не шторм»)
    max_spread_pct: float = 0.1             # макс. спред в %

    # --- Журнал ---
    journal_path: Optional[str] = "journal.jsonl"

    def lot_size(self, ticker: str) -> int:
        """Размер лота тикера (по умолчанию 1 = акция)."""
        return self.lot_sizes.get(ticker, 1)
