# Вынос механик из benz в parser-universal — план работ, 19.09.2026

## Откуда считать (замер 19.09, не пересказ)

Библиотека **уже существует и уже используется**: `/root/parser-universal` —
свой git-репозиторий `scamp77/parser-universal`, версия 0.4.0, описание в
`pyproject.toml` дословно «benz + sup-app cross-project». Своих тестов 23
файла, прогон `.venv/bin/python -m pytest tests -q` → **134 passed in 3,13 с**.
Пакет **установлен системно**: `cd /tmp && python3 -c "import parser_universal"`
находит его. Значит `sys.path.insert(0, "/root/parser-universal")` в benz —
избыточная вставка, а не способ доступа; она есть в **10 файлах** benz
(`parsers_hybrid/orchestrator.py:44`, `preview_parser.py`, `app/core/geo_oblasts.py`,
`parsers_hybrid/waze_traffic/{fetcher,runner}.py`, `scripts/autoria_wayback_diff.py`,
`scripts/ucdp_fetch.py`, три `scripts/cron_infrastructure_*.sh`).

Уже вынесено и работает: `fetcher/safe.py` (SafeFetcher, цепочка стратегий),
`fetcher/strategies/*` (httpx, jina, proxy_pool_v2, direct_overpass),
`adapters/base.py` (Protocol `InputAdapter`), `sinks/postgres.py`,
`normalizers/coord_canonical.py`, `observability/daily_source_log.py`,
`retry/policy.py`.

Поэтому задача — **дозавершить вынос и свести дубли**, а не начинать пакет.

## Что переносим и что нет (решение, чтобы не переносить домен)

Переносим только то, у чего нет привязки к домену benz (топливо, инциденты,
украинская география, таблицы `fuel_reports`/`stations`/`target_incidents`).

**НЕ переносим, остаётся в benz:** `nlp_extractor.py` (бренды АЗС, города
Украины), `_city_filter.py`, `classifier.py`/`benz_classifier.py`,
`db_writer.upsert_fuel_reports`, `media_exif_backfill.py` (оркестрация по
своей таблице), `selector.select_level` (правило зашито на бренды АЗС и
`members_count`), `_geo.in_ua_bbox`. Из `_geo.py` общим является только
сплит bbox на квадранты для Overpass — он и переносится, `in_ua_bbox` нет.

## Единицы

### P1. AccountPool: перенести и починить два настоящих пробела
- [ ] Исполнитель: general-purpose, model: sonnet  Зависит от: —
Файлы: `parser_universal/sources/telegram/account_pool.py` (создать),
  `tests/unit/test_account_pool.py` (создать). Benz НЕ трогать — переключение
  потребителей в P5.
Договор: `AccountSlot(name, session_path)` — один `asyncio.Lock` на файл
  сессии; `AccountPool(slots)` — round-robin, `acquire()` отдаёт слот и
  держит его лок; `slot.penalize(seconds)` уводит слот в охлаждение;
  `FloodWaitError` ловится ОТДЕЛЬНО от прочих исключений и уводит слот в
  охлаждение на `e.seconds`. Время берётся инъецируемым `now()`, чтобы тест
  не спал.
Откуда взять: `/root/benz/parsers_hybrid/telethon_parser.py:97` (AccountSlot)
  и `:138` (AccountPool).
Что там СЛОМАНО и должно быть починено переносом (замер 19.09): поле
  `cooling_sec` только инициализируется (`:106`) и читается (`:156`, `:164`),
  **не присваивается нигде** — охлаждение мёртвое, карантин делается руками
  через `BENZ_TG_ACCOUNTS`. `FloodWaitError` не ловится ни разу: в файле он
  только в комментариях (`:9`, `:60`), обработка — общий `except Exception`.
Приёмка: (1) при FloodWait на слоте A следующий `acquire()` отдаёт B, а A не
  выдаётся до истечения охлаждения — время подставлено, теста без `sleep`;
  (2) два одновременных обращения к ОДНОМУ файлу сессии сериализуются, к
  разным — идут параллельно; (3) **тест падает, если убрать присваивание
  `cooling_sec`** — назвать в отчёте, что проверено именно это (сейчас такого
  теста нет ни в одном репозитории, поле мертво); (4) `pytest tests -q` в
  библиотеке зелёный целиком, число тестов больше прежних 134 — назвать оба.
