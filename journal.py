"""
Журнал сделок и событий (этап 7 цикла).

Пишет JSONL (UTF-8) и дублирует короткую строку в консоль.
Каждое событие: сигнал, каждый фильтр, отказ, вход, выход, трейлинг, halt.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


class TradeLogger:
    """
    Журнал бота.

    Args:
        path: файл журнала (JSONL). None = только в память/консоль.
        quiet: подавить печать в консоль (для selftest).
    """

    def __init__(self, path: Optional[str] = None, quiet: bool = False):
        self.path = Path(path) if path else None
        self.quiet = quiet
        self.records: List[dict] = []

    def log(self, event: str, **fields) -> dict:
        """
        Записать событие.

        Args:
            event: тип события (signal, filter, reject, entry, exit,
                   trail, halt, paused, cycle, error ...)
            **fields: дополнительные поля

        Returns:
            Записанная запись
        """
        rec = {
            "ts": datetime.now(MSK).isoformat(timespec="seconds"),
            "event": event,
            **fields,
        }
        self.records.append(rec)

        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

        if not self.quiet:
            extras = " ".join(f"{k}={v}" for k, v in fields.items())
            print(f"[{rec['ts'][11:19]}] {event}" + (f" {extras}" if extras else ""))

        return rec

    def find(self, event: str) -> List[dict]:
        """Все записи с данным типом события (для тестов/анализа)."""
        return [r for r in self.records if r["event"] == event]
