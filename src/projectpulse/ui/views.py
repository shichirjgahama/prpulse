"""Экраны Tkinter: проекты, дашборд, динамика, граф, сравнение, отчёт, журнал."""

from __future__ import annotations

import json
import os
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from projectpulse.analysis.compare import compare_repos
from projectpulse.analysis.research import run_research
from projectpulse.core.events import read_log_tail
from projectpulse.core.utils import format_duration_ms, week_key
from projectpulse.report.service import generate_report, write_research
from projectpulse.ui import theme
from projectpulse.ui.widgets import (
    BarRow,
    EmptyState,
    EgoGraph,
    HealthGauge,
    KpiCard,
    ScrollableFrame,
    TimelineChart,
    clear_tree,
    treeview_with_scroll,
)

SEVERITY_LABELS = {"critical": "Критично", "warning": "Предупреждение", "info": "Информация"}


def fmt_number(value: float | int | None, digits: int = 0) -> str:
    if value is None:
        return "-"
    formatted = f"{float(value):,.{digits}f}".replace(",", " ")
    if digits <= 0:
        formatted = formatted.split(".")[0]
    return formatted


def fmt_percent(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.{digits}f}%"


def json_load(value: str | None, default):
    try:
        return json.loads(value or "")
    except (ValueError, TypeError):
        return default


