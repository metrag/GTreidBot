# Архитектура торгового бота

## Обзор

Бот работает в событийном цикле, повторяя 7 этапов каждую итерацию (обычно 1-5 секунд).

```
┌─────────────────────────────────────────────────────────────────┐
│                      СОБЫТИЙНЫЙ ЦИКЛ БОТА                        │
└─────────────────────────────────────────────────────────────────┘

while market_is_open() and not halted():
    
    ┌──────────┐     ┌──────────┐     ┌──────────┐
    │ 1. DATA  │────>│ 2. STATE │────>│ 3. ANALYZE│
    │  FEED    │     │  UPDATE  │     │          │
    └──────────┘     └──────────┘     └──────────┘
                                          │
                                          v
    ┌──────────┐     ┌──────────┐     ┌──────────┐
    │ 6. LOG   │<────│ 5. MONITOR│<────│ 4. DECIDE │
    │          │     │  POSITION│     │  & RISK  │
    └──────────┘     └──────────┘     └──────────┘
         │                                │
         │                                v
         │                          ┌──────────┐
         └──────────────────────────│ 7. EXEC  │
                                    └──────────┘
```

---

## 7 этапов цикла

### **Этап 1: DATA FEED — Получение рыночных данных**

**Цель:** Получить актуальные данные с биржи.

**Действия:**
- Подключение к API биржи через `tcli`
- Получение свечей нужных ТФ (1М, 5М, 15М, 1Ч, 4Ч)
- Получение стакана (orderbook)
- Получение статуса торгов

**Данные:**
```python
candles = tcli.candles(symbol, timeframe, count=100)
orderbook = tcli.orderbook(symbol, depth=50)
status = tcli.trading_status(symbol)
```

**Валидация:**
- Проверка актуальности данных (не устарели ли)
- Проверка сессии (дневная/вечерняя открыта?)
- Проверка ликвидности (спред не слишком большой)

---

### **Этап 2: STATE UPDATE — Обновление состояния**

**Цель:** Рассчитать индикаторы и уровни на основе новых данных.

**Действия:**
- Расчёт индикаторов (EMA, ATR, RSI, VWAP, MACD)
- Поиск уровней (support/resistance)
- Обновление позиции и PnL

**Данные:**
```python
indicators = calculate_indicators(candles)
levels = find_levels(candles)
position = get_current_position(symbol)
pnl = calculate_pnl(position)
```

---

### **Этап 3: ANALYZE — Анализ рынка**

**Цель:** Найти торговый сигнал.

**Действия:**
- Проверка фильтров (тренд, волатильность, объём)
- Поиск паттернов/сигналов
- Определение направления (long only) и ТФ входа

**Данные:**
```python
filters_ok = check_filters(indicators, levels)
signal = detect_signal(candles, indicators)
entry_tf = select_timeframe(signal)
```

**Результат:**
```python
signal = {
    "type": "long",
    "strength": 0.75,
    "entry_tf": "5m",
    "expected_move": 0.004,  # 0.4%
}  # или None если сигнала нет
```

---

### **Этап 4: DECIDE & RISK — Решение и проверка рисков**

**Цель:** Рассчитать торговый план и проверить риски.

**Действия:**
- Рассчитать точку входа
- Рассчитать стоп-лосс (структурный + ATR)
- Рассчитать тейк-профит (R:R >= 2:1)
- Проверить точку безубыточности
- Проверить риск-лимиты
- Рассчитать размер позиции

**Данные:**
```python
if signal:
    entry_price = calculate_entry(candles, signal)
    stop_loss = combined_stop(entry_price, candles, atr)  # из GTreidLib
    take_profit = calculate_take_profit(entry_price, stop_loss, rr=2.0)
    
    # Проверка безубыточности
    be = break_even_summary(entry_price, ...)  # из GTreidLib
    if expected_move < be.delta_pct:
        skip()  # движение не покроет комиссии
    
    # Размер позиции
    position_size = calculate_position_size(
        capital=100000,
        risk_per_trade=0.01,  # 1%
        stop_distance=entry_price - stop_loss
    )  # из GTreidLib
```

**Результат:**
```python
trade_plan = {
    "entry": 263.50,
    "stop": 262.35,
    "take": 265.80,
    "size": 100,  # акций
    "risk": 115,  # руб
    "reward": 230,  # руб
    "rr_ratio": 2.0,
}  # или None если условия не подходят
```

---

### **Этап 5: MONITOR POSITION — Мониторинг позиции**

**Цель:** Отслеживать открытую позицию и проверять условия выхода.

**Действия:**
- Проверка стоп-лосса (выбило?)
- Проверка тейк-профита (достигли?)
- Проверка тайм-стопа (слишком долго?)
- Проверка трейлинг-стопа (подтянуть?)
- Проверка EOD (конец дня — закрывать?)