Вернуть: номер PR, четыре пункта приёмки числами, ≤15 строк.

### P2. SAVEPOINT на строку — один хелпер вместо двадцати копий
- [ ] Исполнитель: general-purpose, model: sonnet  Зависит от: —
Файлы: `parser_universal/sinks/savepoint.py` (создать), тест рядом.
Договор: `upsert_rows(conn, sql, rows, on_error=None) -> UpsertResult`
  (`written`, `refused`, `errors`): на каждую строку `SAVEPOINT` →
  `INSERT ... ON CONFLICT` → `RELEASE`, при ошибке строки
  `ROLLBACK TO SAVEPOINT` и продолжение; партия не теряется из-за одной
  строки. Драйвер — psycopg3 (`db` extra), НЕ psycopg2.
Откуда взять образец: паттерн повторён в benz в 20 файлах, канонический —
  `parsers_hybrid/prices/minfin.py:300-335`; у него есть выделенный тест
  `tests/parsers/test_minfin.py:206 test_savepoint_isolation`.
Приёмка: тест на поддельном соединении или на дев-базе показывает, что при
  сбое ОДНОЙ строки из пяти записаны четыре, а не ноль; повторный прогон
  идемпотентен; `errors` содержит номер и текст по каждой отказанной строке.
  Потребителей benz в этой единице НЕ переключать — назвать это в отчёте.
Вернуть: номер PR, число тестов, вывод на партии со сбойной строкой.

### P3. EXIF/GPS из медиа — перенести целиком
- [ ] Исполнитель: general-purpose, model: sonnet  Зависит от: —
Файлы: `parser_universal/media/exif.py` (создать), тесты — переезд из benz.
Договор: `extract_gps_from_jpeg`, `extract_gps_from_quicktime`,
  `extract_gps_from_media`, `compute_confidence` — ровно то, что в
  `/root/benz/parsers_hybrid/_media_extract.py:207,252,323,340` (365 строк,
  ручной разбор TIFF/EXIF IFD, DMS→decimal, ISO6709 для quicktime).
  Доменной привязки у этого кода нет — переносится как есть, без переделки.
Приёмка: тесты benz `tests/parsers/test_media_extract.py` (29) и
  `test_media_extract_fixtures.py` (5) перенесены в библиотеку и зелёные ТАМ
  на том же наборе фикстур — назвать 34 и фактическое число; ни один тест не
  переписан под новый ответ (переписанный тест = перенос сломал разбор).
Вернуть: номер PR, два числа тестов, список перенесённых фикстур.

### P4. Математика координат: три независимые реализации → одна
- [ ] Исполнитель: general-purpose, model: sonnet  Зависит от: —
Файлы: `parser_universal/normalizers/coord_canonical.py` (дополнить), тест рядом.
Договор: одна функция DMS/DDM→decimal, на входе и текст, и EXIF-рациональные;
  у разбора есть исход «не координата» (отказ), и он считается наравне.
Замер 19.09: одна и та же математика написана трижды —
  `/root/benz/parsers_hybrid/_media_extract.py:63` (`_dms_to_decimal`, из EXIF),
  `/root/parser-universal/parser_universal/normalizers/coord_canonical.py:30`,
  `/root/sup-app/sup-app/scripts/tg/extract_coords.py:53` (`_DDM`, из текста).
Приёмка: эталонные пары в тесте — DMS из рациональных, DDM из текста, юг/запад
  дают минус, мусор даёт отказ; **и сверка «не сломал»**: на прежнем выходе
  `scripts/tg/extract_coords.py` (прогнать до правки, сохранить, прогнать после)
  координаты совпадают до 1e-7 — назвать число сверенных записей и число
  расхождений. Потребителей не переключать (это P5), но сверку сделать ЗДЕСЬ.
Вернуть: номер PR, число эталонных пар, число сверенных записей и расхождений.