class BaseView(ttk.Frame):
    title = ""
    subtitle = ""

    def __init__(self, master, app) -> None:
        super().__init__(master, style="TFrame")
        self.app = app
        self.runtime = app.runtime
        self.store = app.runtime.store
        self._repo_map: dict[str, int] = {}
        self._repo_combo: ttk.Combobox | None = None

    # ------------------------------------------------------------------ head
    def header(self, toolbar: bool = True) -> tk.Frame:
        frame = tk.Frame(self, background=theme.BG)
        frame.pack(fill="x", padx=18, pady=(14, 8))
        tk.Label(
            frame, text=self.title, background=theme.BG, foreground=theme.INK,
            font=theme.ui_font(20, "bold"), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            frame, text=self.subtitle, background=theme.BG, foreground=theme.MUTED,
            font=theme.ui_font(9), anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        controls = tk.Frame(frame, background=theme.BG)
        controls.pack(fill="x", pady=(8, 0))
        return controls if toolbar else frame

    def repo_combo(self, parent, on_change: Callable | None = None, width: int = 32) -> ttk.Combobox:
        self._repo_combo = ttk.Combobox(parent, state="readonly", width=width, font=theme.ui_font(9))
        self._repo_combo.bind("<<ComboboxSelected>>", lambda _event: self._repo_selected(on_change))
        return self._repo_combo

    def fill_repos(self) -> None:
        repos = self.store.list_repos()
        self._repo_map = {f"{repo['name']} (#{repo['id']})": int(repo["id"]) for repo in repos}
        if self._repo_combo is not None:
            values = list(self._repo_map)
            self._repo_combo.configure(values=values)
            current = self.app.active_repo_id
            label = next((label for label, repo_id in self._repo_map.items() if repo_id == current), None)
            if label is None and values:
                label = values[0]
                self.app.active_repo_id = self._repo_map[label]
            self._repo_combo.set(label or "")

    def _repo_selected(self, on_change: Callable | None) -> None:
        if self._repo_combo is None:
            return
        repo_id = self._repo_map.get(self._repo_combo.get())
        if repo_id is not None:
            self.app.active_repo_id = repo_id
            if on_change:
                on_change()

    def selected_repo_id(self) -> int | None:
        if self._repo_combo is not None and self._repo_combo.get() in self._repo_map:
            return self._repo_map[self._repo_combo.get()]
        return self.app.active_repo_id

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:  # pragma: no cover - переопределяется
        pass


class ProjectsView(BaseView):
    title = "Проекты"
    subtitle = "Локальные Git-репозитории, режимы импорта и состояние цифрового двойника"

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        controls = self.header()
        ttk.Button(controls, text="Добавить", command=self._add).pack(side="left", padx=3)
        ttk.Button(controls, text="Клон", command=self._clone).pack(side="left", padx=3)
        ttk.Button(controls, text="Инкремент", style="Accent.TButton", command=lambda: self._index("incremental")).pack(side="left", padx=3)
        ttk.Button(controls, text="Полный", command=lambda: self._index("full")).pack(side="left", padx=3)
        ttk.Button(controls, text="Пересборка", command=lambda: self._index("rebuild")).pack(side="left", padx=3)

        body = tk.Frame(self, background=theme.BG)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        card = tk.Frame(body, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True)
        inner = tk.Frame(card, background=theme.SURFACE)
        inner.pack(fill="both", expand=True, padx=12, pady=12)
        columns = [
            ("id", "ID", 40),
            ("name", "Имя", 155),
            ("branch", "Ветка", 80),
            ("head", "HEAD", 95),
            ("commits", "Коммиты", 80),
            ("files", "Файлы", 60),
            ("health", "Балл", 55),
            ("indexed", "Обновлён", 125),
            ("path", "Путь", 240),
        ]
        container, self.tree = treeview_with_scroll(inner, columns, height=14)
        container.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._show_details())
        self.tree.bind("<Double-1>", lambda _event: self._open_dashboard())
        self.tree.tag_configure("critical", foreground=theme.RED)
        self.tree.tag_configure("warning", foreground=theme.YELLOW)
        self.details = tk.Label(
            inner, text="Выберите репозиторий. Двойной щелчок открывает дашборд.",
            background=theme.SURFACE, foreground=theme.MUTED, font=theme.ui_font(8),
            anchor="w", justify="left", wraplength=1000,
        )
        self.details.pack(fill="x", pady=(8, 0))

    def refresh(self) -> None:
        clear_tree(self.tree)
        repos = self.store.list_repos()
        for repo in repos:
            score = ""
            tag = ""
            health = self.store.latest_health(int(repo["id"]))
            if health:
                value = float(health.get("score", 0))
                score = f"{value:.0f}"
                tag = "warning" if value < 60 else ""
            self.tree.insert(
                "",
                "end",
                iid=str(repo["id"]),
                values=(
                    repo["id"],
                    repo["name"],
                    repo.get("branch") or "-",
                    (repo.get("head_sha") or "-")[:10],
                    repo.get("commits_total", 0),
                    repo.get("files_total", 0),
                    score,
                    (repo.get("last_indexed_at") or "-")[:19].replace("T", " "),
                    repo["path"],
                ),
                tags=(tag,) if tag else (),
            )
        if self.app.active_repo_id and self.tree.exists(str(self.app.active_repo_id)):
            self.tree.selection_set(str(self.app.active_repo_id))
        self._show_details()

    def _selected_id(self) -> int | None:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def _show_details(self) -> None:
        repo_id = self._selected_id()
        if not repo_id:
            self.details.configure(text="Выберите репозиторий. Двойной щелчок открывает дашборд.")
            return
        repo = self.store.get_repo(repo_id)
        if not repo:
            return
        run = self.store.latest_run(repo_id)
        parts = [
            f"Путь: {repo['path']}",
            f"URL: {repo.get('url') or '-'}",
            f"Полный импорт: {format_duration_ms(repo.get('full_index_ms'))}, "
            f"инкрементальный: {format_duration_ms(repo.get('incremental_index_ms'))}",
        ]
        if run:
            parts.append(
                f"Последний запуск: #{run['id']} ({run['kind']}, {run['status']}) "
                f"{format_duration_ms(run.get('duration_ms'))}, "
                f"коммитов {run.get('commits_new', 0)}, файлов {run.get('files_parsed', 0)}"
            )
        else:
            parts.append("Импорт ещё не выполнялся.")
        self.details.configure(text="   |   ".join(parts))

    def _open_dashboard(self) -> None:
        repo_id = self._selected_id()
        if repo_id is not None:
            self.app.set_active_repo(repo_id)
            self.app.show_view("dashboard")

    def _add(self) -> None:
        path = filedialog.askdirectory(title="Каталог Git-репозитория")
        if not path:
            return
        try:
            repo = self.runtime.indexer.add_repository(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Не удалось добавить", str(exc), parent=self)
            return
        self.app.set_active_repo(int(repo["id"]))
        self.refresh()
        self.app.set_status(f"Добавлен репозиторий {repo['name']}")

    def _clone(self) -> None:
        url = simpledialog.askstring("Клонирование", "URL Git-репозитория:", parent=self)
        if not url:
            return
        default_name = url.rstrip("/").split("/")[-1].removesuffix(".git") or "repo"
        name = simpledialog.askstring("Клонирование", "Имя проекта:", initialvalue=default_name, parent=self)
        if not name:
            return
        target = self.runtime.config.paths.cache_dir / name

        def task(_token, _progress):
            if target.exists() and any(target.iterdir()):
                return self.runtime.indexer.add_repository(target, name=name, url=url)
            self.runtime.git.clone(url, target)
            return self.runtime.indexer.add_repository(target, name=name, url=url)

        def done(repo):
            self.app.set_active_repo(int(repo["id"]))
            self.refresh()
            self.app.set_status(f"Репозиторий склонирован: {target}")

        self.app.start_background("Клонирование репозитория", task, done)

    def _index(self, mode: str) -> None:
        repo_id = self._selected_id() or self.app.active_repo_id
        if not repo_id:
            messagebox.showinfo("Нет репозитория", "Сначала добавьте репозиторий.", parent=self)
            return
        repo = self.store.get_repo(repo_id)
        if not repo:
            return
        self.app.index_repo(repo_id, mode, on_done=self.refresh)

    def _delete(self) -> None:  # pragma: no cover - не выведено в интерфейс, оставлено для API
        repo_id = self._selected_id()
        if not repo_id:
            return
        if not messagebox.askyesno("Удалить", "Удалить репозиторий из базы? Файлы на диске останутся.", parent=self):
            return
        self.store.delete_repo(repo_id)
        self.refresh()


class DashboardView(BaseView):
    title = "Дашборд"
    subtitle = "Индекс здоровья, ключевые показатели и критичные находки"

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        controls = self.header()
        self.repo_combo(controls, on_change=self.refresh, width=34).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Обновить", command=self.refresh).pack(side="left", padx=3)
        ttk.Button(controls, text="Отчёт", style="Accent.TButton", command=lambda: self.app.show_view("report")).pack(side="left", padx=3)
        self.scroll = ScrollableFrame(self, background=theme.BG)
        self.scroll.pack(fill="both", expand=True, padx=14, pady=(0, 12))

    def on_show(self) -> None:
        self.fill_repos()
        self.refresh()

    def refresh(self) -> None:
        self.fill_repos()
        for child in self.scroll.inner.winfo_children():
            child.destroy()
        repo_id = self.selected_repo_id()
        if not repo_id:
            EmptyState(
                self.scroll.inner, "Нет проектов",
                "Добавьте локальный Git-репозиторий на вкладке «Проекты» и запустите импорт.",
            ).pack(fill="both", expand=True, pady=40)
            return
        repo = self.store.get_repo(repo_id)
        run = self.store.latest_run(repo_id)
        if not repo or not run:
            EmptyState(
                self.scroll.inner, "Импорт не выполнен",
                f"Для проекта {repo['name'] if repo else repo_id} запустите инкрементальный или полный импорт "
                "на вкладке «Проекты».",
            ).pack(fill="both", expand=True, pady=40)
            return

        health = self.store.get_health(int(run["id"])) or {"score": 0.0, "components": {}}
        inner = health.get("components", {}) if isinstance(health.get("components"), dict) else {}
        score = float(health.get("score", 0) or 0)
        label = inner.get("label", "")
        components = inner.get("components", {}) if isinstance(inner.get("components"), dict) else {}
        counts = inner.get("counts", {})
        metrics = self.store.metric_map(int(run["id"]))
        stats = self.store.stats(repo_id)
        findings = self.store.get_findings(int(run["id"]))

        def metric(name: str, default: float = 0.0) -> float:
            return float(metrics.get(("project", "project", name), default))

        top = tk.Frame(self.scroll.inner, background=theme.BG)
        top.pack(fill="x", pady=(4, 8))
        health_card = tk.Frame(top, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        health_card.pack(side="left", fill="both", padx=(4, 8), ipadx=8, ipady=8)
        gauge = HealthGauge(health_card, size=170)
        gauge.pack(side="left", padx=4, pady=4)
        gauge.set(score, label)
        summary = tk.Frame(health_card, background=theme.SURFACE)
        summary.pack(side="left", fill="both", expand=True, padx=14, pady=6)
        tk.Label(
            summary, text=inner.get("summary", "Нет расчёта здоровья"), background=theme.SURFACE,
            foreground=theme.INK, font=theme.ui_font(9), wraplength=370, justify="left", anchor="w",
        ).pack(anchor="w", pady=(4, 8))
        badges = tk.Frame(summary, background=theme.SURFACE)
        badges.pack(anchor="w", pady=(0, 8))
        for severity in ("critical", "warning", "info"):
            value = counts.get(severity, 0)
            tk.Label(
                badges, text=f"{SEVERITY_LABELS[severity]}: {value}", background=theme.SEVERITY[severity],
                foreground="#ffffff", font=theme.ui_font(8, "bold"), padx=9, pady=3,
            ).pack(side="left", padx=(0, 6))
        tk.Label(
            summary,
            text=f"HEAD {(repo.get('head_sha') or '-')[:12]} · {repo.get('branch') or '-'} · "
            f"запуск #{run['id']} ({run['kind']}) · {format_duration_ms(run.get('duration_ms'))}",
            background=theme.SURFACE, foreground=theme.MUTED, font=theme.ui_font(8), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            summary,
            text=f"Полный импорт: {format_duration_ms(repo.get('full_index_ms'))} · "
            f"инкрементальный: {format_duration_ms(repo.get('incremental_index_ms'))}",
            background=theme.SURFACE, foreground=theme.MUTED, font=theme.ui_font(8), anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        side = tk.Frame(top, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        side.pack(side="left", fill="both", expand=True, padx=(8, 4))
        tk.Label(
            side, text="Вклад компонентов", background=theme.SURFACE, foreground=theme.INK,
            font=theme.ui_font(11, "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 6))
        order = ("risks", "hotspots", "knowledge", "structure")
        for key in order:
            item = components.get(key, {})
            row = BarRow(side, item.get("title", key))
            row.pack(fill="x", padx=14, pady=3)
            row.set(float(item.get("penalty", 0) or 0), float(item.get("max", 1) or 1), item.get("detail", ""))
        tk.Label(
            side, text="Сумма штрафов вычитается из 100. Чем ниже штрих, тем лучше.",
            background=theme.SURFACE, foreground=theme.MUTED, font=theme.ui_font(7), anchor="w",
        ).pack(fill="x", padx=14, pady=(4, 10))

        kpi_grid = tk.Frame(self.scroll.inner, background=theme.BG)
        kpi_grid.pack(fill="x", pady=8)
        values = [
            ("LOC", fmt_number(stats.get("loc"), 0), f"SLOC {fmt_number(stats.get('sloc'), 0)}"),
            ("Коммиты", fmt_number(stats.get("commits"), 0), f"авторов {fmt_number(stats.get('authors'), 0)}"),
            ("Файлы", fmt_number(stats.get("files"), 0), f"сущностей {fmt_number(stats.get('entities'), 0)}"),
            ("Сложность", fmt_number(metric("avg_function_complexity"), 1), "макс. " + fmt_number(metric("complexity_max"), 0)),
            ("Churn 90d", fmt_number(metric("churn_90d"), 0), "добавлено + удалено"),
            ("Багфиксы", fmt_percent(metric("bugfix_share")), "доля коммитов"),
            ("Bus factor", fmt_number(metric("bus_factor"), 0), "авторов " + fmt_number(metric("bus_factor_authors"), 0)),
            ("Циклы", fmt_number(metric("cycle_count"), 0), "в графе файлов"),
        ]
        for index, (title, value, hint) in enumerate(values):
            card = KpiCard(kpi_grid, title, value, hint)
            card.grid(row=index // 4, column=index % 4, sticky="nsew", padx=4, pady=4)
        for column in range(4):
            kpi_grid.columnconfigure(column, weight=1)

        lower = tk.Frame(self.scroll.inner, background=theme.BG)
        lower.pack(fill="both", expand=True, pady=8)
        findings_card = tk.Frame(lower, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        findings_card.pack(side="left", fill="both", expand=True, padx=(4, 8))
        tk.Label(
            findings_card, text="Находки правил", background=theme.SURFACE, foreground=theme.INK,
            font=theme.ui_font(11, "bold"), anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 4))
        columns = [("severity", "Уровень", 90), ("title", "Риск", 230), ("target", "Цель", 260)]
        container, tree = treeview_with_scroll(findings_card, columns, height=9)
        container.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tree.tag_configure("critical", foreground=theme.RED)
        tree.tag_configure("warning", foreground=theme.YELLOW)
        for finding in findings[:80]:
            tree.insert(
                "", "end",
                values=(SEVERITY_LABELS.get(finding["severity"], finding["severity"]), finding["title"], finding["target"]),
                tags=(finding["severity"],),
            )
        if not findings:
            tree.insert("", "end", values=("", "Правила риска не сработали", ""))

        metrics_card = tk.Frame(lower, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        metrics_card.pack(side="left", fill="both", expand=True, padx=(8, 4))
        tk.Label(
            metrics_card, text="Проектные метрики", background=theme.SURFACE, foreground=theme.INK,
            font=theme.ui_font(11, "bold"), anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 4))
        metric_rows = [
            ("Плотность churn", fmt_number(metric("churn_density_90d"), 1), "на 100 LOC"),
            ("Плотность комментариев", fmt_percent(metric("comment_density")), "comments / (SLOC + comments)"),
            ("Средняя доля лидера", fmt_percent(metric("avg_file_top_share")), "по файлам"),
            ("Дрейф владения", fmt_percent(metric("ownership_drift")), "между окнами"),
            ("Нестабильных API", fmt_number(metric("api_volatile_files"), 0), "файлов"),
            ("Давление багфиксов", fmt_percent(metric("fix_pressure_recent")), "последние 45 дней"),
            ("Coupling pressure", fmt_number(metric("coupling_pressure_avg"), 2), "связи на 1000 LOC"),
            ("Скачков churn", fmt_number(metric("churn_spike_count"), 0), "z >= 2.5"),
        ]
        rows_frame = tk.Frame(metrics_card, background=theme.SURFACE)
        rows_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        for index, (name, value, hint) in enumerate(metric_rows):
            tk.Label(
                rows_frame, text=name, background=theme.SURFACE, foreground=theme.MUTED,
                font=theme.ui_font(8), anchor="w",
            ).grid(row=index, column=0, sticky="w", pady=3)
            tk.Label(
                rows_frame, text=value, background=theme.SURFACE, foreground=theme.INK,
                font=theme.ui_font(9, "bold"), anchor="e",
            ).grid(row=index, column=1, sticky="e", padx=(10, 0))
            tk.Label(
                rows_frame, text=hint, background=theme.SURFACE, foreground="#94a3b8",
                font=theme.ui_font(7), anchor="w",
            ).grid(row=index, column=2, sticky="w", padx=(8, 0))
        rows_frame.columnconfigure(2, weight=1)


class TimelineView(BaseView):
    title = "Динамика"
    subtitle = "Недельные ряды, релизы, аномалии и навигация по временной шкале"

    GROUPS = [
        ("Churn и активность", ["churn_weekly"]),
        ("Коммиты и багфиксы", ["commits_weekly", "bugfix_weekly"]),
        ("Волатильность churn", ["churn_volatility"]),
        ("Владение кодом", ["ownership_top_share", "ownership_drift"]),
    ]

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        controls = self.header()
        self.repo_combo(controls, on_change=self.refresh, width=30).pack(side="left", padx=(0, 6))
        self.group = ttk.Combobox(controls, state="readonly", values=[name for name, _ in self.GROUPS], width=24)
        self.group.current(0)
        self.group.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        self.group.pack(side="left", padx=6)
        ttk.Button(controls, text="Обновить", command=self.refresh).pack(side="left", padx=3)

        body = tk.Frame(self, background=theme.BG)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        chart_card = tk.Frame(body, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        chart_card.pack(fill="both", expand=True)
        self.chart = TimelineChart(chart_card, height=300, on_select=self._bucket_selected)
        self.chart.pack(fill="both", expand=True, padx=12, pady=9)
        self.detail = tk.Label(
            chart_card, text="Выберите точку на графике, чтобы увидеть значения недели.",
            background=theme.SURFACE, foreground=theme.MUTED, font=theme.ui_font(8), anchor="w",
        )
        self.detail.pack(fill="x", padx=14, pady=(0, 8))

        table_card = tk.Frame(body, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        table_card.pack(fill="both", expand=True, pady=(10, 0))
        tk.Label(
            table_card, text="Последние недели", background=theme.SURFACE, foreground=theme.INK,
            font=theme.ui_font(10, "bold"), anchor="w",
        ).pack(fill="x", padx=12, pady=(8, 2))
        columns = [
            ("week", "Неделя", 100), ("commits", "Коммиты", 90), ("bugfix", "Багфиксы", 90),
            ("churn", "Churn", 100), ("cv", "CV", 80), ("top", "Доля лидера", 110), ("drift", "Дрейф", 90),
        ]
        container, self.table = treeview_with_scroll(table_card, columns, height=7)
        container.pack(fill="both", expand=True, padx=10, pady=(0, 9))
        self._series: dict[str, list[dict]] = {}
        self._markers: dict[str, str] = {}
        self._anomalies: set[str] = set()

    def on_show(self) -> None:
        self.fill_repos()
        self.refresh()

    def refresh(self) -> None:
        self.fill_repos()
        repo_id = self.selected_repo_id()
        self._series = {}
        self._markers = {}
        self._anomalies = set()
        if not repo_id:
            self.chart.set_data([])
            clear_tree(self.table)
            return
        run = self.store.latest_run(repo_id)
        if not run:
            self.chart.set_data([])
            clear_tree(self.table)
            return
        for row in self.store.get_series(repo_id):
            self._series.setdefault(row["metric"], []).append(row)
        commits = {row["sha"]: int(row["ts"]) for row in self.store.get_commits(repo_id)}
        for snapshot in self.store.list_snapshots(repo_id):
            ref = snapshot.get("ref") or ""
            sha = snapshot.get("commit_sha")
            if not sha or sha not in commits:
                continue
            if not (ref.startswith("tag:") or ref.startswith("branch:")):
                continue
            label = snapshot["label"].split(",")[0]
            self._markers.setdefault(week_key(commits[sha]), label[:18])
        for finding in self.store.get_findings(int(run["id"])):
            if finding["rule"] == "churn_spike":
                value = json_load(finding.get("value_json"), {})
                if value.get("bucket"):
                    self._anomalies.add(value["bucket"])
        names = self.GROUPS[self.group.current()][1]
        series = []
        for index, name in enumerate(names):
            points = [{"bucket": row["bucket"], "value": float(row["value"])} for row in self._series.get(name, [])]
            series.append({"name": self._label(name), "points": points, "color": theme.SERIES_COLORS[index]})
        y_unit = {
            "churn_weekly": "строки: добавлено + удалено",
            "commits_weekly": "коммитов за неделю",
            "bugfix_weekly": "багфиксов за неделю",
            "churn_volatility": "коэффициент вариации",
            "ownership_top_share": "доля 0..1",
            "ownership_drift": "доля 0..1",
        }.get(names[0], "")
        self.chart.set_data(series, self._markers, self._anomalies, y_unit)
        self._fill_table()

    @staticmethod
    def _label(name: str) -> str:
        return {
            "churn_weekly": "churn за неделю",
            "commits_weekly": "коммиты",
            "bugfix_weekly": "багфиксы",
            "churn_volatility": "волатильность churn",
            "ownership_top_share": "доля ведущего автора",
            "ownership_drift": "дрейф владения",
        }.get(name, name)

    def _fill_table(self) -> None:
        clear_tree(self.table)
        buckets = [row["bucket"] for row in self._series.get("churn_weekly", [])]
        for bucket in reversed(buckets[-20:]):
            def value(name: str, digits: int = 0) -> str:
                row = next((item for item in self._series.get(name, []) if item["bucket"] == bucket), None)
                return fmt_number(row["value"], digits) if row else "-"

            self.table.insert(
                "", "end",
                values=(
                    bucket,
                    value("commits_weekly"),
                    value("bugfix_weekly"),
                    value("churn_weekly"),
                    value("churn_volatility", 2),
                    fmt_percent(float(next((item["value"] for item in self._series.get("ownership_top_share", []) if item["bucket"] == bucket), 0.0))),
                    fmt_percent(float(next((item["value"] for item in self._series.get("ownership_drift", []) if item["bucket"] == bucket), 0.0))),
                ),
            )

    def _bucket_selected(self, bucket: str) -> None:
        parts = [bucket]
        for name in ("commits_weekly", "bugfix_weekly", "churn_weekly", "churn_volatility", "ownership_top_share", "ownership_drift"):
            row = next((item for item in self._series.get(name, []) if item["bucket"] == bucket), None)
            if row:
                digits = 2 if name in {"churn_volatility", "ownership_top_share", "ownership_drift"} else 0
                parts.append(f"{self._label(name)}: {fmt_number(row['value'], digits)}")
        self.detail.configure(text="   |   ".join(parts), foreground=theme.INK)


class GraphView(BaseView):
    title = "Граф"
    subtitle = "Две проекции зависимостей, версии срезов и навигация по связям"

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        controls = self.header()
        self.repo_combo(controls, on_change=self._repo_changed, width=24).pack(side="left", padx=(0, 5))
        self.snapshot_combo = ttk.Combobox(controls, state="readonly", width=34)
        self.snapshot_combo.bind("<<ComboboxSelected>>", lambda _event: self._load_snapshot())
        self.snapshot_combo.pack(side="left", padx=5)
        self.projection = ttk.Combobox(controls, state="readonly", width=14, values=["Файлы", "Сущности"])
        self.projection.current(0)
        self.projection.bind("<<ComboboxSelected>>", lambda _event: self._load_snapshot())
        self.projection.pack(side="left", padx=5)
        self.search = ttk.Entry(controls, width=24)
        self.search.pack(side="left", padx=(8, 3))
        self.search.bind("<Return>", lambda _event: self._fill_nodes())
        ttk.Button(controls, text="Найти", command=self._fill_nodes).pack(side="left")
        ttk.Button(controls, text="Обновить", command=self.refresh).pack(side="left", padx=3)

        body = tk.Frame(self, background=theme.BG)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        paned = ttk.Panedwindow(body, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = tk.Frame(paned, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        right = tk.Frame(paned, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        paned.add(left, weight=2)
        paned.add(right, weight=3)
        tk.Label(
            left, text="Узлы среза", background=theme.SURFACE, foreground=theme.INK,
            font=theme.ui_font(10, "bold"), anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 2))
        self.node_info = tk.Label(
            left, text="", background=theme.SURFACE, foreground=theme.MUTED, font=theme.ui_font(7), anchor="w"
        )
        self.node_info.pack(fill="x", padx=10, pady=(0, 4))
        columns = [("name", "Узел", 250), ("kind", "Тип", 66), ("loc", "LOC", 50)]
        container, self.tree = treeview_with_scroll(left, columns, height=18)
        container.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._node_selected())
        self.tree.bind("<Double-1>", lambda _event: self._node_selected())

        self.graph = EgoGraph(right, on_node_click=self._set_center)
        self.graph.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        self.details = tk.Label(
            right, text="", background=theme.SURFACE, foreground=theme.MUTED, font=theme.ui_font(8),
            anchor="w", justify="left", wraplength=660,
        )
        self.details.pack(fill="x", padx=12, pady=(0, 8))

        self._snapshots: list[dict] = []
        self._nodes: list[dict] = []
        self._edges: list[dict] = []
        self._by_id: dict[str, dict] = {}
        self._degrees: dict[str, int] = {}
        self._center = ""

    def on_show(self) -> None:
        self.fill_repos()
        self.refresh()

    def _repo_changed(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.fill_repos()
        repo_id = self.selected_repo_id()
        self._snapshots = self.store.list_snapshots(repo_id) if repo_id else []
        self.snapshot_combo.configure(values=[self._snapshot_label(row) for row in self._snapshots])
        if self._snapshots:
            head = next((row for row in reversed(self._snapshots) if row.get("ref") == "HEAD"), self._snapshots[-1])
            self.snapshot_combo.set(self._snapshot_label(head))
            self._load_snapshot()
        else:
            self.snapshot_combo.set("")
            self._nodes = []
            self._edges = []
            self._by_id = {}
            self._center = ""
            clear_tree(self.tree)
            self.node_info.configure(text="Срезов нет")
            self.graph.set_graph([], [], "")
            self.details.configure(text="Срезы появятся после импорта репозитория.")

    @staticmethod
    def _snapshot_label(row: dict) -> str:
        created = (row.get("created_at") or "")[:10]
        sha = (row.get("commit_sha") or "")[:8]
        return f"{row['label'][:36]} · {sha} · {created}"

    def _load_snapshot(self) -> None:
        label = self.snapshot_combo.get()
        row = next((item for item in self._snapshots if self._snapshot_label(item) == label), None)
        if not row:
            return
        nodes = self.store.get_snapshot_nodes(int(row["id"]))
        edges = self.store.get_snapshot_edges(int(row["id"]))
        if self.projection.current() == 0:
            nodes = [node for node in nodes if node.get("kind") == "file"]
            node_ids = {node["node_id"] for node in nodes}
            edges = [edge for edge in edges if edge.get("kind") == "import" and edge["src"] in node_ids and edge["dst"] in node_ids]
        else:
            nodes = [node for node in nodes if node.get("kind") in {"module", "class", "function"}]
            node_ids = {node["node_id"] for node in nodes}
            edges = [edge for edge in edges if edge.get("kind") in {"call", "inherit", "compose"} and edge["src"] in node_ids and edge["dst"] in node_ids]
        self._nodes = nodes
        self._edges = edges
        self._by_id = {node["node_id"]: node for node in nodes}
        self._degrees = {node_id: 0 for node_id in self._by_id}
        for edge in edges:
            self._degrees[edge["src"]] = self._degrees.get(edge["src"], 0) + 1
            self._degrees[edge["dst"]] = self._degrees.get(edge["dst"], 0) + 1
        metrics = json_load(row.get("metrics_json"), {})
        self.node_info.configure(
            text=f"узлов {len(nodes)}, связей {len(edges)}, циклов {row.get('cycles_count', 0)}, "
            f"файлов {metrics.get('files', 0)}, сущностей {metrics.get('entities', 0)}"
        )
        self._center = ""
        self._fill_nodes()
        self._auto_center()

    def _fill_nodes(self) -> None:
        clear_tree(self.tree)
        query = self.search.get().strip().lower()
        rows = [
            node for node in self._nodes
            if not query or query in str(node.get("name", "")).lower() or query in str(node.get("path", "")).lower()
        ]
        rows.sort(key=lambda node: (-self._degrees.get(node["node_id"], 0), node.get("name", ""), node["node_id"]))
        for node in rows[:800]:
            label = str(node.get("name") or node["node_id"])
            if node.get("kind") == "file" and len(label) > 32:
                parts = label.replace("\\", "/").split("/")
                label = ".../" + "/".join(parts[-2:])
            if len(label) > 36:
                label = label[:33] + "..."
            self.tree.insert(
                "", "end", iid=node["node_id"],
                values=(label, node.get("kind", ""), node.get("loc", 0)),
            )
        if rows and not self._center:
            self.tree.selection_set(rows[0]["node_id"])

    def _auto_center(self) -> None:
        if not self._nodes:
            self.graph.set_graph([], [], "")
            self.details.configure(text="В этом срезе нет узлов выбранной проекции.")
            return
        if self._center not in self._by_id:
            node_id = self.tree.selection()[0] if self.tree.selection() else None
            if not node_id:
                node_id = sorted(
                    self._nodes, key=lambda node: (-self._degrees.get(node["node_id"], 0), node["node_id"])
                )[0]["node_id"]
            self._center = node_id
        self.graph.set_graph(self._nodes, self._edges, self._center)
        self._update_details()

    def _node_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        self._center = selection[0]
        self.graph.set_graph(self._nodes, self._edges, self._center)
        self._update_details()

    def _set_center(self, node_id: str) -> None:
        if node_id not in self._by_id:
            return
        self._center = node_id
        if self.tree.exists(node_id):
            self.tree.selection_set(node_id)
            self.tree.see(node_id)
        self.graph.set_graph(self._nodes, self._edges, node_id)
        self._update_details()

    def _update_details(self) -> None:
        node = self._by_id.get(self._center)
        if not node:
            return
        fan_in = sum(1 for edge in self._edges if edge["dst"] == self._center)
        fan_out = sum(1 for edge in self._edges if edge["src"] == self._center)
        self.details.configure(
            text=f"{node.get('kind', '').upper()} · {node.get('name', '')} · путь: {node.get('path') or '-'} · "
            f"LOC {node.get('loc', 0)} · сложность {node.get('complexity', 0)} · "
            f"входящих {fan_in} · исходящих {fan_out}. Щелчок по соседу перецентрирует схему."
        )


class CompareView(BaseView):
    title = "Сравнение"
    subtitle = "Два репозитория по индексу здоровья и пяти ключевым показателям"

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        controls = self.header()
        self.combo_a = ttk.Combobox(controls, state="readonly", width=26)
        self.combo_b = ttk.Combobox(controls, state="readonly", width=26)
        self.combo_a.pack(side="left", padx=(0, 5))
        self.combo_b.pack(side="left", padx=5)
        ttk.Button(controls, text="Сравнить", style="Accent.TButton", command=self._compare).pack(side="left", padx=6)
        ttk.Button(controls, text="Исследование", command=self._research).pack(side="left", padx=3)
        self.scroll = ScrollableFrame(self, background=theme.BG)
        self.scroll.pack(fill="both", expand=True, padx=14, pady=(0, 12))

    def on_show(self) -> None:
        self._fill_combos()
        self._render_empty()

    def _fill_combos(self) -> None:
        repos = self.store.list_repos()
        self._repo_map = {f"{repo['name']} (#{repo['id']})": int(repo["id"]) for repo in repos}
        values = list(self._repo_map)
        self.combo_a.configure(values=values)
        self.combo_b.configure(values=values)
        if values:
            if self.combo_a.get() not in values:
                self.combo_a.set(values[0])
            if self.combo_b.get() not in values:
                self.combo_b.set(values[1] if len(values) > 1 else values[0])

    def _render_empty(self) -> None:
        for child in self.scroll.inner.winfo_children():
            child.destroy()
        EmptyState(
            self.scroll.inner, "Выберите два проекта",
            "Оба репозитория должны быть проиндексированы. Сравнение показывает индекс здоровья, "
            "сложность, churn, долю багфиксов и bus factor.",
        ).pack(fill="both", expand=True, pady=60)

    def _compare(self) -> None:
        repo_a_id = self._repo_map.get(self.combo_a.get())
        repo_b_id = self._repo_map.get(self.combo_b.get())
        if not repo_a_id or not repo_b_id:
            messagebox.showinfo("Сравнение", "Выберите два репозитория.", parent=self)
            return
        if repo_a_id == repo_b_id:
            messagebox.showinfo("Сравнение", "Выберите разные репозитории.", parent=self)
            return
        repo_a = self.store.get_repo(repo_a_id)
        repo_b = self.store.get_repo(repo_b_id)
        try:
            result = compare_repos(self.store, repo_a, repo_b)
        except ValueError as exc:
            messagebox.showwarning("Сравнение", str(exc), parent=self)
            return
        for child in self.scroll.inner.winfo_children():
            child.destroy()
        top = tk.Frame(self.scroll.inner, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        top.pack(fill="x", padx=4, pady=(4, 8))
        tk.Label(
            top, text=result["verdict"], background=theme.SURFACE, foreground=theme.INK,
            font=theme.ui_font(12, "bold"), anchor="w", wraplength=900, justify="left",
        ).pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(
            top,
            text=f"Побед: {repo_a['name']} - {result['wins_a']}, {repo_b['name']} - {result['wins_b']}. "
            "Стрелка показывает, у кого лучше значение с учётом направления показателя.",
            background=theme.SURFACE, foreground=theme.MUTED, font=theme.ui_font(8), anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 12))

        card = tk.Frame(self.scroll.inner, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=4, pady=4)
        columns = [("indicator", "Показатель", 320), ("a", repo_a["name"], 140), ("b", repo_b["name"], 140), ("better", "Лучше", 140)]
        container, tree = treeview_with_scroll(card, columns, height=8)
        container.pack(fill="x", padx=12, pady=12)
        tree.tag_configure("a", background="#ecfdf5", foreground=theme.INK)
        tree.tag_configure("b", background="#eff6ff", foreground=theme.INK)
        for row in result["indicators"]:
            value_a = f"{row['a']:.2f}" + (" %" if row["key"] == "bugfix" else "")
            value_b = f"{row['b']:.2f}" + (" %" if row["key"] == "bugfix" else "")
            better = {"a": repo_a["name"], "b": repo_b["name"], "tie": "равно"}[row["better"]]
            tree.insert(
                "", "end",
                values=(f"{row['title']} ({row['unit']})", value_a, value_b, better),
                tags=(row["better"],) if row["better"] in {"a", "b"} else (),
            )
        tk.Label(
            card, text="HTML и PDF отчёты по каждому проекту доступны на вкладке «Отчёт».",
            background=theme.SURFACE, foreground=theme.MUTED, font=theme.ui_font(8), anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 10))

    def _research(self) -> None:
        repo_a_id = self._repo_map.get(self.combo_a.get())
        repo_b_id = self._repo_map.get(self.combo_b.get())
        if not repo_a_id or not repo_b_id or repo_a_id == repo_b_id:
            messagebox.showinfo("Исследование", "Выберите два разных репозитория.", parent=self)
            return
        repo_a = self.store.get_repo(repo_a_id)
        repo_b = self.store.get_repo(repo_b_id)
        if not self.store.latest_run(repo_a_id) or not self.store.latest_run(repo_b_id):
            messagebox.showwarning("Исследование", "Оба репозитория должны быть проиндексированы.", parent=self)
            return

        def task(_token, _progress):
            result = run_research(self.store, repo_a, repo_b)
            markdown, json_path = write_research(result, self.runtime.config)
            return result, markdown, json_path

        def done(payload):
            result, markdown, json_path = payload
            messagebox.showinfo(
                "Исследование готово",
                f"Гипотеза: {result['hypothesis']}\n\nMarkdown: {markdown}\nJSON: {json_path}",
                parent=self,
            )
            try:
                os.startfile(str(markdown))  # type: ignore[attr-defined]
            except OSError:
                pass

        self.app.start_background("Мини-исследование", task, done)


class ReportView(BaseView):
    title = "Отчёт"
    subtitle = "Автономный HTML и PDF с разделами «Сводка / Риски / Динамика / Граф / Рекомендации»"

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        controls = self.header()
        self.repo_combo(controls, on_change=self.refresh, width=32).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Открыть каталог", command=self._open_folder).pack(side="left", padx=3)
        ttk.Button(controls, text="Обновить", command=self.refresh).pack(side="left", padx=3)

        body = tk.Frame(self, background=theme.BG)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        form = tk.Frame(body, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        form.pack(fill="x")
        tk.Label(
            form, text="Параметры отчёта", background=theme.SURFACE, foreground=theme.INK,
            font=theme.ui_font(11, "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 4))
        row = tk.Frame(form, background=theme.SURFACE)
        row.pack(fill="x", padx=14, pady=6)
        self.var_html = tk.BooleanVar(value=True)
        self.var_pdf = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="HTML", variable=self.var_html).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(row, text="PDF", variable=self.var_pdf).pack(side="left", padx=(0, 18))
        tk.Label(row, text="Каталог:", background=theme.SURFACE, foreground=theme.MUTED, font=theme.ui_font(9)).pack(side="left")
        self.out_dir = ttk.Entry(row, width=62)
        self.out_dir.pack(side="left", padx=6)
        self.out_dir.insert(0, str(self.runtime.config.paths.reports_dir))
        ttk.Button(row, text="Выбрать", command=self._browse).pack(side="left", padx=3)
        ttk.Button(row, text="Сформировать", style="Accent.TButton", command=self._generate).pack(side="left", padx=(12, 3))
        self.status = tk.Label(
            form, text="Отчёт строится по последнему успешному импорту.", background=theme.SURFACE,
            foreground=theme.MUTED, font=theme.ui_font(8), anchor="w",
        )
        self.status.pack(fill="x", padx=14, pady=(0, 10))

        result_card = tk.Frame(body, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        result_card.pack(fill="both", expand=True, pady=(10, 0))
        tk.Label(
            result_card, text="Сформированные файлы", background=theme.SURFACE, foreground=theme.INK,
            font=theme.ui_font(11, "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 4))
        self.paths: dict[str, str] = {}
        self.files = tk.Listbox(
            result_card, background=theme.SURFACE, foreground=theme.INK, font=theme.mono_font(9),
            borderwidth=0, highlightthickness=0, activestyle="none", height=7,
        )
        self.files.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        actions = tk.Frame(result_card, background=theme.SURFACE)
        actions.pack(fill="x", padx=14, pady=(0, 10))
        ttk.Button(actions, text="Открыть HTML", command=lambda: self._open("html")).pack(side="left", padx=3)
        ttk.Button(actions, text="Открыть PDF", command=lambda: self._open("pdf")).pack(side="left", padx=3)
        ttk.Button(actions, text="Открыть каталог", command=self._open_folder).pack(side="left", padx=3)

    def on_show(self) -> None:
        self.fill_repos()
        self.refresh()

    def refresh(self) -> None:
        self.fill_repos()
        self.paths = {}
        self.files.delete(0, "end")
        if self.selected_repo_id():
            run = self.store.latest_run(int(self.selected_repo_id()))
            if run:
                self.status.configure(
                    text=f"Последний импорт: #{run['id']} ({run['kind']}), {run['started_at']}, "
                    f"файлов {run.get('files_parsed', 0)}, длительность {format_duration_ms(run.get('duration_ms'))}."
                )
            else:
                self.status.configure(text="Для выбранного проекта ещё не было успешного импорта.")

    def _browse(self) -> None:
        directory = filedialog.askdirectory(title="Каталог для отчётов", parent=self)
        if directory:
            self.out_dir.delete(0, "end")
            self.out_dir.insert(0, directory)

    def _generate(self) -> None:
        repo_id = self.selected_repo_id()
        if not repo_id:
            messagebox.showinfo("Отчёт", "Сначала добавьте и проиндексируйте репозиторий.", parent=self)
            return
        formats = [name for name, var in (("html", self.var_html), ("pdf", self.var_pdf)) if var.get()]
        if not formats:
            messagebox.showinfo("Отчёт", "Выберите хотя бы один формат.", parent=self)
            return
        out = self.out_dir.get().strip() or None
        self.status.configure(text="Формирование отчёта...")

        def task(_token, _progress):
            return generate_report(self.store, self.runtime.config, repo_id, formats=formats, out=out)

        def done(written):
            self.paths = written
            self.files.delete(0, "end")
            for fmt, path in written.items():
                self.files.insert("end", f"{fmt.upper()}: {path}")
            self.status.configure(text=f"Готово: {len(written)} файл(а).")
            self.app.set_status("Отчёт сформирован")

        self.app.start_background("Формирование отчёта", task, done)

    def _open(self, fmt: str) -> None:
        path = self.paths.get(fmt)
        if not path:
            return
        try:
            if fmt == "html":
                webbrowser.open(Path(path).as_uri())
            else:
                os.startfile(path)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Не удалось открыть", str(exc), parent=self)

    def _open_folder(self) -> None:
        base = self.paths.get("html") or self.paths.get("pdf") or self.out_dir.get()
        folder = Path(base).parent if Path(base).suffix else Path(base)
        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Не удалось открыть", str(exc), parent=self)


class LogView(BaseView):
    title = "Журнал"
    subtitle = "Диагностика индексации, ошибки git и сообщения плагинов"

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        controls = self.header()
        ttk.Button(controls, text="Обновить", command=self.refresh).pack(side="left", padx=3)
        ttk.Button(controls, text="Открыть файл", command=self._open_file).pack(side="left", padx=3)
        body = tk.Frame(self, background=theme.BG)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        card = tk.Frame(body, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True)
        self.path_label = tk.Label(
            card, text=str(self.runtime.config.paths.log_path), background=theme.SURFACE,
            foreground=theme.MUTED, font=theme.ui_font(8), anchor="w",
        )
        self.path_label.pack(fill="x", padx=12, pady=(8, 4))
        frame = tk.Frame(card, background=theme.SURFACE)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.text = tk.Text(
            frame, background="#0b1220", foreground="#dbeafe", insertbackground="#ffffff",
            font=theme.mono_font(8), borderwidth=0, wrap="none",
        )
        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        scroll_x = ttk.Scrollbar(frame, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        content = read_log_tail(self.runtime.config.paths.log_path, lines=600)
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content or "Журнал пуст. Выполните импорт или отчёт.")
        self.text.configure(state="disabled")
        self.text.see("end")

    def _open_file(self) -> None:
        try:
            os.startfile(str(self.runtime.config.paths.log_path))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Не удалось открыть", str(exc), parent=self)
