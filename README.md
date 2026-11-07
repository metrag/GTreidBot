# GTreidBot

Скелет торгового бота: 7 этапов цикла, paper-режим, MOEX long-only.

Строится поверх библиотеки [GTreidLib](../GTreidLib/README.md) — бот только
импортирует её, вся математика (сигналы, фильтры, стопы, риск) живёт там.

## Быстрый старт

```bash
# 1. Офлайн-проверка полного цикла (без сети и токена)
python -m GTreidBot --selftest

# 2. Paper trading (нужен токен Tinkoff Invest API)
python -m GTreidBot --mode paper --tickers SBER,GAZP --capital 100000
```

## Токен Tinkoff Invest API

Paper-режим читает реальные котировки через tcli — нужен токен песочницы.
Создайте файл `C:\Users\user\Desktop\tcli\.env`:

```ini
INVEST_SANDBOX_TOKEN=ваш_токен
```

Токен берётся в приложении Тинькофф: Настройки -> API-ключи (контур
«Песочница» для sandbox). Без токена бот завершится с понятным сообщением
(код 2), а не будет крутить ошибки.

## Архитектура

Каждый цикл (по умолчанию 60 секунд) проходит 7 этапов:

```
1. DataFeed     -> DataFeed: свечи, стакан, статус рынка (tcli, кэш)
2. StateUpdate  -> StateManager: позиции, дневной PnL, просадка, roll_day
3. Analyze      -> сигналы GTreidLib.signals (pullback_to_ma, momentum_candle)
4. Decide       -> apply_filters (8 фильтров) + check_risk_limits + стоп/размер
5. Execute     -> Executor: вход по ask (paper), запись в журнал
6. Monitor      -> стоп / reverse_signal / time_stop / трейлинг / EOD-flatten
7. Log          -> TradeLogger: JSONL + консоль, каждая причина отказа
```

## Структура

```
GTreidBot/
├── __main__.py    # CLI: python -m GTreidBot [опции]
├── config.py      # BotConfig: тикеры, риск, стопы, сессии, лимиты
├── bot.py         # TradingBot: run() + cycle() — 7 этапов
├── state.py       # Position, StateManager (капитал, PnL, просадка)
├── executor.py    # Fill, Executor (paper: покупка по ask, продажа по bid)
├── journal.py     # TradeLogger: journal.jsonl (UTF-8) + консоль
└── selftest.py    # FakeFeed + синтетические свечи: полный цикл офлайн
```

## Опции CLI

| Опция | По умолчанию | Описание |
|---|---|---|
| `--mode` | paper | paper / live (live заблокирован до этапа М2) |
| `--tickers` | SBER | тикеры через запятую |
| `--capital` | 100000 | стартовый капитал, руб |
| `--interval` | 1min | 1min / 5min / 15min / 1hour |
| `--cycle` | 60 | период цикла, секунд |
| `--journal` | journal.jsonl | файл журнала (JSONL) |
| `--risk-per-trade` | 0.01 | риск на сделку (0.01 = 1%) |
| `--max-positions` | 3 | максимум одновременных позиций |
| `--no-sandbox` | false | боевой контур tcli (токен INVEST_TOKEN) |
| `--selftest` | false | офлайн-проверка без сети |

## Торговая логика (профиль)

- **Рынок:** MOEX акции, long-only, без плеча
- **Сессии:** дневная 10:00-18:40, вечерняя 19:05-23:50 МСК
- **Вход:** `pullback_to_ma` или `momentum_candle` + все 8 фильтров + риск-проверки
- **Стоп:** `combined_stop` (структурный vs ATR), риск на сделку 1%
- **Выходы:** стоп-лосс / обратный сигнал / time-stop 30 мин / трейлинг после +1R / EOD-flatten 23:35
- **Без ТП:** `take_for_check` используется только для валидации R:R >= 2, ордер цели не ставится
- **Лимиты:** дневной убыток 2%, просадка 10%, до 20 сделок в день

## Пример вывода

```
[12:00:00] start mode=paper tickers=SBER capital=100000.0 interval=1min
[12:00:01] signal stage=analyze ticker=SBER signal=pullback_to_ma price=312.40
[12:00:01] filters stage=decide ticker=SBER approved=True passed=8/8
[12:00:02] open stage=execute ticker=SBER shares=30 price=312.45 stop=307.90 risk=136.50
[12:35:00] close stage=monitor ticker=SBER reason=time_stop pnl=-12.30
```

## Тестирование

```bash
python -m GTreidBot --selftest    # офлайн, exit=0 при успехе
python -m GTreidLib.signals       # математика сигналов
python -m GTreidLib.risk_check    # риск-лимиты
```

## Статус

- [x] Шаг 4: скелет бота, 7 этапов, paper-режим, selftest
- [ ] Шаг 5: живой paper на реальных котировках (нужен токен)
- [ ] М2 (tcli): реальные ордера, live-режим
- [ ] Стримы tcli (котировки/стакан в реальном времени вместо опроса)
