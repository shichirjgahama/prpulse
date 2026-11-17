# Плагины

## 1. Зачем нужны плагины

Ядро ProjectPulse не нужно менять, чтобы добавить новый показатель или правило. Плагин объявляет метрику или правило, а реестры подхватывают их при старте. Это выполнено в рамках требования о расширяемости архитектуры.

Точки расширения:

| Точка | Контракт | Результат |
| --- | --- | --- |
| метрика | `Metric.compute(ctx)` | список `MetricValue` |
| правило | `Rule.evaluate(ctx, metrics)` | список `Finding` |
| сервис | `register(container)` | регистрация в контейнере |
| entry point | группа `projectpulse.metrics` или `projectpulse.rules` | класс или список классов |

## 2. Контракт метрики

```python
from projectpulse.analysis.metrics.base import Metric, MetricValue


class TodoDensityMetric(Metric):
    name = "todo_density"
    version = "1.0"
    kind = "plugin"
    description = "Число TODO/FIXME на 1000 строк кода"
    unit = "на 1000 LOC"
    formula = "TD = todo_count / max(loc, 1) * 1000"

    def compute(self, ctx):
        values = []
        for path, row in sorted(ctx.files_by_path.items()):
            loc = int(row.get("loc", 0))
            todos = int(row.get("todo_count", 0))
            values.append(MetricValue("file", path, self.name, todos / max(loc, 1) * 1000.0))
        return values
```

Обязательно:

- `name` - уникальное имя;
- `compute(ctx)` - список значений.

Рекомендуется:

- `version`, `description`, `unit`, `formula` - попадают в каталог плагинов и отчёт;
- `kind = "plugin"`, чтобы отличать расширение от встроенной метрики;
- сортировка входов и детерминированные значения;
- защита от деления на ноль через `safe_div` или `max(..., 1)`;
- область `project`, `module`, `file` или `entity` в каждом `MetricValue`.

Метрика может вернуть несколько областей. Например, `todo_density` возвращает значения по файлам и одно агрегированное значение по проекту.

## 3. Контракт правила

```python
from projectpulse.analysis.rules.base import Finding, Rule
from projectpulse.core.utils import is_support_path


class TodoClusterRule(Rule):
    name = "todo_cluster"
    version = "1.0"
    description = "В файле накопилось три и более отметок TODO/FIXME"
    trend = False

    def evaluate(self, ctx, metrics):
        findings = []
        for path, row in sorted(ctx.files_by_path.items()):
            count = int(row.get("todo_count", 0))
            if count < 3 or is_support_path(path):
                continue
            findings.append(
                Finding(
                    rule=self.name,
                    severity="warning" if count >= 5 else "info",
                    target=path,
                    title="Скопление TODO/FIXME",
                    explanation=f"В файле {count} незавершённых отметок.",
                    recommendation="Разобрать отметки и назначить владельца.",
                    value={"todo_count": count},
                )
            )
        return findings
```

Поля `Finding`:

| Поле | Смысл |
| --- | --- |
| `rule` | имя правила |
| `severity` | `critical`, `warning` или `info` |
| `target` | файл, модуль, сущность или проект |
| `title` | короткое название |
| `explanation` | почему сработало, с числами |
| `recommendation` | что сделать |
| `value` | JSON со значениями для отчёта |

Правило не должно бросать исключения на пустых данных. Движок всё равно изолирует сбой, но пропущенное правило означает потерянный риск.

## 4. Загрузка

Порядок:

1. Entry points `projectpulse.metrics` и `projectpulse.rules`.
2. Каталог `plugins/` в домашнем каталоге приложения.
3. Встроенный каталог `plugins/` рядом с проектом.

Файлы, начинающиеся с `_`, пропускаются. Одинаковые пути не загружаются дважды. Внутри файла читаются:

- `METRICS` - классы или экземпляры метрик;
- `RULES` - классы или экземпляры правил;
- `register(container)` - необязательный хук.

Если файл не компилируется, падает при импорте или регистрации, он пропускается с записью в журнале. Остальные плагины и встроенный анализ продолжают работать.

Отключить все плагины можно флагом:

```powershell
python -m projectpulse --no-plugins plugins
```

## 5. Контейнер сервисов

`register(container)` получает `ServiceContainer` с сервисами:

| Имя | Тип |
| --- | --- |
| `config` | `AppConfig` |
| `store` | `Store` |
| `git` | `GitRunner` |
| `metrics` | `MetricRegistry` |
| `rules` | `RuleRegistry` |
| `logger` | `logging.Logger` |
| `indexer` | `Indexer` |
| `plugins` | `PluginManager` |

Контейнер - минимальный DI без магии: `register(name, value)`, `get(name, default)`, `require(name)`, `names()`. Плагин может зарегистрировать свой сервис, но не должен перезаписывать встроенный без необходимости.

## 6. Пример в комплекте

Файл `plugins/example_todo.py` содержит:

- `TodoDensityMetric` - плотность TODO/FIXME на 1000 LOC по файлам и проекту;
- `TodoClusterRule` - предупреждение при 3-4 отметках, информация при 5 и более;
- `register(container)` - регистрирует сервис `example_todo_plugin`.

Проверка:

```powershell
python -m projectpulse plugins
```

В выводе появятся `todo_density` и `todo_cluster` с источником `file:...example_todo.py`. После импорта метрика попадает в `metric_values`, а находки - в `findings`, отчёт и дашборд.

## 7. Установка как пакета

Плагин можно оформить отдельным пакетом с entry points:

```toml
[project.entry-points."projectpulse.metrics"]
my_metric = "my_package.metrics:MyMetric"

[project.entry-points."projectpulse.rules"]
my_rule = "my_package.rules:MyRule"
```

После `pip install` классы загрузятся без копирования файлов. Это удобно для команд, но не обязательно для задания.

## 8. Ограничения

- Плагин работает в том же процессе, поэтому не изолирован от падения интерпретатора.
- Нет версионирования API плагинов, кроме соглашения о полях классов.
- Плагин не может добавить новую таблицу в схему без миграции.
- Метрика плагина участвует в отчёте, но не входит в фиксированный индекс здоровья, если правило явно не учитывает её.
- Внешние зависимости плагина должны быть установлены отдельно.

## 9. Тестирование плагина

```python
from projectpulse.core.plugins import MetricRegistry, PluginManager, RuleRegistry, ServiceContainer

manager = PluginManager(MetricRegistry(), RuleRegistry(), ServiceContainer(), [Path("plugins")])
loaded = manager.load_all()
assert loaded
```

`tests/test_config_plugins.py` проверяет загрузку файла, регистрацию метрики, правила и сервиса, а также пропуск битого плагина. Для собственного плагина достаточно аналогичного теста и проверки `plugins --json`.
