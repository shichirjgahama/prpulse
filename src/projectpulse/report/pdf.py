"""PDF-отчёт на reportlab: те же разделы, что и в HTML, с векторными графиками."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Sequence

from projectpulse.core.events import ReportError
from projectpulse.report.builder import ReportData
from projectpulse.report.html import SEVERITY_LABELS, number, percent

try:  # pragma: no cover - проверка доступности зависимости
    from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        KeepTogether,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError as exc:  # pragma: no cover
    raise ReportError("Для PDF-отчёта установите reportlab: pip install reportlab") from exc

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 17 * mm
MARGIN_RIGHT = 15 * mm
MARGIN_TOP = 18 * mm
MARGIN_BOTTOM = 16 * mm
CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

COLOR_INK = colors.HexColor("#0f172a")
COLOR_MUTED = colors.HexColor("#64748b")
COLOR_LINE = colors.HexColor("#e2e8f0")
COLOR_ACCENT = colors.HexColor("#0f766e")
COLOR_BLUE = colors.HexColor("#2563eb")
COLOR_ORANGE = colors.HexColor("#c2410c")
COLOR_RED = colors.HexColor("#dc2626")
COLOR_YELLOW = colors.HexColor("#d97706")
COLOR_GREEN = colors.HexColor("#16a34a")
SERIES_COLORS = [COLOR_ACCENT, COLOR_BLUE, COLOR_ORANGE, colors.HexColor("#7c3aed"), colors.HexColor("#be123c")]

def _hex(color) -> str:
    value = color.hexval()
    return "#" + value[2:] if value.startswith("0x") else value


_FONT_CANDIDATES = [
    (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
    (Path("C:/Windows/Fonts/segoeui.ttf"), Path("C:/Windows/Fonts/segoeuib.ttf")),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    (Path("/System/Library/Fonts/Supplemental/Arial.ttf"), Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),
]


def _register_fonts() -> tuple[str, str]:
    """Регистрирует шрифт с кириллицей. Возвращает (regular, bold)."""
    if getattr(_register_fonts, "_done", False):
        return _register_fonts._names  # type: ignore[attr-defined]
    for regular, bold in _FONT_CANDIDATES:
        if not regular.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("PPSans", str(regular)))
            bold_name = "PPSans"
            if bold.exists():
                pdfmetrics.registerFont(TTFont("PPSans-Bold", str(bold)))
                bold_name = "PPSans-Bold"
            _register_fonts._names = ("PPSans", bold_name)  # type: ignore[attr-defined]
            _register_fonts._done = True  # type: ignore[attr-defined]
            return _register_fonts._names  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - переходим к следующему кандидату
            continue
    _register_fonts._names = ("Helvetica", "Helvetica-Bold")  # type: ignore[attr-defined]
    _register_fonts._done = True  # type: ignore[attr-defined]
    return _register_fonts._names  # type: ignore[attr-defined]


def _styles() -> dict[str, ParagraphStyle]:
    regular, bold = _register_fonts()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "PPTitle", parent=base["Title"], fontName=bold, fontSize=20, leading=24,
            textColor=COLOR_INK, alignment=TA_LEFT, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "PPSubtitle", parent=base["Normal"], fontName=regular, fontSize=9.5,
            leading=13, textColor=COLOR_MUTED, spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "PPH2", parent=base["Heading2"], fontName=bold, fontSize=15, leading=19,
            textColor=COLOR_INK, spaceBefore=14, spaceAfter=7,
        ),
        "h3": ParagraphStyle(
            "PPH3", parent=base["Heading3"], fontName=bold, fontSize=10.5, leading=14,
            textColor=COLOR_INK, spaceBefore=7, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "PPBody", parent=base["BodyText"], fontName=regular, fontSize=9, leading=12.4,
            textColor=COLOR_INK, spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "PPSmall", parent=base["BodyText"], fontName=regular, fontSize=8, leading=10.8,
            textColor=COLOR_MUTED, spaceAfter=3,
        ),
        "cell": ParagraphStyle(
            "PPCell", parent=base["BodyText"], fontName=regular, fontSize=7.6, leading=10.2,
            textColor=COLOR_INK, spaceAfter=0,
        ),
        "cell_bold": ParagraphStyle(
            "PPCellBold", parent=base["BodyText"], fontName=bold, fontSize=7.6, leading=10.2,
            textColor=COLOR_INK, spaceAfter=0,
        ),
        "cell_head": ParagraphStyle(
            "PPCellHead", parent=base["BodyText"], fontName=bold, fontSize=7.6, leading=10.2,
            textColor=colors.HexColor("#475569"), spaceAfter=0,
        ),
        "footer": ParagraphStyle(
            "PPFooter", parent=base["Normal"], fontName=regular, fontSize=7,
            textColor=COLOR_MUTED, alignment=0,
        ),
    }


def _p(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(str(text).replace("\n", "<br/>"), style)


def _table(
    rows: Sequence[Sequence[object]],
    widths: Sequence[float],
    styles: dict[str, ParagraphStyle],
    *,
    header: bool = True,
    font_size: float = 7.6,
    zebra: bool = True,
) -> Table:
    prepared: list[list[object]] = []
    for row_index, row in enumerate(rows):
        prepared_row: list[object] = []
        for cell in row:
            if isinstance(cell, (Paragraph, Table, Drawing)):
                prepared_row.append(cell)
            else:
                style = styles["cell_head"] if header and row_index == 0 else styles["cell"]
                prepared_row.append(_p(cell if cell is not None else "", style))
        prepared.append(prepared_row)
    table = Table(prepared, colWidths=list(widths), repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, COLOR_LINE),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")))
    if zebra:
        for index in range(1 if header else 0, len(prepared)):
            if (index - (1 if header else 0)) % 2 == 1:
                commands.append(("BACKGROUND", (0, index), (-1, index), colors.HexColor("#fbfdff")))
    table.setStyle(TableStyle(commands))
    return table


def _bar_drawing(penalty: float, maximum: float, width: float = 115, height: float = 8) -> Drawing:
    drawing = Drawing(width, height)
    drawing.add(Rect(0, 0, width, height, fillColor=COLOR_LINE, strokeColor=None, rx=2, ry=2))
    ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, penalty / maximum))
    color = COLOR_GREEN if ratio < 0.25 else COLOR_YELLOW if ratio < 0.6 else COLOR_RED
    if ratio > 0:
        drawing.add(Rect(0, 0, width * ratio, height, fillColor=color, strokeColor=None, rx=2, ry=2))
    return drawing


def _line_chart(
    series: Sequence[dict],
    width: float,
    height: float,
    title: str,
    unit: str = "",
    maximum_points: int = 160,
) -> Drawing:
    drawing = Drawing(width, height)
    drawing.add(Rect(0, 0, width, height, fillColor=colors.white, strokeColor=COLOR_LINE, strokeWidth=0.6))
    drawing.add(String(8, height - 14, title, fontName=_register_fonts()[1], fontSize=8.5, fillColor=COLOR_INK))
    if not series:
        drawing.add(String(8, height / 2, "Нет данных", fontName=_register_fonts()[0], fontSize=8, fillColor=COLOR_MUTED))
        return drawing

    left, right, top, bottom = 42.0, 8.0, 30.0, 22.0
    plot_w = width - left - right
    plot_h = height - top - bottom
    buckets = sorted({point["bucket"] for item in series for point in item["points"]})
    if len(buckets) > maximum_points:
        keep = max(2, maximum_points)
        indexes = {round(i * (len(buckets) - 1) / (keep - 1)) for i in range(keep)}
        buckets = [bucket for index, bucket in enumerate(buckets) if index in indexes]
    if not buckets:
        return drawing
    values_by_series: list[list[float]] = []
    maximum = 0.0
    for item in series:
        mapping = {point["bucket"]: float(point["value"]) for point in item["points"]}
        values = [mapping.get(bucket, 0.0) for bucket in buckets]
        values_by_series.append(values)
        maximum = max(maximum, max(values, default=0.0))
    maximum = maximum if maximum > 0 else 1.0
    if maximum < 10:
        maximum = 10.0

    for line_index in range(5):
        y = bottom + plot_h * line_index / 4
        drawing.add(Line(left, y, left + plot_w, y, strokeColor=COLOR_LINE, strokeWidth=0.5))
        drawing.add(
            String(
                left - 5,
                y - 2.5,
                number(maximum * line_index / 4, 0),
                fontName=_register_fonts()[0],
                fontSize=6.5,
                fillColor=COLOR_MUTED,
                textAnchor="end",
            )
        )
    step = plot_w / max(1, len(buckets) - 1)
    for series_index, values in enumerate(values_by_series):
        color = SERIES_COLORS[series_index % len(SERIES_COLORS)]
        points: list[tuple[float, float]] = []
        for index, value in enumerate(values):
            x = left + index * step
            y = bottom + plot_h * min(1.0, max(0.0, value / maximum))
            points.append((x, y))
        for index in range(len(points) - 1):
            drawing.add(Line(points[index][0], points[index][1], points[index + 1][0], points[index + 1][1], strokeColor=color, strokeWidth=1.2))
        if len(points) <= 80:
            for x, y in points:
                drawing.add(Circle(x, y, 1.4, fillColor=color, strokeColor=None))
        label = str(series[series_index].get("name", ""))[:26]
        legend_x = left + series_index * 150
        if legend_x + 120 < width:
            drawing.add(Rect(legend_x, height - 25, 7, 7, fillColor=color, strokeColor=None))
            drawing.add(String(legend_x + 10, height - 24, label, fontName=_register_fonts()[0], fontSize=6.8, fillColor=COLOR_MUTED))
    label_indexes = sorted({0, len(buckets) // 2, len(buckets) - 1})
    for index in label_indexes:
        x = left + index * step
        drawing.add(
            String(
                x,
                bottom - 11,
                buckets[index][5:],
                fontName=_register_fonts()[0],
                fontSize=6.3,
                fillColor=COLOR_MUTED,
                textAnchor="middle",
            )
        )
    if unit:
        drawing.add(String(8, 5, unit, fontName=_register_fonts()[0], fontSize=6.3, fillColor=COLOR_MUTED))
    return drawing


def _score_color(score: float):
    if score >= 80:
        return COLOR_GREEN
    if score >= 60:
        return colors.HexColor("#ca8a04")
    if score >= 40:
        return COLOR_ORANGE
    return COLOR_RED


def _summary_flowables(data: ReportData, styles: dict[str, ParagraphStyle]) -> list:
    health = data.health or {}
    inner = health.get("components", {}) if isinstance(health.get("components"), dict) else {}
    score = float(health.get("score", 0) or 0)
    label = inner.get("label", "")
    counts = inner.get("counts", {})
    components = inner.get("components", {}) if isinstance(inner.get("components"), dict) else {}
    stats = data.stats
    run = data.run
    repo = data.repo

    flow: list = [Paragraph("ProjectPulse: отчёт о цифровом двойнике", styles["title"])]
    flow.append(
        Paragraph(
            f"Репозиторий <b>{repo['name']}</b> · ветка <b>{repo.get('branch') or '-'}</b> · "
            f"HEAD <b>{(repo.get('head_sha') or '-')[:12]}</b> · сформирован {data.generated_at}",
            styles["subtitle"],
        )
    )

    flow.append(Paragraph("Сводка", styles["h2"]))
    health_table = Table(
        [
            [
                _p(f"<font size='34' color='{_hex(_score_color(score))}'><b>{score:.0f}</b></font><br/>из 100", styles["body"]),
                [
                    _p(f"<b>{label}</b>", styles["h3"]),
                    _p(inner.get("summary", ""), styles["body"]),
                    _p(
                        f"Критично: {counts.get('critical', 0)} · предупреждений: {counts.get('warning', 0)} · "
                        f"информация: {counts.get('info', 0)}",
                        styles["small"],
                    ),
                ],
            ]
        ],
        colWidths=[92, CONTENT_WIDTH - 92],
        hAlign="LEFT",
    )
    health_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.6, COLOR_LINE),
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f8fafc")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    flow.extend([health_table, Spacer(1, 7)])

    component_rows: list[list[object]] = [["Компонент", "Штраф", "Шкала", "Пояснение"]]
    for key in ("risks", "hotspots", "knowledge", "structure"):
        item = components.get(key, {})
        penalty = float(item.get("penalty", 0) or 0)
        maximum = float(item.get("max", 1) or 1)
        component_rows.append(
            [
                _p(item.get("title", key), styles["cell_bold"]),
                _p(f"{penalty:.1f} / {maximum:.0f}", styles["cell"]),
                _bar_drawing(penalty, maximum),
                _p(item.get("detail", ""), styles["cell"]),
            ]
        )
    flow.append(_p("Вклад рисков в индекс здоровья", styles["h3"]))
    flow.append(_table(component_rows, [72, 40, 120, CONTENT_WIDTH - 232], styles))
    flow.append(Spacer(1, 8))

    kpis = [
        ("LOC", number(stats.get("loc"), 0), f"SLOC {number(stats.get('sloc'), 0)}"),
        ("Коммиты", number(stats.get("commits"), 0), f"авторов {number(stats.get('authors'), 0)}"),
        ("Файлы", number(stats.get("files"), 0), f"сущностей {number(stats.get('entities'), 0)}"),
        ("Сложность", number(data.metric("avg_function_complexity"), 1), "макс. " + number(data.metric("complexity_max"), 0)),
        ("Churn 90d", number(data.metric("churn_90d"), 0), "добавлено + удалено"),
        ("Багфиксы", percent(data.metric("bugfix_share")), "доля коммитов"),
        ("Bus factor", number(data.metric("bus_factor"), 0), "авторов " + number(data.metric("bus_factor_authors"), 0)),
        ("Циклы", number(data.metric("cycle_count"), 0), "граф файлов"),
    ]
    kpi_cells = [
        [
            _p(
                f"<font color='#64748b' size='6.5'>{title.upper()}</font><br/><b>{value}</b><br/>"
                f"<font color='#94a3b8' size='6'>{hint}</font>",
                styles["body"],
            )
            for title, value, hint in kpis[index : index + 4]
        ]
        for index in range(0, len(kpis), 4)
    ]
    kpi_table = Table(kpi_cells, colWidths=[CONTENT_WIDTH / 4] * 4, hAlign="LEFT")
    kpi_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, COLOR_LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, COLOR_LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    flow.append(kpi_table)

    phases = {}
    try:
        phases = json.loads(run.get("stats_json") or "{}").get("phase_ms", {})
    except ValueError:
        phases = {}
    phase_text = ", ".join(f"{key}: {value} мс" for key, value in phases.items()) or "нет данных"
    run_text = (
        f"Импорт: <b>{run.get('kind')}</b> от {run.get('started_at', '')}, длительность "
        f"{number((run.get('duration_ms') or 0) / 1000, 2)} с. "
        f"Полный импорт: {number((repo.get('full_index_ms') or 0) / 1000, 2)} с, "
        f"инкрементальный: {number((repo.get('incremental_index_ms') or 0) / 1000, 2)} с. "
        f"Фазы: {phase_text}."
    )
    flow.append(Spacer(1, 8))
    flow.append(_p(run_text, styles["small"]))
    return flow


def _risk_flowables(data: ReportData, styles: dict[str, ParagraphStyle]) -> list:
    flow: list = [Paragraph("Риски", styles["h2"])]
    if not data.findings:
        flow.append(_p("Правила риска не сработали.", styles["body"]))
        return flow
    counts: dict[str, int] = {}
    for finding in data.findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    flow.append(
        _p(
            f"Всего срабатываний: {len(data.findings)}. "
            + ", ".join(f"{SEVERITY_LABELS.get(key, key)}: {value}" for key, value in sorted(counts.items())),
            styles["small"],
        )
    )
    rows: list[list[object]] = [["Уровень", "Риск", "Цель", "Почему сработало", "Рекомендация"]]
    severity_color = {"critical": COLOR_RED, "warning": COLOR_YELLOW, "info": COLOR_BLUE}
    for finding in data.findings[:60]:
        color = _hex(severity_color.get(finding["severity"], COLOR_MUTED))
        rows.append(
            [
                _p(f"<font color='{color}'><b>{SEVERITY_LABELS.get(finding['severity'], finding['severity'])}</b></font>", styles["cell"]),
                _p(f"<b>{finding['title']}</b><br/><font size='6' color='#94a3b8'>{finding['rule']}</font>", styles["cell"]),
                _p(finding["target"], styles["cell"]),
                _p(finding["explanation"], styles["cell"]),
                _p(finding["recommendation"], styles["cell"]),
            ]
        )
    widths = [44, 92, 80, CONTENT_WIDTH - 44 - 92 - 80 - 120, 120]
    flow.append(_table(rows, widths, styles))
    if len(data.findings) > 60:
        flow.append(_p(f"В PDF показаны первые 60 из {len(data.findings)} срабатываний. Полный список есть в HTML-отчёте.", styles["small"]))
    return flow


def _series_points(data: ReportData, name: str) -> list[dict]:
    return [{"bucket": row["bucket"], "value": float(row["value"])} for row in data.series.get(name, [])]


def _dynamics_flowables(data: ReportData, styles: dict[str, ParagraphStyle]) -> list:
    flow: list = [Paragraph("Динамика", styles["h2"])]
    flow.append(_p("Недельные ряды от первого коммита до HEAD. Значения не зависят от даты запуска.", styles["small"]))
    flow.append(
        _line_chart(
            [{"name": "churn за неделю", "points": _series_points(data, "churn_weekly")}],
            CONTENT_WIDTH,
            148,
            "Churn по неделям",
            "строки: добавлено + удалено",
        )
    )
    flow.append(Spacer(1, 5))
    flow.append(
        _line_chart(
            [
                {"name": "коммиты", "points": _series_points(data, "commits_weekly")},
                {"name": "багфиксы", "points": _series_points(data, "bugfix_weekly")},
            ],
            CONTENT_WIDTH,
            148,
            "Активность коммитов и багфиксов",
            "коммитов за неделю",
        )
    )
    flow.append(Spacer(1, 5))
    flow.append(
        _line_chart(
            [
                {"name": "доля ведущего автора", "points": _series_points(data, "ownership_top_share")},
                {"name": "дрейф владения", "points": _series_points(data, "ownership_drift")},
            ],
            CONTENT_WIDTH,
            148,
            "Владение кодом",
            "доля 0..1",
        )
    )
    weeks = data.series.get("churn_weekly", [])[-12:]
    if weeks:
        churn = {row["bucket"]: float(row["value"]) for row in data.series.get("churn_weekly", [])}
        commits = {row["bucket"]: float(row["value"]) for row in data.series.get("commits_weekly", [])}
        bugfix = {row["bucket"]: float(row["value"]) for row in data.series.get("bugfix_weekly", [])}
        volatility = {row["bucket"]: float(row["value"]) for row in data.series.get("churn_volatility", [])}
        rows: list[list[object]] = [["Неделя", "Churn", "Коммиты", "Багфиксы", "CV churn"]]
        for row in reversed(weeks):
            bucket = row["bucket"]
            rows.append(
                [
                    bucket,
                    number(churn.get(bucket, 0), 0),
                    number(commits.get(bucket, 0), 0),
                    number(bugfix.get(bucket, 0), 0),
                    number(volatility.get(bucket, 0), 2),
                ]
            )
        flow.append(Spacer(1, 5))
        flow.append(_table(rows, [70, 105, 100, 100, CONTENT_WIDTH - 375], styles))
    return flow


def _graph_flowables(data: ReportData, styles: dict[str, ParagraphStyle]) -> list:
    flow: list = [Paragraph("Граф зависимостей", styles["h2"])]
    flow.append(
        _p(
            "Срезы сохраняются для HEAD и релизов. Дифф считается относительно предыдущего среза. "
            "Проекции: файлы и сущности.",
            styles["small"],
        )
    )
    rows: list[list[object]] = [["Срез", "Коммит", "Узлы", "Связи", "Циклы", "LOC"]]
    for snapshot in data.snapshots:
        rows.append(
            [
                snapshot["label"],
                (snapshot.get("commit_sha") or "")[:10],
                number(snapshot["nodes"], 0),
                number(snapshot["edges"], 0),
                number(snapshot["cycles"], 0),
                number(snapshot["loc"], 0),
            ]
        )
    if len(rows) == 1:
        flow.append(_p("Срезы ещё не сформированы.", styles["small"]))
    else:
        flow.append(_table(rows, [120, 65, 45, 45, 40, CONTENT_WIDTH - 315], styles))

    cycles_text = (
        "; ".join(" -> ".join(cycle) for cycle in data.cycles[:6]) if data.cycles else "Циклов импортов не найдено."
    )
    flow.append(_p("Циклы", styles["h3"]))
    flow.append(_p(cycles_text, styles["small"]))

    flow.append(_p("Bus factor по модулям", styles["h3"]))
    module_rows: list[list[object]] = [["Модуль", "Bus factor", "Авторов", "Коммитов", "Доля лидера"]]
    for module in data.modules[:12]:
        module_rows.append(
            [
                module["name"],
                number(module["bus_factor"], 0),
                number(module["authors"], 0),
                number(module["commits"], 0),
                percent(module["top_share"]),
            ]
        )
    flow.append(_table(module_rows, [150, 55, 50, 55, CONTENT_WIDTH - 310], styles) if len(module_rows) > 1 else _p("Нет данных.", styles["small"]))

    flow.append(_p("Горячие точки", styles["h3"]))
    hotspot_rows: list[list[object]] = [["Файл", "Риск", "Сложность", "Churn 90d", "LOC"]]
    for row in data.top_hotspots[:10]:
        hotspot_rows.append(
            [
                row["path"],
                number(row.get("hotspot_score", 0), 1),
                number(row["complexity_max"], 0),
                number(row["churn_90d"], 0),
                number(row["loc"], 0),
            ]
        )
    flow.append(_table(hotspot_rows, [CONTENT_WIDTH - 230, 55, 55, 60, 60], styles) if len(hotspot_rows) > 1 else _p("Нет данных.", styles["small"]))
    return flow


def _recommendation_flowables(data: ReportData, styles: dict[str, ParagraphStyle]) -> list:
    flow: list = [Paragraph("Рекомендации", styles["h2"])]
    seen: set[str] = set()
    items: list[str] = []
    priority = {"critical": 0, "warning": 1, "info": 2}
    for finding in sorted(data.findings, key=lambda item: priority.get(item["severity"], 3)):
        text = finding["recommendation"]
        if text in seen:
            continue
        seen.add(text)
        items.append(f"<b>{finding['title']}</b> ({finding['target']}): {text}")
    inner = data.health.get("components", {}) if data.health else {}
    components = inner.get("components", {}) if isinstance(inner, dict) else {}
    generic: list[str] = []
    if components.get("knowledge", {}).get("penalty", 0) > 8:
        generic.append("Снизить концентрацию знаний: парное программирование, ротация ревью, документирование решений.")
    if components.get("hotspots", {}).get("penalty", 0) > 10:
        generic.append("Запланировать рефакторинг горячих точек и регрессионные тесты перед следующими изменениями.")
    if components.get("structure", {}).get("penalty", 0) > 4:
        generic.append("Разорвать циклы импортов и стабилизировать публичный API.")
    if components.get("risks", {}).get("penalty", 0) > 20:
        generic.append("Распределить снижение критичных находок на ближайшие итерации и пересмотреть пороги.")
    if not items:
        items.append("Критичных рекомендаций нет: сохраняйте текущий контроль метрик.")
    for index, item in enumerate(items[:16], start=1):
        flow.append(_p(f"{index}. {item}", styles["body"]))
    if len(items) > 16:
        flow.append(_p(f"Ещё {len(items) - 16} рекомендаций в HTML-отчёте.", styles["small"]))
    flow.append(_p("По компонентам здоровья", styles["h3"]))
    for item in generic or ["Дополнительные рекомендации не требуются."]:
        flow.append(_p(f"- {item}", styles["body"]))
    return flow


def _appendix_flowables(data: ReportData, styles: dict[str, ParagraphStyle]) -> list:
    flow: list = [Paragraph("Приложение: воспроизводимость", styles["h2"])]
    thresholds = json.dumps(data.thresholds, ensure_ascii=False, indent=2, sort_keys=True)
    flow.append(_p("Пороги", styles["h3"]))
    flow.append(_p(thresholds.replace(" ", "&nbsp;"), styles["small"]))
    flow.append(_p("Запуск", styles["h3"]))
    flow.append(
        _p(
            "python -m projectpulse index --repo &lt;путь&gt; --mode full<br/>"
            "python -m projectpulse index --repo &lt;путь&gt; --mode incremental<br/>"
            "python -m projectpulse report --repo &lt;путь&gt; --format pdf --out report.pdf",
            styles["small"],
        )
    )
    flow.append(
        _p(
            f"Версия {data.tool_version}. Метрики считаются относительно HEAD-коммита. "
            "Багфиксы определяются регулярным выражением, владение - по изменённым строкам.",
            styles["small"],
        )
    )
    return flow


class _ReportDocument(BaseDocTemplate):
    def __init__(self, buffer: io.BytesIO, data: ReportData, **kwargs) -> None:
        super().__init__(buffer, **kwargs)
        self.report_data = data
        self.styles_map = _styles()
        frame = Frame(
            MARGIN_LEFT,
            MARGIN_BOTTOM,
            CONTENT_WIDTH,
            PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM,
            id="body",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(
            [PageTemplate(id="report", frames=[frame], onPage=self._decorate)]
        )

    def _decorate(self, canvas, doc) -> None:
        canvas.saveState()
        regular, bold = _register_fonts()
        canvas.setFont(regular, 7.2)
        canvas.setFillColor(COLOR_MUTED)
        canvas.drawString(MARGIN_LEFT, PAGE_HEIGHT - 10 * mm, "ProjectPulse · отчёт о цифровом двойнике")
        canvas.drawRightString(PAGE_WIDTH - MARGIN_RIGHT, PAGE_HEIGHT - 10 * mm, self.report_data.repo["name"])
        canvas.setStrokeColor(COLOR_LINE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_LEFT, PAGE_HEIGHT - 12 * mm, PAGE_WIDTH - MARGIN_RIGHT, PAGE_HEIGHT - 12 * mm)
        canvas.line(MARGIN_LEFT, 11 * mm, PAGE_WIDTH - MARGIN_RIGHT, 11 * mm)
        canvas.setFont(regular, 7)
        canvas.drawString(MARGIN_LEFT, 7 * mm, f"Версия {self.report_data.tool_version} · {self.report_data.generated_at}")
        canvas.drawRightString(PAGE_WIDTH - MARGIN_RIGHT, 7 * mm, f"Страница {doc.page}")
        canvas.restoreState()


def build_pdf(data: ReportData) -> bytes:
    """Собирает PDF и возвращает байты."""
    styles = _styles()
    buffer = io.BytesIO()
    document = _ReportDocument(
        buffer,
        data,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"ProjectPulse: {data.repo['name']}",
        author="ProjectPulse",
        subject="Отчёт о цифровом двойнике программного проекта",
    )
    story: list = []
    story.extend(_summary_flowables(data, styles))
    story.extend(_risk_flowables(data, styles))
    story.extend(_dynamics_flowables(data, styles))
    story.extend(_graph_flowables(data, styles))
    story.extend(_recommendation_flowables(data, styles))
    story.extend(_appendix_flowables(data, styles))
    document.build(story)
    return buffer.getvalue()


def write_pdf(data: ReportData, path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_pdf(data))
    return target