**Данные:**
```python
current_price = get_current_price(symbol)

if current_price <= position.stop:
    action = "close_by_stop"

elif current_price >= position.take:
    action = "close_by_take"

elif time_in_position > MAX_HOLD_TIME:
    action = "close_by_time"

elif should_trail_stop(position, current_price):
    action = "trail_stop"

elif is_end_of_day() and FLATTEN_EOD:
    action = "flatten_eod"

else:
    action = "hold"
```

---

### **Этап 6: EXECUTE — Исполнение**

**Цель:** Открыть/закрыть позицию через API биржи.

**Действия:**
- Открытие позиции (market order)
- Выставление стоп-ордера
- Закрытие позиции по сигналу
- Модификация стоп-ордера (трейлинг)

**Данные:**
```python
if trade_plan:
    order = tcli.place_order(symbol, "buy", trade_plan.size)
    stop_order = tcli.place_stop_order(symbol, "sell", trade_plan.stop)

if action == "close_by_stop":
    # стоп уже сработал — проверяем исполнение
    pass

elif action == "close_by_take":
    order = tcli.place_order(symbol, "sell", position.size)
    tcli.cancel_order(position.stop_order_id)

elif action == "close_by_time":
    order = tcli.place_order(symbol, "sell", position.size)

elif action == "trail_stop":
    tcli.modify_order(position.stop_order_id, new_stop)
```

---

### **Этап 7: LOG — Логирование**

**Цель:** Записать все действия и обновить статистику.

**Действия:**
- Логирование всех действий
- Обновление статистики
- Сохранение снимка состояния

**Данные:**
```python
log_event({
    "timestamp": now(),
    "event": "entry" | "exit" | "signal" | "skip",
    "symbol": symbol,
    "price": current_price,
    "details": trade_plan or action,
})

update_statistics(trades_today, pnl_today, win_rate)
```

---

## Компоненты бота (классы)

```python
class TradingBot:
    """Главный класс бота"""
    
    def __init__(self, config):
        self.config = config
        self.data_feed = DataFeed(config)          # Этап 1
        self.state_manager = StateManager()        # Этап 2
        self.analyzer = MarketAnalyzer(config)     # Этап 3
        self.risk_manager = RiskManager(config)    # Этап 4
        self.position_monitor = PositionMonitor()  # Этап 5
        self.executor = Executor(config)           # Этап 6
        self.logger = TradeLogger()                # Этап 7
    
    def run(self):
        """Главный цикл"""
        while True:
            # 1. Данные
            market_data = self.data_feed.update()
            
            # 2. Состояние
            self.state_manager.update(market_data)
            
            # 3. Анализ
            signal = self.analyzer.analyze(self.state_manager)
            
            # 4. Решение
            if signal:
                trade_plan = self.risk_manager.evaluate(signal)
                
                # 6. Исполнение
                if trade_plan:
                    self.executor.open_position(trade_plan)
            
            # 5. Мониторинг позиции
            if self.state_manager.has_position():
                action = self.position_monitor.check(self.state_manager)
                
                # 6. Исполнение
                if action:
                    self.executor.execute_action(action)
            
            # 7. Логирование
            self.logger.log_cycle(self.state_manager)
            
            # Пауза перед следующим циклом
            sleep(CYCLE_INTERVAL)
```

---

## Ключевые принципы

1. **Событийный цикл** — бот работает в бесконечном цикле, повторяя 7 этапов
2. **Разделение ответственности** — каждый компонент отвечает за одну задачу
3. **Проверка рисков ДО исполнения** — сначала считаем стоп/размер, потом исполняем
4. **Безубыточность** — проверяем что движение покроет комиссии
5. **Риск-менеджмент** — фиксированный риск на сделку (1%), максимум позиций, дневной лимит
6. **Логирование** — каждое действие записывается для анализа
7. **Paper trading** — сначала тестируем на бумаге, потом реальные деньги

---

## Модули GTreidLib для бота

| Модуль | Функции | Этап |
|--------|---------|------|
| `break_even.py` | `break_even_summary()`, `pct_change()` | 4 |
| `stop_loss.py` | `structural_stop()`, `atr_stop()`, `combined_stop()`, `trailing_stop()` | 4, 5 |
| `position_sizing.py` | `calculate_position_size()` | 4 |
| `risk_check.py` | `check_risk_limits()` | 4 |

---

## Следующие шаги

1. ✅ Реализовать модули в GTreidLib:
   - `stop_loss.py` — расчёт стопов
   - `position_sizing.py` — размер позиции
   - `risk_check.py` — проверка риск-лимитов

2. Написать скелет бота `bot.py`:
   - Класс `TradingBot` с 7 этапами
   - Интеграция с `tcli`

3. Реализовать каждую стадию отдельно:
   - DataFeed (через tcli)
   - Analyzer (индикаторы + фильтры + сигналы)
   - RiskManager (стопы + размер + проверки)
   - Executor (ордера через tcli)

4. Paper trading — тест на бумаге

5. Переход на реальные деньги (малый капитал)
