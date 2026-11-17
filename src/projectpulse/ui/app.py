"""Главное окно ProjectPulse и фоновые задачи."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from projectpulse import __version__
from projectpulse.core.events import CancelToken, IndexCancelled, Progress
from projectpulse.core.runtime import Runtime
from projectpulse.ui import theme
from projectpulse.ui.views import (
    CompareView,
    DashboardView,
    GraphView,
    LogView,
    ProjectsView,
    ReportView,
    TimelineView,
)

NAV_ITEMS = [
    ("projects", "Проекты"),
    ("dashboard", "Дашборд"),
    ("timeline", "Динамика"),
    ("graph", "Граф"),
    ("compare", "Сравнение"),
    ("report", "Отчёт"),
    ("log", "Журнал"),
]


class TaskManager:
    def __init__(self, app: "ProjectPulseApp") -> None:
        self.app = app
        self.queue: queue.Queue = queue.Queue()
        self.token: CancelToken | None = None
        self.busy = False
        self.label = ""
        self._on_done = None

    def start(self, label: str, target, on_done=None) -> bool:
        if self.busy:
            messagebox.showinfo("Задача выполняется", "Дождитесь завершения текущей операции.", parent=self.app)
            return False
        self.busy = True
        self.label = label
        self._on_done = on_done
        self.token = CancelToken()
        self.app.set_busy(True)
        self.app.set_status(f"{label}...")

        def progress(event: Progress) -> None:
            self.queue.put(("progress", event))

        def worker() -> None:
            try:
                result = target(self.token, progress)
            except Exception as exc:  # noqa: BLE001 - ошибка уходит в UI
                self.queue.put(("error", exc))
            else:
                self.queue.put(("done", result))

        threading.Thread(target=worker, daemon=True, name="projectpulse-task").start()
        self.app.after(80, self._poll)
        return True

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    self.app.update_progress(payload)
                elif kind == "done":
                    self.busy = False
                    self.app.set_busy(False)
                    self.app.set_status(f"{self.label}: готово")
                    callback = self._on_done
                    self._on_done = None
                    if callback:
                        try:
                            callback(payload)
                        except Exception as exc:  # noqa: BLE001
                            messagebox.showerror("Ошибка интерфейса", str(exc), parent=self.app)
                elif kind == "error":
                    self.busy = False
                    self.app.set_busy(False)
                    if isinstance(payload, IndexCancelled):
                        self.app.set_status(f"{self.label}: отменено")
                    else:
                        self.app.set_status(f"{self.label}: ошибка")
                        messagebox.showerror(
                            "Операция не выполнена",
                            f"{type(payload).__name__}: {payload}",
                            parent=self.app,
                        )
        except queue.Empty:
            pass
        if self.busy:
            self.app.after(80, self._poll)

    def cancel(self) -> None:
        if self.token and self.busy:
            self.token.cancel()
            self.app.set_status(f"{self.label}: запрошена отмена")


class ProjectPulseApp(tk.Tk):
    def __init__(self, runtime: Runtime) -> None:
        super().__init__()
        self.runtime = runtime
        self.store = runtime.store
        self.active_repo_id: int | None = None
        self.views: dict[str, object] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        self.current_view = ""
        self._closing = False
        self.tasks = TaskManager(self)

        self.title("ProjectPulse - цифровой двойник проекта")
        self.geometry("1340x860")
        self.minsize(1120, 720)
        self.configure(background=theme.BG)
        theme.apply_theme(self)
        self.option_add("*tearOff", False)
        self._layout()
        self._create_views()
        repos = self.store.list_repos()
        if repos:
            self.active_repo_id = int(repos[0]["id"])
        self.show_view("projects")
        self.set_status("Готово к работе")
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------------ layout
    def _layout(self) -> None:
        self.grid_columnconfigure(0, minsize=214)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = tk.Frame(self, background=theme.NAV_BG, width=214)
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        sidebar.grid_propagate(False)
        logo = tk.Frame(sidebar, background=theme.NAV_BG)
        logo.pack(fill="x", padx=18, pady=(22, 18))
        tk.Label(
            logo, text="ProjectPulse", background=theme.NAV_BG, foreground="#ffffff",
            font=theme.ui_font(15, "bold"), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            logo, text="цифровой двойник проекта", background=theme.NAV_BG, foreground="#7c8ba1",
            font=theme.ui_font(8), anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        tk.Frame(sidebar, background="#1e293b", height=1).pack(fill="x", padx=14, pady=(0, 10))
        nav = tk.Frame(sidebar, background=theme.NAV_BG)
        nav.pack(fill="x", padx=10)
        for key, label in NAV_ITEMS:
            button = tk.Button(
                nav, text=label, anchor="w", padx=14, pady=9, relief="flat", borderwidth=0,
                background=theme.NAV_BG, foreground=theme.NAV_TEXT, activebackground=theme.NAV_ACTIVE,
                activeforeground="#ffffff", font=theme.ui_font(10), cursor="hand2",
                command=lambda name=key: self.show_view(name),
            )
            button.pack(fill="x", pady=1)
            self.nav_buttons[key] = button
        spacer = tk.Frame(sidebar, background=theme.NAV_BG)
        spacer.pack(fill="both", expand=True)
        bottom = tk.Frame(sidebar, background=theme.NAV_BG)
        bottom.pack(fill="x", padx=18, pady=16)
        tk.Label(
            bottom, text=f"версия {__version__}", background=theme.NAV_BG, foreground="#64748b",
            font=theme.ui_font(7), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            bottom, text="локальная работа · SQLite + Git", background=theme.NAV_BG, foreground="#64748b",
            font=theme.ui_font(7), anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        self.content = tk.Frame(self, background=theme.BG)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        status = tk.Frame(self, background=theme.SURFACE_ALT, height=28)
        status.grid(row=1, column=1, sticky="ew")
        status.grid_propagate(False)
        self.status_label = tk.Label(
            status, text="", background=theme.SURFACE_ALT, foreground=theme.MUTED,
            font=theme.ui_font(8), anchor="w",
        )
        self.status_label.pack(side="left", padx=12)
        self.cancel_button = ttk.Button(status, text="Отмена", width=8, command=self.cancel_task)
        self.cancel_button.pack(side="right", padx=8, pady=3)
        self.cancel_button.state(["disabled"])
        self.progress = ttk.Progressbar(status, mode="determinate", maximum=100, length=210)
        self.progress.pack(side="right", padx=6, pady=5)

    def _create_views(self) -> None:
        factories = {
            "projects": ProjectsView,
            "dashboard": DashboardView,
            "timeline": TimelineView,
            "graph": GraphView,
            "compare": CompareView,
            "report": ReportView,
            "log": LogView,
        }
        for key, factory in factories.items():
            view = factory(self.content, self)
            view.grid(row=0, column=0, sticky="nsew")
            view.grid_remove()
            self.views[key] = view

    # --------------------------------------------------------------- navigation
    def show_view(self, key: str) -> None:
        if key not in self.views:
            return
        if self.current_view and self.current_view in self.views:
            self.views[self.current_view].grid_remove()
        self.current_view = key
        view = self.views[key]
        view.grid()
        view.tkraise()
        for name, button in self.nav_buttons.items():
            active = name == key
            button.configure(
                background=theme.NAV_ACTIVE if active else theme.NAV_BG,
                foreground="#ffffff" if active else theme.NAV_TEXT,
                font=theme.ui_font(10, "bold" if active else "normal"),
            )
        view.on_show()

    def set_active_repo(self, repo_id: int | None) -> None:
        self.active_repo_id = repo_id
        if self.current_view in {"dashboard", "timeline", "graph", "report"}:
            self.views[self.current_view].on_show()

    def notify_data_changed(self) -> None:
        view = self.views.get(self.current_view)
        if view is not None:
            try:
                view.refresh()
            except Exception:  # noqa: BLE001 - интерфейс не должен падать из-за обновления
                pass

    # ------------------------------------------------------------------- tasks
    def start_background(self, label: str, target, on_done=None) -> bool:
        return self.tasks.start(label, target, on_done)

    def cancel_task(self) -> None:
        self.tasks.cancel()

    def index_repo(self, repo_id: int, mode: str, on_done=None) -> None:
        repo = self.store.get_repo(repo_id)
        name = repo["name"] if repo else str(repo_id)
        label = f"Индексация {name} ({mode})"

        def target(token, progress):
            return self.runtime.indexer.index(repo_id, mode=mode, progress=progress, cancel=token)

        def done(result):
            if on_done:
                on_done()
            self.set_status(f"{result.summary()}")

        self.start_background(label, target, done)

    # ------------------------------------------------------------------ status
    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text[:180])

    def update_progress(self, event: Progress) -> None:
        if event.total > 0:
            self.progress.configure(value=max(0.0, min(100.0, event.fraction * 100)))
            self.status_label.configure(
                text=f"{event.phase}: {event.message} ({event.current}/{event.total})"[:180]
            )
        else:
            self.progress.configure(value=0)
            self.status_label.configure(text=f"{event.phase}: {event.message}"[:180])

    def set_busy(self, busy: bool) -> None:
        if busy:
            self.cancel_button.state(["!disabled"])
            self.progress.configure(value=0)
        else:
            self.cancel_button.state(["disabled"])
            self.progress.configure(value=0)

    def _close(self) -> None:
        if self.tasks.busy:
            if not messagebox.askyesno(
                "Задача выполняется",
                "Операция ещё выполняется. Отменить и закрыть приложение?",
                parent=self,
            ):
                return
            self.tasks.cancel()
        self._closing = True
        self.destroy()


def run_gui(runtime: Runtime) -> int:
    # DPI awareness намеренно не включается: Windows масштабирует окно целиком,
    # поэтому пиксельные размеры Tkinter не расходятся с размером шрифтов.
    app = ProjectPulseApp(runtime)
    app.mainloop()
    return 0
