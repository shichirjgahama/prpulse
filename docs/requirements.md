# Карта требований

## 1. Как читать таблицу

Столбец "Где" указывает основной файл или каталог. Столбец "Доказательство" - тест, отчёт или документ, по которому требование можно проверить. Все пути относительны корня проекта.

## 2. Модуль 1. Архитектура и модель данных

| Требование | Где | Доказательство |
| --- | --- | --- |
| Архитектурная документация | `docs/architecture.md` | слои, компоненты, сценарии, решения |
| Не менее двух UML-диаграмм | `docs/architecture.md` | компоненты, классы, две sequence-диаграммы |
| ER-модель | `docs/data-model.md` | Mermaid `erDiagram` и описание таблиц |
| Расширяемость плагинами | `core/plugins.py`, `analysis/metrics/base.py`, `analysis/rules/base.py` | реестры, entry points, `plugins/example_todo.py`, `tests/test_config_plugins.py` |
| Разделение слоёв | `ui/`, `core/`, `analysis/`, `storage/`, `gitio/` | зависимости направлены внутрь, UI не импортируется анализом |
| Детерминизм | `core/utils.py`, `analysis/stats.py`, SQL-сортировки | фиксированный seed 42, сортировка списков, время от HEAD |
| Работа офлайн | `gitio/runner.py`, `storage/db.py` | только локальный Git и SQLite после клонирования |
| Без прав администратора | `core/config.py` | данные в `%LOCALAPPDATA%` или `PROJECTPULSE_HOME` |

## 3. Модуль 2. Индексация, граф, метрики, риски

| Требование | Где | Доказательство |
| --- | --- | --- |
| Полная индексация | `indexer/pipeline.py` | `index --mode full`, `test_full_index_builds_complete_twin` |
| Инкрементальная индексация | `indexer/pipeline.py` | дочитывание коммитов, разбор только изменённых файлов, `test_incremental_after_new_commits` |
| Пересборка с нуля | `indexer/pipeline.py` | `index --mode rebuild`, `test_rebuild_recreates_state` |
| Защита от расхождения истории | `indexer/pipeline.py` | fallback на полный импорт, `test_diverged_history_falls_back_to_full` |
| Две проекции графа | `analysis/graph.py`, `analysis/imports.py` | файловая и сущностная, `test_graph.py` |
| Графовые алгоритмы вручную | `analysis/graph.py` | итеративный Тарьян, топосортировка, diff, циклы |
| Версионирование графа | `storage/schema.sql`, `indexer/pipeline.py` | `graph_snapshots`, `snapshot_nodes`, `snapshot_edges`, срезы HEAD, тегов, веток |
| 5 классических метрик | `analysis/metrics/builtin.py` | LOC, сложность, churn, владение, bus factor |
| 3 собственные метрики | `analysis/metrics/builtin.py` | FPI, coupling pressure, IVI, формулы и мотивация в `docs/metrics.md` |
| 2 временных ряда | `analysis/context.py`, `analysis/metrics/builtin.py` | волатильность churn, дрейф владения |
| 10 метрик всего | `analysis/metrics/builtin.py` | `default_metrics()`, `tests/test_metrics_rules.py` |
| 8 и более правил риска | `analysis/rules/builtin.py` | 10 правил, `default_rules()` |
| 3 и более правила на трендах | `analysis/rules/builtin.py` | 4 правила: churn spike, volatility rise, fix pressure, ownership drift |
| Уровни важности и объяснения | `analysis/rules/base.py` | `critical`, `warning`, `info`, поля `explanation` и `recommendation` |
| Индекс здоровья 0-100 | `analysis/health.py` | четыре компонента штрафа, `docs/risks.md` |
| Пороги настраиваемы | `core/config.py` | `Thresholds`, `thresholds.json`, `tests/test_config_plugins.py` |

## 4. Модуль 3. Интерфейс и отчёты

| Требование | Где | Доказательство |
| --- | --- | --- |
| Настольный интерфейс | `ui/app.py`, `ui/views.py` | Tkinter, 7 экранов, `docs/ui.md` |
| Дашборд | `ui/views.py`, `ui/widgets.py` | здоровье, компоненты, KPI, находки, скриншот `docs/images/dashboard-pluggy.png` |
| Временная шкала | `ui/views.py`, `ui/widgets.py` | недельные ряды, релизы, аномалии, `docs/images/timeline.png` |
| Навигация по графу | `ui/views.py`, `ui/widgets.py` | срезы, проекции, эго-граф, перецентрирование, `docs/images/graph-files.png` |
| Сравнение двух репозиториев | `analysis/compare.py`, `ui/views.py` | здоровье и 5 показателей, вердикт, `docs/images/compare.png` |
| HTML-отчёт | `report/html.py` | автономный файл, SVG, без скриптов |
| PDF-отчёт | `report/pdf.py` | reportlab, та же структура |
| Обязательные разделы | `report/html.py`, `report/pdf.py` | "Сводка / Риски / Динамика / Граф / Рекомендации", `test_html_report_has_required_sections` |
| Готовые отчёты | `reports/` | `pluggy.html`, `pluggy.pdf`, `django-extensions.html`, `django-extensions.pdf` |
| Сравнение в JSON | `reports/compare.json` | 65.30 против 41.60, вердикт |
| Мини-исследование в GUI и CLI | `analysis/research.py`, `app.py` | кнопка "Исследование", команда `research` |