### P5. Потребители переходят на библиотеку, вставка `sys.path` уходит
- [ ] Исполнитель: general-purpose, model: sonnet  Зависит от: P1, P3, P4
Файлы: benz — `parsers_hybrid/telethon_parser.py`, `_media_extract.py`,
  9 остальных файлов со вставкой; sup-app — `scripts/tg/extract_coords.py`.
Договор: в benz остаются ТОНКИЕ ре-экспорты под старыми именами (чтобы ни
  один вызывающий модуль и ни один cron не переписывался), сама реализация
  берётся из `parser_universal`. `sys.path.insert(0, "/root/parser-universal")`
  удаляется — пакет установлен системно (замер 19.09).
Приёмка: `grep -rl 'parser-universal' /root/benz --include='*.py'` — ноль;
  `python3 -m pytest tests/parsers -q` в benz зелёный, число назвать и
  сравнить с числом ДО правки (обязательно снять до); один cron benz прогнан
  руками (`scripts/cron_media_exif.sh` в режиме без записи, если есть) и
  вернул 0. **Крон benz на паузе с 20.08.2026 — не включать, только руками.**
Вернуть: три числа (тесты до, тесты после, код выхода cron).

### P6. Шаблон cron-обёртки (flock + preflight + лог)
- [ ] Исполнитель: sup-ops  Зависит от: —
Договор: один образец `scripts/cron_wrapper.sh.template` в библиотеке:
  `set -euo pipefail`, `flock` на lock-файл, проверка DSN до работы, лог в
  указанный файл, ненулевой код при отказе preflight. Паттерн снят с 24
  одинаковых `scripts/cron_*.sh` benz.
Приёмка: шаблон запускается с тестовой командой, второй одновременный запуск
  отбивается flock'ом (показать оба кода выхода); при пустом DSN падает ДО
  вызова полезной команды.
Вернуть: два кода выхода.

### P7. Разнобой драйверов и чтения `.env` — назвать целевой вариант, чинить ПОТОМ
- [ ] Исполнитель: сам (решение)  Зависит от: P5
Замер: в benz два драйвера Postgres одновременно — `parsers_hybrid/db_writer.py`
  на psycopg2, `app/core/config.py` на psycopg[binary] v3; и два способа
  читать `.env` — pydantic-settings в app и самописный построчный разбор в
  `parsers_hybrid/_env.py:29` + `telethon_parser.py:67 _read_env()`.
Решение: целевой вариант — psycopg3 и pydantic-settings. **Не смешивать с
  переносом**: смена драйвера отдельным PR после P5, иначе падение нельзя
  будет отнести ни к переносу, ни к драйверу.
Приёмка: отдельный план на смену драйвера с приёмкой на боевых прогонах benz.

### P8. Сторона sup-app: ретраи и бэкофф — сначала сверка, потом объединение
- [ ] Исполнитель: general-purpose, model: sonnet  Зависит от: —
Замер разведки: в sup-app есть свои ретраи в `scripts/import_wikiloc_ratelimit.py`,
  `scripts/import_brouter_batch.py`, `scripts/velobarnaul_parser.py`; с
  `parser_universal/retry/policy.py` и `fetcher/safe.py` они НЕ сверялись —
  совпадение предполагается по названию, а не замерено.
Приёмка разведки: назвать, чем отличается каждая из трёх реализаций от
  `RetryPolicy` (число попыток, джиттер, какие коды и исключения повторяются,
  что делает на 429) — таблицей. Только после этого решать про объединение;
  «похоже по названию» решением не считается.
Вернуть: таблицу отличий, вердикт по каждой из трёх.

## Порядок

P1, P2, P3, P4 независимы по файлам и идут параллельно — каждая своим
worktree библиотеки и своим PR. P5 после P1/P3/P4 (он переключает
потребителей и требует, чтобы переносимое уже лежало в библиотеке). P6 и P8
в любое время. P7 — решение после P5, отдельным планом.

Риск, который держим в голове: benz — живой проект со своим cron. Перенос
идёт «скопировать в библиотеку → тонкий ре-экспорт в benz», а не
«вырезать»; ни один вызывающий модуль benz не переписывается.
