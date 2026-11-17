# Руководство пользователя

## 1. Требования

- Python 3.11 или новее.
- Git в `PATH`.
- Windows, Linux или macOS. Основная проверенная среда - Windows.
- Права администратора не нужны.
- Сеть нужна только для первой установки зависимостей и клонирования демонстрационных репозиториев.

Обязательных внешних библиотек нет: ядро, интерфейс, графы, метрики и статистика работают на стандартной библиотеке. Дополнительно:

| Пакет | Зачем | Обязателен |
| --- | --- | --- |
| `reportlab` | PDF-отчёт | нет, без него работает HTML |
| `hypothesis` | property-тесты | нет, нужен только для полного набора тестов |

## 2. Установка

### Вариант без установки

```powershell
cd C:\Users\sound\projectpulse
$env:PYTHONPATH = "C:\Users\sound\projectpulse\src;C:\Users\sound\projectpulse"
python -m projectpulse --version
```

### Вариант с виртуальным окружением

```powershell
cd C:\Users\sound\projectpulse
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[pdf,test]"
projectpulse --version
```

Установка в пользовательский каталог не требует администратора. Если политика PowerShell запрещает активацию, используйте `python -m projectpulse` с `PYTHONPATH` или `Set-ExecutionPolicy -Scope Process`.

## 3. Каталог данных

По умолчанию:

```text
%LOCALAPPDATA%\ProjectPulse\
```

Внутри:

| Путь | Содержимое |
| --- | --- |
| `projectpulse.db` | SQLite-база цифрового двойника |
| `projectpulse.log` | журнал импортов, ошибок и плагинов |
| `reports/` | сгенерированные HTML и PDF |
| `plugins/` | пользовательские плагины |
| `cache/` | временные файлы замеров |

Переопределение:

```powershell
python -m projectpulse --home D:\pp_data gui
$env:PROJECTPULSE_HOME = "D:\pp_data"
```

Приоритет: аргумент `--home`, затем переменная `PROJECTPULSE_HOME`, затем каталог по умолчанию. Каталоги создаются автоматически.

## 4. Демонстрационные репозитории

`repos.json` фиксирует два внешних проекта с лицензией MIT:

| Имя | Роль | Коммит |
| --- | --- | --- |
| pluggy | здоровый | `46a80723004b2f6c3a57c387c3a1d50e17fb8c25` |
| django-extensions | проблемный | `9bdf31556675e795c7c7c4f033f194dc075d5919` |

Подготовка:

```powershell
python scripts\prepare_samples.py
```

Скрипт клонирует репозитории в `samples/` и переключает их на указанные коммиты. Повторный запуск проверяет текущий HEAD и не трогает уже подготовленные каталоги. Без сети используйте `--no-network`: скрипт сообщит, каких каталогов не хватает, и не будет пытаться клонировать.

После подготовки сеть не нужна: вся история уже локальна.

## 5. Командная строка

Общий вид:

```text
python -m projectpulse [--home КАТАЛОГ] [--no-plugins] КОМАНДА [параметры]
```

### 5.1 Добавление и список

```powershell
python -m projectpulse add --repo samples\pluggy --name pluggy
python -m projectpulse repos
python -m projectpulse repos --json
```

`add` только регистрирует путь. Для анализа нужен `index`.

### 5.2 Индексация

```powershell
python -m projectpulse index --repo samples\pluggy --mode full
python -m projectpulse index --repo samples\pluggy --mode incremental
python -m projectpulse index --repo samples\pluggy --mode rebuild
```

Параметры:

- `--repo` - путь к Git-репозиторию или имя уже добавленного проекта;
- `--name` - отображаемое имя при первом добавлении;
- `--mode` - `full`, `incremental` или `rebuild`;
- `--json` - машиночитаемый результат;
- `--quiet` - без индикатора прогресса.

Коды возврата: 0 - успех, 1 - ошибка приложения, 2 - отмена, 130 - прерывание с клавиатуры.

### 5.3 Отчёт

```powershell
python -m projectpulse report --repo pluggy --format html,pdf --out reports
python -m projectpulse report --repo pluggy --format html --out reports\pluggy.html
```

Если `--out` - каталог, имя файла формируется автоматически. Если указан файл с расширением, он используется напрямую. Поддерживаются `html` и `pdf` в любом сочетании через запятую.

### 5.4 Сравнение

```powershell
python -m projectpulse compare --a pluggy --b django-extensions
python -m projectpulse compare --a pluggy --b django-extensions --json
```

Сравниваются здоровье и пять показателей. В конце печатается вердикт.

### 5.5 Мини-исследование

```powershell
python -m projectpulse research `
  --healthy samples\pluggy `
  --problematic samples\django-extensions `
  --out reports\research_report
