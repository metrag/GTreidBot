"""
GTreidBot — скелет торгового бота (7 этапов цикла).

Точка входа:
    python -m GTreidBot --selftest          # офлайн-проверка связки
    python -m GTreidBot --mode paper        # paper trading
    python -m GTreidBot --tickers SBER,GAZP --capital 100000
"""

import argparse
import sys
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from GTreidLib import RiskConfig

from .config import BotConfig

MSK = ZoneInfo("Europe/Moscow")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="GTreidBot",
        description="Скелет торгового бота (MOEX, long-only, paper/live)",
    )
    p.add_argument("--mode", choices=["paper", "live"], default="paper",
                   help="режим работы (по умолчанию paper)")
    p.add_argument("--tickers", type=str, default="SBER",
                   help="тикеры через запятую (по умолчанию SBER)")
    p.add_argument("--capital", type=float, default=100_000.0,
                   help="стартовый капитал, руб")
    p.add_argument("--interval", type=str, default="1min",
                   choices=["1min", "5min", "15min", "1hour"],
                   help="таймфрейм свечей")
    p.add_argument("--cycle", type=int, default=60,
                   help="период цикла, секунд (по умолчанию 60)")
    p.add_argument("--journal", type=str, default="journal.jsonl",
                   help="файл журнала (JSONL)")
    p.add_argument("--no-sandbox", action="store_true",
                   help="выключить sandbox-контур tcli")
    p.add_argument("--risk-per-trade", type=float, default=0.01,
                   help="риск на сделку в долях (0.01 = 1%%)")
    p.add_argument("--max-positions", type=int, default=3,
                   help="максимум одновременных позиций")
    p.add_argument("--selftest", action="store_true",
                   help="офлайн-проверка полного цикла без сети")
    return p


def config_from_args(args: argparse.Namespace) -> BotConfig:
    return BotConfig(
        mode=args.mode,
        sandbox=not args.no_sandbox,
        tickers=[t.strip().upper() for t in args.tickers.split(",") if t.strip()],
        capital=args.capital,
        interval=args.interval,
        cycle_seconds=args.cycle,
        journal_path=args.journal,
        risk_per_trade=args.risk_per_trade,
        risk=RiskConfig(max_positions=args.max_positions),
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.selftest:
        from .selftest import run_selftest
        return run_selftest()

    if args.mode == "live":
        print("[STOP] live-режим реализуется на этапе М2 (исполнение tcli). "
              "Пока используйте --mode paper.")
        return 2

    # Проверка токена tcli до старта цикла (иначе бесконечные ошибки данных)
    try:
        from tcli.config import Settings
        settings = Settings.load()
        if not settings.enabled:
            contour = "INVEST_SANDBOX_TOKEN" if not args.no_sandbox else "INVEST_TOKEN"
            print(f"[STOP] не задан токен Tinkoff Invest API ({contour}).")
            print(f"       Создайте файл {settings.env_path} с содержимым:")
            print(f"       {contour}=ваш_токен")
            print("       Токен: Тинькофф Инвестиции -> Настройки -> API-ключи.")
            return 2
    except ImportError:
        print("[WARN] tcli не установлен — проверка токена пропущена.")

    from .bot import TradingBot
    bot = TradingBot(config_from_args(args))
    bot.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
