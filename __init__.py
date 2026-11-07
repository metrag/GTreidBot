"""
GTreidBot — скелет торгового бота поверх GTreidLib.

Модули:
    config   — BotConfig (режим, тикеры, риск, фильтры, выходы)
    state    — StateManager / Position (позиции, дневной PnL, просадка)
    journal  — TradeLogger (JSONL-журнал всех событий)
    executor — Executor (paper-исполнение по bid/ask)
    bot      — TradingBot (главный цикл 7 этапов)
"""

from .config import BotConfig
from .state import Position, StateManager
from .journal import TradeLogger
from .executor import Executor, Fill
from .bot import TradingBot

__version__ = "0.1.0"
__all__ = [
    "BotConfig",
    "Position",
    "StateManager",
    "TradeLogger",
    "Executor",
    "Fill",
    "TradingBot",
]