```

Если проекты ещё не проиндексированы, команда выполнит инкрементальный импорт. Флаг `--no-index` запрещает автоматическую индексацию и требует готовых записей в базе. Результат - `research_report.md` и `research_report.json`.

### 5.6 Плагины

```powershell
python -m projectpulse plugins
python -m projectpulse plugins --json
```

Показывает число и источники метрик и правил, включая загруженные плагины.

### 5.7 Замеры

```powershell
python -m projectpulse bench --repo samples\pluggy --runs 1 --json
```

Замер выполняется на временном клоне, чтобы не менять исходную историю. Перед каждым инкрементальным проходом создаётся пробный коммит. Временный клон и его запись в базе удаляются после замера.

## 6. Графический интерфейс

```powershell
python -m projectpulse gui
```

или просто:

```powershell
python -m projectpulse
```

Сценарий:

1. "Проекты" - добавить или клонировать репозиторий.
2. "Полный" - первый импорт.
3. "Дашборд" - здоровье, компоненты, показатели, находки.
4. "Динамика" - недельные ряды, релизы, аномалии.
5. "Граф" - срезы, проекции файлов и сущностей, эго-граф.
6. "Сравнение" - два проекта и мини-исследование.
7. "Отчёт" - HTML и PDF.
8. "Журнал" - диагностика.

Подробнее с screenshots: [ui.md](ui.md).

## 7. Отчёты

HTML-отчёт автономен:

- нет `<script>`, внешних стилей и внешних изображений;
- графики - встроенный SVG;
- таблицы и рекомендации читаются без сети;
- размер около 74-101 КБ на демонстрационных данных.

PDF содержит те же разделы и строится reportlab. Если reportlab не установлен, запрос PDF завершится понятной ошибкой, а HTML продолжит работать.

Разделы: "Сводка", "Риски", "Динамика", "Граф зависимостей", "Рекомендации", "Приложение: воспроизводимость". В приложении указаны HEAD, ветка, версия, пороги и статистика запуска.

## 8. Настройка порогов

Файл `thresholds.json` в домашнем каталоге приложения переопределяет пороги:

```json
{
  "churn_recent_days": 90,
  "churn_spike_z": 2.5,
  "ownership_share_high": 0.85,
  "fix_pressure_growth": 0.5
}
```

Правила:

- неизвестные ключи игнорируются;
- битый JSON приводит к значениям по умолчанию;
- изменения применяются при следующем импорте;
- уже сохранённые находки не пересчитываются автоматически.

Полный список полей - в `src/projectpulse/core/config.py`.

## 9. Плагины

Плагин - Python-файл в каталоге `plugins/` домашнего каталога приложения или во встроенном каталоге проекта. Он объявляет `METRICS`, `RULES` и необязательную функцию `register(container)`.

```powershell
python -m projectpulse plugins
```

Если плагин сломан, он пропускается с записью в журнале, остальные работают. Подробнее: [plugins.md](plugins.md).

## 10. Диагностика

| Симптом | Что проверить |
| --- | --- |
| "Репозиторий не найден" | выполнить `index --repo <путь>` или указать точное имя из `repos` |
| "Не является Git-репозиторием" | наличие `.git` и доступность `git --version` |
| Импорт долго не начинается | занятость другой фоновой задачи в GUI, права на каталог |
| PDF не создаётся | установлен ли `reportlab` |
| Пустой дашборд | был ли успешный запуск, статус в `runs` |
| Плагин не виден | имя файла `*.py`, отсутствие синтаксической ошибки, запись в журнале |
| Кириллица в консоли Windows | `chcp 65001` или `$env:PYTHONIOENCODING = "utf-8"` |
| Сбой после обновления схемы | `index --mode rebuild` |

Журнал: `%LOCALAPPDATA%\ProjectPulse\projectpulse.log` или `<home>\projectpulse.log`.

## 11. Полный демонстрационный прогон

```powershell
$env:PYTHONPATH = "C:\Users\sound\projectpulse\src;C:\Users\sound\projectpulse"
python scripts\prepare_samples.py
python scripts\run_all.py --reindex --bench --tests
```

Скрипт:

1. проверяет демонстрационные репозитории;
2. индексирует pluggy и django-extensions;
3. формирует HTML и PDF;
4. сравнивает проекты и сохраняет `compare.json`;
5. запускает мини-исследование;
6. при `--bench` выполняет замеры;
7. при `--tests` запускает 106 тестов;
8. пишет `reports/summary.json`.

## 12. Удаление

Приложение не устанавливает службы и драйверы. Достаточно удалить каталог проекта и каталог данных. Демонстрационные репозитории лежат в `samples/` и исключены из Git.
