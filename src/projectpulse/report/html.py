"""HTML-отчёт: автономный файл с inline CSS и SVG."""

from __future__ import annotations

import html
import json
from datetime import datetime
from string import Template
from typing import Iterable, Sequence

from projectpulse.report.builder import ReportData

SEVERITY_LABELS = {"critical": "Критично", "warning": "Предупреждение", "info": "Информация"}
SEVERITY_COLORS = {"critical": "#dc2626", "warning": "#d97706", "info": "#0284c7"}
CHART_COLORS = ["#0f766e", "#2563eb", "#c2410c", "#7c3aed", "#be123c"]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def number(value: float | int | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    formatted = f"{float(value):,.{digits}f}".replace(",", " ")
    if digits <= 0:
        formatted = formatted.replace(".", "")
    return formatted


def percent(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.{digits}f}%"


def _severity_badge(severity: str) -> str:
    color = SEVERITY_COLORS.get(severity, "#64748b")
    label = SEVERITY_LABELS.get(severity, severity)
    return f'<span class="badge" style="background:{color}">{esc(label)}</span>'


def svg_donut(score: float) -> str:
    radius = 54.0
    circumference = 2 * 3.14159265 * radius
    filled = max(0.0, min(100.0, score)) / 100.0
    color = "#16a34a" if score >= 80 else "#ca8a04" if score >= 60 else "#ea580c" if score >= 40 else "#dc2626"
    dash = circumference * filled
    return f"""<svg viewBox="0 0 160 160" width="170" height="170" role="img" aria-label="Индекс здоровья {score:.1f}">
  <circle cx="80" cy="80" r="{radius}" fill="none" stroke="#e2e8f0" stroke-width="14"/>
  <circle cx="80" cy="80" r="{radius}" fill="none" stroke="{color}" stroke-width="14"
          stroke-dasharray="{dash:.2f} {circumference:.2f}" stroke-linecap="round"
          transform="rotate(-90 80 80)"/>
  <text x="80" y="86" text-anchor="middle" font-size="34" font-weight="700" fill="#0f172a">{score:.0f}</text>
  <text x="80" y="108" text-anchor="middle" font-size="12" fill="#64748b">из 100</text>
</svg>"""


def _aligned_series(series: Sequence[dict]) -> tuple[list[str], list[dict]]:
    buckets = sorted({point["bucket"] for item in series for point in item["points"]})
    aligned = []
    for item in series:
        values = {point["bucket"]: float(point["value"]) for point in item["points"]}
        aligned.append({**item, "values": [values.get(bucket, 0.0) for bucket in buckets]})
    return buckets, aligned


def svg_line_chart(
    series: Sequence[dict],
    title: str,
    markers: dict[str, str] | None = None,
    anomalies: Iterable[str] = (),
    height: int = 250,
    y_unit: str = "",
) -> str:
    """Линейный график с маркерами релизов и аномалий."""
    if not series:
        return '<p class="muted">Нет данных для графика.</p>'
    markers = markers or {}
    anomaly_set = set(anomalies)
    buckets, aligned = _aligned_series(series)
    if not buckets:
        return '<p class="muted">Нет данных для графика.</p>'
    width = 880
    left, right, top, bottom = 64, 18, 42, 44
    plot_w = width - left - right
    plot_h = height - top - bottom
    maximum = max((max(item["values"]) for item in aligned), default=1.0)
    maximum = maximum if maximum > 0 else 1.0
    if maximum < 10:
        maximum = 10.0
    step = plot_w / max(1, len(buckets) - 1)
    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="{esc(title)}">',
        f'<text x="{left}" y="20" font-size="14" font-weight="600" fill="#0f172a">{esc(title)}</text>',
    ]
    for line in range(5):
        y = top + plot_h * line / 4
        value = maximum * (4 - line) / 4
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e2e8f0" stroke-width="1"/>')
        parts.append(
            f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="10" fill="#64748b">{number(value, 0)}</text>'
        )
    for index, bucket in enumerate(buckets):
        if bucket in markers:
            x = left + index * step
            parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_h}" stroke="#94a3b8" stroke-width="1" stroke-dasharray="3 3"/>')
            label = markers[bucket]
            parts.append(
                f'<text x="{x:.1f}" y="{top-8}" text-anchor="middle" font-size="9" fill="#475569">{esc(label[:18])}</text>'
            )
    for item_index, item in enumerate(aligned):
        color = item.get("color", CHART_COLORS[item_index % len(CHART_COLORS)])
        points = []
        for index, value in enumerate(item["values"]):
            x = left + index * step
            y = top + plot_h * (1 - min(1.0, value / maximum))
            points.append(f"{x:.1f},{y:.1f}")
        parts.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>'
        )
        if len(points) <= 60:
            for index, value in enumerate(item["values"]):
                x = left + index * step
                y = top + plot_h * (1 - min(1.0, value / maximum))
                if buckets[index] in anomaly_set:
                    parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#dc2626" stroke="#ffffff" stroke-width="1.5"/>')
                else:
                    parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.3" fill="{color}"/>')
        legend_x = left + item_index * 220
        parts.append(f'<rect x="{legend_x}" y="{height-22}" width="10" height="10" fill="{color}" rx="2"/>')
        parts.append(
            f'<text x="{legend_x+15}" y="{height-13}" font-size="11" fill="#334155">{esc(item["name"])}</text>'
        )
    label_indexes = {0, len(buckets) // 2, len(buckets) - 1}
    for index in sorted(label_indexes):
        x = left + index * step
        parts.append(
            f'<text x="{x:.1f}" y="{top+plot_h+20}" text-anchor="middle" font-size="10" fill="#64748b">{esc(buckets[index])}</text>'
        )
    if y_unit:
        parts.append(
            f'<text x="{left}" y="{top+plot_h+38}" font-size="10" fill="#94a3b8">{esc(y_unit)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _component_bars(data: ReportData) -> str:
    health = data.health.get("components", {}) if data.health else {}
    components = health.get("components", {}) if isinstance(health, dict) else {}
    rows = []
    for key in ("risks", "hotspots", "knowledge", "structure"):
        item = components.get(key, {})
        max_value = float(item.get("max", 1) or 1)
        penalty = float(item.get("penalty", 0) or 0)
        ratio = min(1.0, penalty / max_value) if max_value else 0.0
        color = "#16a34a" if ratio < 0.25 else "#ca8a04" if ratio < 0.6 else "#dc2626"
        rows.append(
            f"""<div class="bar-row">
  <div class="bar-label">{esc(item.get("title", key))}<span>{penalty:.1f} / {max_value:.0f}</span></div>
  <div class="bar-track"><div class="bar-fill" style="width:{ratio*100:.1f}%;background:{color}"></div></div>
  <div class="bar-detail">{esc(item.get("detail", ""))}</div>
</div>"""
        )
    return "".join(rows)


def _kpi(title: str, value: str, hint: str = "") -> str:
    return f"""<div class="kpi"><div class="kpi-title">{esc(title)}</div>
<div class="kpi-value">{esc(value)}</div><div class="kpi-hint">{esc(hint)}</div></div>"""


def _summary(data: ReportData) -> str:
    health_info = data.health.get("components", {}) if data.health else {}
    score = float(data.health.get("score", 0) or 0)
    label = health_info.get("label", "")
    counts = health_info.get("counts", {})
    stats = data.stats
    repo = data.repo
    run = data.run
    timings = {}
    try:
        timings = json.loads(run.get("stats_json") or "{}").get("phase_ms", {})
    except ValueError:
        timings = {}
    kpis = [
        _kpi("LOC", number(stats.get("loc"), 0), f"SLOC {number(stats.get('sloc'), 0)}"),
        _kpi("Коммиты", number(stats.get("commits"), 0), f"авторов {number(stats.get('authors'), 0)}"),
        _kpi("Файлы", number(stats.get("files"), 0), f"сущностей {number(stats.get('entities'), 0)}"),
        _kpi(
            "Сложность",
            number(data.metric("avg_function_complexity"), 1),
            "макс. функция " + number(data.metric("complexity_max"), 0),
        ),
        _kpi("Churn 90 дней", number(data.metric("churn_90d"), 0), "добавлено + удалено"),
        _kpi("Доля багфиксов", percent(data.metric("bugfix_share")), "по сообщениям коммитов"),
        _kpi("Bus factor", number(data.metric("bus_factor"), 0), "авторов " + number(data.metric("bus_factor_authors"), 0)),
        _kpi("Циклы импортов", number(data.metric("cycle_count"), 0), "в графе файлов"),
    ]
    severity = (
        f'<span class="badge" style="background:{SEVERITY_COLORS["critical"]}">критично {counts.get("critical", 0)}</span> '
        f'<span class="badge" style="background:{SEVERITY_COLORS["warning"]}">предупреждений {counts.get("warning", 0)}</span>'
        if counts
        else ""
    )
    full_ms = repo.get("full_index_ms")
    incremental_ms = repo.get("incremental_index_ms")
    phase_text = ", ".join(f"{key}: {value} мс" for key, value in timings.items()) or "нет данных"
    return f"""
<section id="summary">
  <h2>Сводка</h2>
  <div class="hero card">
    <div class="donut">{svg_donut(score)}</div>
    <div class="hero-body">
      <div class="eyebrow">Индекс здоровья</div>
      <h3>{esc(label)}</h3>
      <p>{esc(health_info.get("summary", ""))}</p>
      <div class="severity">{severity}</div>
      <div class="meta-line">Репозиторий <b>{esc(repo["name"])}</b> · ветка <code>{esc(repo.get("branch") or "-")}</code> · HEAD <code>{esc((repo.get("head_sha") or "-")[:12])}</code></div>
      <div class="meta-line">Импорт: <b>{esc(run.get("kind"))}</b> · {esc(run.get("started_at", ""))} · {number((run.get("duration_ms") or 0) / 1000, 2)} с</div>
      <div class="meta-line">Полный импорт: <b>{number((full_ms or 0) / 1000, 2)} с</b> · инкрементальный: <b>{number((incremental_ms or 0) / 1000, 2)} с</b></div>
      <div class="meta-line muted">Фазы: {esc(phase_text)}</div>
    </div>
  </div>
  <div class="grid-2">
    <div class="card">
      <h3>Вклад рисков в индекс</h3>
      {_component_bars(data)}
      <p class="muted">Чем меньше штраф, тем лучше. Сумма штрафов вычитается из 100.</p>
    </div>
    <div class="card">
      <h3>Ключевые показатели</h3>
      <div class="kpi-grid">{''.join(kpis)}</div>
    </div>
  </div>
  <div class="card">
    <h3>Параметры запуска</h3>
    <table class="table compact">
      <tr><th>Коммитов прочитано</th><td>{number(run.get("commits_seen"), 0)}</td>
          <th>Новых коммитов</th><td>{number(run.get("commits_new"), 0)}</td></tr>
      <tr><th>Файлов разобрано</th><td>{number(run.get("files_parsed"), 0)}</td>
          <th>Файлов пропущено</th><td>{number(run.get("files_skipped"), 0)}</td></tr>
      <tr><th>Срезов графа</th><td>{len(data.snapshots)}</td>
          <th>Правил в отчёте</th><td>{len(data.findings)}</td></tr>
      <tr><th>Плотность комментариев</th><td>{percent(data.metric("comment_density"))}</td>
          <th>Churn на 100 LOC</th><td>{number(data.metric("churn_density_90d"), 1)}</td></tr>
    </table>
  </div>
</section>"""


def _risks(data: ReportData) -> str:
    if not data.findings:
        body = '<p class="ok">Правила риска не сработали. Продолжайте контролировать метрики на новых срезах.</p>'
    else:
        rows = []
        for finding in data.findings:
            rows.append(
                f"""<tr>
  <td>{_severity_badge(finding["severity"])}</td>
  <td><b>{esc(finding["title"])}</b><div class="rule-id">{esc(finding["rule"])}</div></td>
  <td><code>{esc(finding["target"])}</code></td>
  <td>{esc(finding["explanation"])}</td>
  <td>{esc(finding["recommendation"])}</td>
</tr>"""
            )
        body = f"""<table class="table">
<thead><tr><th>Уровень</th><th>Риск</th><th>Цель</th><th>Почему сработало</th><th>Рекомендация</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>"""
    counts = {}
    for finding in data.findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    summary = ", ".join(f"{SEVERITY_LABELS.get(key, key)}: {value}" for key, value in sorted(counts.items()))
    return f"""
<section id="risks">
  <h2>Риски</h2>
  <p class="muted">Всего срабатываний: {len(data.findings)} ({esc(summary)}). В таблице указаны значения метрик и пороги, которые привели к срабатыванию.</p>
  <div class="card">{body}</div>
</section>"""


def _markers(data: ReportData) -> dict[str, str]:
    markers: dict[str, list[str]] = {}
    for snapshot in data.snapshots:
        week = snapshot.get("week")
        ref = snapshot.get("ref") or ""
        if week and (ref.startswith("tag:") or ref.startswith("branch:")):
            markers.setdefault(week, []).append(snapshot["label"].split(",")[0])
    return {week: ", ".join(labels[:2]) for week, labels in markers.items()}


def _dynamics(data: ReportData) -> str:
    def points(name: str) -> list[dict]:
        return [{"bucket": row["bucket"], "value": float(row["value"])} for row in data.series.get(name, [])]

    markers = _markers(data)
    anomalies = set()
    for finding in data.findings:
        if finding["rule"] == "churn_spike":
            try:
                bucket = json.loads(finding.get("value_json") or "{}").get("bucket")
            except ValueError:
                bucket = None
            if bucket:
                anomalies.add(bucket)
    churn = svg_line_chart(
        [{"name": "churn за неделю", "points": points("churn_weekly"), "color": "#0f766e"}],
        "Churn по неделям",
        markers=markers,
        anomalies=anomalies,
        y_unit="строки (добавлено + удалено)",
    )
    commits = svg_line_chart(
        [
            {"name": "коммиты", "points": points("commits_weekly"), "color": "#2563eb"},
            {"name": "багфиксы", "points": points("bugfix_weekly"), "color": "#c2410c"},
        ],
        "Активность коммитов и багфиксов",
        markers=markers,
        y_unit="коммитов за неделю",
    )
    ownership = svg_line_chart(
        [
            {"name": "доля ведущего автора", "points": points("ownership_top_share"), "color": "#7c3aed"},
            {"name": "дрейф владения", "points": points("ownership_drift"), "color": "#be123c"},
        ],
        "Владение кодом",
        markers=markers,
        y_unit="доля (0..1)",
    )
    weeks = data.series.get("churn_weekly", [])[-12:]
    rows = []
    by_week = {row["bucket"]: row for row in data.series.get("churn_volatility", [])}
    for row in weeks:
        bucket = row["bucket"]
        rows.append(
            f"<tr><td>{esc(bucket)}</td><td>{number(row['value'], 0)}</td><td>{number(next((c['value'] for c in data.series.get('commits_weekly', []) if c['bucket'] == bucket), 0), 0)}</td><td>{number(next((b['value'] for b in data.series.get('bugfix_weekly', []) if b['bucket'] == bucket), 0), 0)}</td><td>{number(by_week.get(bucket, {}).get('value', 0), 2)}</td></tr>"
        )
    table = (
        "<table class='table compact'><thead><tr><th>Неделя</th><th>Churn</th><th>Коммиты</th><th>Багфиксы</th><th>CV churn</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        if rows
        else "<p class='muted'>Недостаточно истории.</p>"
    )
    return f"""
<section id="dynamics">
  <h2>Динамика</h2>
  <p class="muted">Ряды построены по неделям от первого до HEAD-коммита. Вертикальные штрихи - релизы и ветки, красные точки - аномальные всплески.</p>
  <div class="card chart-card">{churn}</div>
  <div class="grid-2">
    <div class="card chart-card">{commits}</div>
    <div class="card chart-card">{ownership}</div>
  </div>
  <div class="card"><h3>Последние 12 недель</h3>{table}</div>
</section>"""


def _graph(data: ReportData) -> str:
    snapshot_rows = []
    for snapshot in data.snapshots:
        diff = snapshot.get("diff")
        if diff:
            diff_text = (
                f"+{diff['added_nodes']} / -{diff['removed_nodes']} узлов, "
                f"+{diff['added_edges']} / -{diff['removed_edges']} связей"
            )
        else:
            diff_text = "первый срез"
        metrics = snapshot.get("metrics", {})
        snapshot_rows.append(
            f"""<tr><td>{esc(snapshot["label"])}</td><td><code>{esc((snapshot.get("commit_sha") or "")[:10])}</code></td>
<td>{number(snapshot["nodes"], 0)}</td><td>{number(snapshot["edges"], 0)}</td>
<td>{number(metrics.get("file_edges", 0), 0)} / {number(metrics.get("entity_edges", 0), 0)}</td>
<td>{number(snapshot["cycles"], 0)}</td><td>{number(snapshot["loc"], 0)}</td><td>{esc(diff_text)}</td></tr>"""
        )
    cycles_html = (
        "<ul>" + "".join(f"<li><code>{esc(' -> '.join(cycle))}</code></li>" for cycle in data.cycles[:10]) + "</ul>"
        if data.cycles
        else "<p class='ok'>Циклов импортов не найдено.</p>"
    )

    def files_table(rows: Sequence[dict], value_title: str, value_key: str) -> str:
        if not rows:
            return "<p class='muted'>Нет данных.</p>"
        body = "".join(
            f"<tr><td><code>{esc(row['path'])}</code></td><td>{number(row[value_key], 2)}</td><td>{number(row['loc'], 0)}</td><td>{number(row['churn_90d'], 0)}</td></tr>"
            for row in rows[:8]
        )
        return (
            f"<table class='table compact'><thead><tr><th>Файл</th><th>{esc(value_title)}</th><th>LOC</th><th>Churn 90d</th></tr></thead><tbody>{body}</tbody></table>"
        )

    module_rows = "".join(
        f"<tr><td><code>{esc(row['name'])}</code></td><td>{number(row['bus_factor'], 0)}</td><td>{number(row['authors'], 0)}</td><td>{number(row['commits'], 0)}</td><td>{percent(row['top_share'])}</td><td>{number(row['coupling'], 2)}</td></tr>"
        for row in data.modules[:12]
    )
    module_table = (
        f"<table class='table compact'><thead><tr><th>Модуль</th><th>Bus factor</th><th>Авторов</th><th>Коммитов</th><th>Доля лидера</th><th>Coupling</th></tr></thead><tbody>{module_rows}</tbody></table>"
        if module_rows
        else "<p class='muted'>Нет модулей.</p>"
    )
    return f"""
<section id="graph">
  <h2>Граф зависимостей</h2>
  <div class="card">
    <h3>Версии графа</h3>
    <p class="muted">Срезы сохраняются для HEAD и релизов. Дифф считается относительно предыдущего среза.</p>
    <table class="table compact">
      <thead><tr><th>Срез</th><th>Коммит</th><th>Узлы</th><th>Связи</th><th>Файлы / сущности</th><th>Циклы</th><th>LOC</th><th>Дифф</th></tr></thead>
      <tbody>{''.join(snapshot_rows) or "<tr><td colspan='8'>Срезы ещё не сформированы</td></tr>"}</tbody>
    </table>
  </div>
  <div class="grid-2">
    <div class="card"><h3>Циклы</h3>{cycles_html}</div>
    <div class="card"><h3>Bus factor по модулям</h3>{module_table}</div>
  </div>
  <div class="grid-2">
    <div class="card"><h3>Сложные файлы</h3>{files_table(data.top_complexity, "Сложность", "value")}</div>
    <div class="card"><h3>Часто меняемые файлы</h3>{files_table(data.top_churn, "Churn 90d", "value")}</div>
  </div>
  <div class="grid-2">
    <div class="card"><h3>Давление багфиксов</h3>{files_table(data.top_fix_pressure, "FPI (45 дней)", "value")}</div>
    <div class="card"><h3>Горячие точки</h3>{files_table(data.top_hotspots, "Риск", "hotspot_score")}</div>
  </div>
</section>"""


def _recommendations(data: ReportData) -> str:
    seen: set[str] = set()
    items: list[str] = []
    priority = {"critical": 0, "warning": 1, "info": 2}
    for finding in sorted(data.findings, key=lambda item: priority.get(item["severity"], 3)):
        text = finding["recommendation"]
        if text in seen:
            continue
        seen.add(text)
        items.append(
            f"<li>{_severity_badge(finding['severity'])} <b>{esc(finding['title'])}</b> · <code>{esc(finding['target'])}</code><br>{esc(text)}</li>"
        )
    health = data.health.get("components", {}) if data.health else {}
    components = health.get("components", {}) if isinstance(health, dict) else {}
    generic: list[str] = []
    if components.get("knowledge", {}).get("penalty", 0) > 8:
        generic.append("Снизить концентрацию знаний: парное программирование, ротация ревью, документирование архитектурных решений.")
    if components.get("hotspots", {}).get("penalty", 0) > 10:
        generic.append("Запланировать рефакторинг горячих точек и добавить регрессионные тесты перед следующими изменениями.")
    if components.get("structure", {}).get("penalty", 0) > 4:
        generic.append("Разорвать циклы импортов и стабилизировать публичный API перед расширением функциональности.")
    if components.get("risks", {}).get("penalty", 0) > 20:
        generic.append("Пересмотреть пороги риска и распределить работу по снижению критичных находок на ближайшие итерации.")
    generic_html = "".join(f"<li>{esc(item)}</li>" for item in generic) or "<li>Дополнительные рекомендации не требуются.</li>"
    findings_html = "".join(items) or "<li>Критичных рекомендаций нет.</li>"
    return f"""
<section id="recommendations">
  <h2>Рекомендации</h2>
  <div class="grid-2">
    <div class="card"><h3>По найденным рискам</h3><ul class="recommendations">{findings_html}</ul></div>
    <div class="card"><h3>По компонентам здоровья</h3><ul class="recommendations">{generic_html}</ul></div>
  </div>
</section>"""


def _appendix(data: ReportData) -> str:
    thresholds = json.dumps(data.thresholds, ensure_ascii=False, indent=2, sort_keys=True)
    stats = data.run.get("stats_json") or "{}"
    try:
        stats_pretty = json.dumps(json.loads(stats), ensure_ascii=False, indent=2, sort_keys=True)
    except ValueError:
        stats_pretty = stats
    metrics = sorted({row["metric"] for row in data.metric_rows})
    metric_list = ", ".join(metrics)
    return f"""
<section id="appendix">
  <h2>Приложение: воспроизводимость</h2>
  <div class="grid-2">
    <div class="card">
      <h3>Запуск</h3>
      <pre>python -m projectpulse index --repo &lt;путь&gt; --mode full
python -m projectpulse index --repo &lt;путь&gt; --mode incremental
python -m projectpulse report --repo &lt;путь&gt; --format html --out report.html</pre>
      <p class="muted">Метрики считаются относительно даты HEAD-коммита, а не текущего времени, поэтому повторный импорт не меняет значения.</p>
      <p class="muted">Багфиксы определяются по регулярному выражению из порогов; владение считается по изменённым строкам.</p>
    </div>
    <div class="card">
      <h3>Контекст</h3>
      <table class="table compact">
        <tr><th>Версия</th><td>{esc(data.tool_version)}</td></tr>
        <tr><th>Сформирован</th><td>{esc(data.generated_at)}</td></tr>
        <tr><th>Репозиторий</th><td>{esc(data.repo.get("url") or data.repo["name"])}</td></tr>
        <tr><th>HEAD</th><td><code>{esc(data.repo.get("head_sha") or "-")}</code></td></tr>
        <tr><th>Запуск</th><td>#{esc(data.run.get("id"))} ({esc(data.run.get("kind"))})</td></tr>
        <tr><th>Метрики</th><td>{esc(metric_list)}</td></tr>
      </table>
    </div>
  </div>
  <div class="card"><h3>Пороги</h3><pre>{esc(thresholds)}</pre></div>
  <div class="card"><h3>Статистика запуска</h3><pre>{esc(stats_pretty)}</pre></div>
</section>"""


_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #f1f5f9; color: #0f172a; font: 14px/1.55 "Segoe UI", system-ui, -apple-system, sans-serif; }
.page { max-width: 1180px; margin: 0 auto; padding: 28px 24px 56px; }
header.top { display: flex; justify-content: space-between; gap: 24px; align-items: flex-end; margin-bottom: 22px; }
header.top h1 { margin: 0 0 6px; font-size: 28px; letter-spacing: -0.02em; }
header.top .sub { color: #475569; font-size: 13px; }
.repo-badge { background: #0f172a; color: #e2e8f0; border-radius: 10px; padding: 12px 16px; font-size: 12px; text-align: right; }
.repo-badge b { display: block; font-size: 15px; color: #ffffff; margin-bottom: 4px; }
h2 { font-size: 22px; margin: 34px 0 8px; letter-spacing: -0.01em; }
h3 { font-size: 15px; margin: 4px 0 12px; }
section { margin-bottom: 10px; }
.card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 18px 20px; box-shadow: 0 1px 2px rgba(15,23,42,.04); }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
.hero { display: flex; gap: 26px; align-items: center; }
.hero-body { flex: 1; }
.hero h2 { margin: 2px 0 6px; }
.eyebrow { text-transform: uppercase; letter-spacing: .12em; font-size: 11px; color: #64748b; }
.donut svg { display: block; }
.meta-line { color: #475569; font-size: 12px; margin-top: 6px; }
.muted { color: #64748b; }
.ok { color: #15803d; font-weight: 600; }
.badge { display: inline-block; color: #ffffff; border-radius: 999px; padding: 2px 9px; font-size: 11px; font-weight: 600; letter-spacing: .02em; white-space: nowrap; }
.severity { display: flex; gap: 8px; margin: 8px 0; }
.kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.kpi { border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 12px; background: #f8fafc; }
.kpi-title { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: .06em; }
.kpi-value { font-size: 19px; font-weight: 700; margin-top: 3px; }
.kpi-hint { font-size: 10px; color: #94a3b8; margin-top: 2px; }
.bar-row { margin: 10px 0; }
.bar-label { display: flex; justify-content: space-between; font-size: 12px; font-weight: 600; }
.bar-label span { color: #64748b; font-weight: 500; }
.bar-track { height: 8px; border-radius: 999px; background: #e2e8f0; margin: 5px 0 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 999px; }
.bar-detail { font-size: 11px; color: #94a3b8; }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th { text-align: left; background: #f8fafc; color: #475569; font-weight: 600; padding: 8px 9px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
.table td { padding: 8px 9px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
.table.compact td, .table.compact th { padding: 6px 8px; }
.rule-id { font-size: 10px; color: #94a3b8; font-family: Consolas, monospace; margin-top: 2px; }
code, pre { font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px; }
pre { background: #0f172a; color: #e2e8f0; padding: 12px 14px; border-radius: 10px; overflow: auto; max-height: 320px; }
.chart-card { padding: 10px 12px; }
.chart { width: 100%; height: auto; display: block; }
.recommendations { margin: 0; padding-left: 18px; }
.recommendations li { margin-bottom: 10px; }
footer { margin-top: 40px; color: #94a3b8; font-size: 11px; display: flex; justify-content: space-between; }
@media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } .kpi-grid { grid-template-columns: repeat(2, 1fr); } .hero { flex-direction: column; align-items: flex-start; } }
@media print { body { background: #fff; } .card { break-inside: avoid; box-shadow: none; } .page { max-width: none; padding: 0; } h2 { break-after: avoid; } pre { max-height: none; } }
"""

_PAGE = Template(
    """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ProjectPulse · $repo_name</title>
<style>$css</style>
</head>
<body>
<div class="page">
<header class="top">
  <div>
    <h1>ProjectPulse: отчёт о цифровом двойнике</h1>
    <div class="sub">Сводка, риски, динамика, граф и рекомендации по Git-репозиторию</div>
  </div>
  <div class="repo-badge"><b>$repo_name</b>$repo_url<br>HEAD: $head_sha</div>
</header>
$summary
$risks
$dynamics
$graph
$recommendations
$appendix
<footer><span>ProjectPulse $version</span><span>Сформирован: $generated_at</span></footer>
</div>
</body>
</html>
"""
)


def build_html(data: ReportData) -> str:
    return _PAGE.safe_substitute(
        css=_CSS,
        repo_name=esc(data.repo["name"]),
        repo_url=esc(data.repo.get("url") or ""),
        head_sha=esc((data.repo.get("head_sha") or "-")[:12]),
        summary=_summary(data),
        risks=_risks(data),
        dynamics=_dynamics(data),
        graph=_graph(data),
        recommendations=_recommendations(data),
        appendix=_appendix(data),
        version=esc(data.tool_version),
        generated_at=esc(data.generated_at),
    )