## 5. Модуль 4. Качество, исследование, документация

| Требование | Где | Доказательство |
| --- | --- | --- |
| 25 и более тестов | `tests/` | 106 тестов, `docs/testing.md` |
| Модульные тесты | `tests/test_parser.py`, `test_stats.py`, `test_utils.py`, `test_graph.py`, `test_metrics_rules.py`, `test_config_plugins.py`, `test_storage.py` | 64 теста |
| Интеграционные тесты | `tests/test_pipeline.py`, `test_git_runner.py`, `test_report.py`, `test_research_compare.py`, `test_cli.py` | 33 теста на реальном Git и SQLite |
| Property-тесты | `tests/test_properties.py` | 9 свойств hypothesis, `max_examples=60` |
| cProfile | `scripts/profile_index.py` | `reports/profile_full.txt`, `reports/profile_full.prof` |
| Две доказанные оптимизации | `gitio/runner.py`, `indexer/pipeline.py` | пакетное чтение blob 143x, кэш разбора 2181 -> 718 вызовов, `docs/performance.md` |
| Обработка ошибок | `core/events.py`, `indexer/pipeline.py`, `report/service.py`, `ui/app.py` | таблица отказоустойчивости в `docs/testing.md` |
| Мини-исследование | `analysis/research.py`, `analysis/stats.py` | гипотеза, недельные ряды, корреляции, p-value |
| Пирсон и Спирмен вручную | `analysis/stats.py` | без scipy, `tests/test_stats.py` |
| Перестановочный тест | `analysis/stats.py` | 500 перестановок, seed 42 |
| Запрет готовых анализаторов | `pyproject.toml` | нет radon, pylint, flake8, scipy, networkx |
| Разрешённые зависимости | `pyproject.toml` | ядро без зависимостей, опционально reportlab и hypothesis |
| Документация | `docs/` | 12 страниц, включая эту карту |
| Воспроизводимость | `repos.json`, `scripts/prepare_samples.py`, `scripts/run_all.py` | фиксированные коммиты, один прогон |

## 6. Ограничения задания

| Ограничение | Как выполнено |
| --- | --- |
| Только stdlib и разрешённые библиотеки | обязательных зависимостей нет; reportlab только для PDF; hypothesis только для тестов; dulwich не используется, Git вызывается через CLI |
| Без графовых библиотек для ядра | Тарьян, циклы, топосортировка и diff реализованы в `analysis/graph.py`; Tk Canvas рисует эго-граф |
| Без готовых анализаторов кода | парсер на `ast` и `tokenize`, метрики считаются вручную |
| Без scipy | Пирсон, Спирмен, ранги и перестановки реализованы в `analysis/stats.py` |
| Офлайн после клонирования | все данные в SQLite, отчёты автономны, сеть не используется |
| Без администратора | виртуальное окружение и пользовательский каталог данных |
| Python 3.11+ | `requires-python = ">=3.11"`, синтаксис совместим |

## 7. Демонстрационная пара

`repos.json` фиксирует два внешних открытых проекта с лицензией MIT:

- `pytest-dev/pluggy`, коммит `46a80723004b2f6c3a57c387c3a1d50e17fb8c25`, роль "здоровый";
- `django-extensions/django-extensions`, коммит `9bdf31556675e795c7c7c4f033f194dc075d5919`, роль "проблемный".

Такая пара даёт реалистичную историю и воспроизводимые числа: 850 и 2889 коммитов, 36 и 246 Python-файлов, здоровье 65.3 и 41.6. Оба репозитория не входят в поставку и скачиваются скриптом `prepare_samples.py`.

Если требуется пара репозиториев под собственным аккаунтом, замените `url`, `path` и `commit` в `repos.json` и выполните `prepare_samples.py` заново. Код и анализ не зависят от конкретных имён.

## 8. Быстрая проверка

```powershell
$env:PYTHONPATH = "src;."
python -m unittest discover -s tests
python scripts\run_all.py --reindex --bench
```

Ожидаемый итог:

- 106 тестов проходят;
- `reports/summary.json` содержит два проекта;
- HTML и PDF содержат обязательные разделы;
- `reports/compare.json` содержит вердикт;
- `reports/research_report/` содержит Markdown и JSON;
- `reports/benchmark.json` и `reports/microbench.json` содержат замеры.

## 9. Что не входит в работу

- Поддержка языков кроме Python.
- Автоматическое исправление кода.
- Серверная часть и многопользовательский режим.
- Сборка установщика MSIX.
- README по требованию заказчика: точка входа - `docs/index.md`.
