"""Переиспользуемые виджеты: карточки, графики, шкала здоровья, граф."""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Callable, Sequence

from projectpulse.ui import theme


class ScrollableFrame(tk.Frame):
    def __init__(self, master, background: str = theme.BG, **kwargs) -> None:
        super().__init__(master, background=background, **kwargs)
        self.canvas = tk.Canvas(self, background=background, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, background=background)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._sync)
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _sync(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _bind_wheel(self, _event=None) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _event=None) -> None:
        self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class KpiCard(tk.Frame):
    def __init__(self, master, title: str, value: str = "-", hint: str = "") -> None:
        super().__init__(master, background=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        self.title = tk.Label(
            self, text=title.upper(), background=theme.SURFACE, foreground=theme.MUTED,
            font=theme.ui_font(7, "bold"), anchor="w",
        )
        self.value = tk.Label(
            self, text=value, background=theme.SURFACE, foreground=theme.INK,
            font=theme.ui_font(18, "bold"), anchor="w",
        )
        self.hint = tk.Label(
            self, text=hint, background=theme.SURFACE, foreground="#94a3b8",
            font=theme.ui_font(7), anchor="w",
        )
        self.title.pack(fill="x", padx=10, pady=(8, 0))
        self.value.pack(fill="x", padx=10)
        self.hint.pack(fill="x", padx=10, pady=(0, 8))

    def set(self, value: str, hint: str | None = None) -> None:
        self.value.configure(text=value)
        if hint is not None:
            self.hint.configure(text=hint)


class HealthGauge(tk.Canvas):
    def __init__(self, master, size: int = 180, **kwargs) -> None:
        super().__init__(
            master, width=size, height=size + 26, background=theme.SURFACE,
            highlightthickness=0, **kwargs,
        )
        self.size = size
        self.score = 0.0
        self.label = ""
        self.bind("<Configure>", lambda _event: self.redraw())

    def set(self, score: float, label: str = "") -> None:
        self.score = max(0.0, min(100.0, float(score)))
        self.label = label
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width() or self.size
        height = self.winfo_height() or (self.size + 26)
        diameter = max(90, min(width, height - 26))
        pad = 16
        left = (width - diameter) / 2 + pad
        top = pad
        box = (left, top, left + diameter - 2 * pad, top + diameter - 2 * pad)
        color = (
            theme.GREEN if self.score >= 80 else "#ca8a04" if self.score >= 60
            else theme.ORANGE if self.score >= 40 else theme.RED
        )
        self.create_arc(*box, start=0, extent=359.9, style="arc", outline=theme.BORDER, width=15)
        if self.score > 0:
            self.create_arc(
                *box, start=90, extent=-359.9 * self.score / 100.0, style="arc",
                outline=color, width=15,
            )
        center_x, center_y = width / 2, top + (diameter - 2 * pad) / 2
        self.create_text(
            center_x, center_y - 4, text=f"{self.score:.0f}", fill=theme.INK,
            font=theme.ui_font(max(20, diameter // 7), "bold"),
        )
        self.create_text(
            center_x, center_y + 22, text="из 100", fill=theme.MUTED, font=theme.ui_font(8),
        )
        if self.label:
            self.create_text(
                width / 2, diameter + 4, text=self.label, fill=theme.MUTED,
                font=theme.ui_font(8, "bold"), width=max(80, width - 8), justify="center",
            )


class BarRow(tk.Frame):
    def __init__(self, master, title: str) -> None:
        super().__init__(master, background=theme.SURFACE)
        head = tk.Frame(self, background=theme.SURFACE)
        head.pack(fill="x")
        self.title = tk.Label(
            head, text=title, background=theme.SURFACE, foreground=theme.INK,
            font=theme.ui_font(8, "bold"), anchor="w",
        )
        self.value = tk.Label(
            head, text="", background=theme.SURFACE, foreground=theme.MUTED,
            font=theme.ui_font(8), anchor="e",
        )
        self.title.pack(side="left")
        self.value.pack(side="right")
        self.canvas = tk.Canvas(self, height=8, background=theme.SURFACE, highlightthickness=0)
        self.canvas.pack(fill="x", pady=(3, 1))
        self.detail = tk.Label(
            self, text="", background=theme.SURFACE, foreground="#94a3b8",
            font=theme.ui_font(7), anchor="w", wraplength=420, justify="left",
        )
        self.detail.pack(fill="x")
        self.canvas.bind("<Configure>", lambda _event: self.redraw())
        self._ratio = 0.0

    def set(self, penalty: float, maximum: float, detail: str = "") -> None:
        self._ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, penalty / maximum))
        self.value.configure(text=f"{penalty:.1f} / {maximum:.0f}")
        self.detail.configure(text=detail)
        self.redraw()

    def redraw(self) -> None:
        self.canvas.delete("all")
        width = max(10, self.canvas.winfo_width())
        height = 8
        self.canvas.create_rectangle(0, 0, width, height, fill=theme.BORDER, outline="")
        color = theme.GREEN if self._ratio < 0.25 else theme.YELLOW if self._ratio < 0.6 else theme.RED
        if self._ratio > 0:
            self.canvas.create_rectangle(0, 0, width * self._ratio, height, fill=color, outline="")


class TimelineChart(tk.Frame):
    """Линейный график с зумом, прокруткой, маркерами релизов и аномалиями."""

    def __init__(self, master, height: int = 290, on_select: Callable[[str], None] | None = None) -> None:
        super().__init__(master, background=theme.SURFACE)
        self.height = height
        self.on_select = on_select
        self.series: list[dict] = []
        self.buckets: list[str] = []
        self.markers: dict[str, str] = {}
        self.anomalies: set[str] = set()
        self.y_unit = ""
        self.zoom = 1.0
        self.offset = 0
        self._hover_bucket: str | None = None
        self._redraw_job: str | None = None

        toolbar = tk.Frame(self, background=theme.SURFACE)
        toolbar.pack(fill="x", pady=(0, 4))
        ttk.Button(toolbar, text="<", width=3, command=lambda: self.pan(-1)).pack(side="left")
        ttk.Button(toolbar, text=">", width=3, command=lambda: self.pan(1)).pack(side="left", padx=(3, 8))
        ttk.Button(toolbar, text="+", width=3, command=lambda: self.set_zoom(self.zoom * 1.5)).pack(side="left")
        ttk.Button(toolbar, text="-", width=3, command=lambda: self.set_zoom(self.zoom / 1.5)).pack(side="left", padx=(3, 8))
        self.range_label = tk.Label(
            toolbar, text="", background=theme.SURFACE, foreground=theme.MUTED, font=theme.ui_font(8)
        )
        self.range_label.pack(side="left")
        self.hover_label = tk.Label(
            toolbar, text="", background=theme.SURFACE, foreground=theme.INK, font=theme.ui_font(8, "bold")
        )
        self.hover_label.pack(side="right")

        body = tk.Frame(self, background=theme.SURFACE)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, background=theme.SURFACE, highlightthickness=0, height=height)
        self.scrollbar = ttk.Scrollbar(body, orient="horizontal", command=self._scroll)
        self.canvas.configure(xscrollcommand=self.scrollbar.set)
        self.canvas.pack(fill="both", expand=True)
        self.scrollbar.pack(fill="x")
        self.canvas.bind("<Configure>", self._schedule)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Button-1>", self._click)

    # ------------------------------------------------------------------ data
    def set_data(
        self,
        series: Sequence[dict],
        markers: dict[str, str] | None = None,
        anomalies: set[str] | None = None,
        y_unit: str = "",
    ) -> None:
        self.series = [
            {
                "name": item["name"],
                "color": item.get("color", theme.SERIES_COLORS[index % len(theme.SERIES_COLORS)]),
                "values": {point["bucket"]: float(point["value"]) for point in item["points"]},
            }
            for index, item in enumerate(series)
        ]
        self.buckets = sorted({row["bucket"] for item in series for row in item["points"]})
        self.markers = markers or {}
        self.anomalies = anomalies or set()
        self.y_unit = y_unit
        self.offset = 0
        self._redraw()

    def set_zoom(self, value: float) -> None:
        self.zoom = max(1.0, min(8.0, value))
        self.offset = min(self.offset, self._max_offset())
        self._redraw()

    def _visible_count(self) -> int:
        if not self.buckets:
            return 0
        return max(4, min(len(self.buckets), int(math.ceil(len(self.buckets) / self.zoom))))

    def _max_offset(self) -> int:
        return max(0, len(self.buckets) - self._visible_count())

    def pan(self, direction: int) -> None:
        step = max(1, self._visible_count() // 4)
        self.offset = max(0, min(self._max_offset(), self.offset + direction * step))
        self._redraw()

    def _scroll(self, *args) -> None:
        if not self.buckets:
            return
        if args and args[0] == "moveto":
            fraction = float(args[1])
            self.offset = int(round(fraction * self._max_offset()))
        elif args and args[0] == "scroll":
            amount = int(args[1])
            self.offset = max(0, min(self._max_offset(), self.offset + amount))
        self._redraw()

    # ------------------------------------------------------------------ draw
    def _schedule(self, _event=None) -> None:
        if self._redraw_job:
            self.after_cancel(self._redraw_job)
        self._redraw_job = self.after(40, self._redraw)

    def _redraw(self) -> None:
        self._redraw_job = None
        self.canvas.delete("all")
        width = max(420, self.canvas.winfo_width())
        height = self.height
        margin_left, margin_right, margin_top, margin_bottom = 52, 18, 32, 42
        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom
        if not self.buckets:
            self.canvas.create_text(
                width / 2, height / 2, text="Нет данных. Проиндексируйте репозиторий.",
                fill=theme.MUTED, font=theme.ui_font(9),
            )
            self.range_label.configure(text="")
            return
        visible = self._visible_count()
        start = max(0, min(self.offset, self._max_offset()))
        self.offset = start
        buckets = self.buckets[start : start + visible]
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self.scrollbar.set(
            start / max(1, self._max_offset()) if self._max_offset() else 0.0,
            min(1.0, (start + visible) / max(1, len(self.buckets))),
        )
        self.range_label.configure(text=f"{buckets[0]} - {buckets[-1]}   недель: {len(buckets)} из {len(self.buckets)}")

        maximum = max(
            (max((item["values"].get(bucket, 0.0) for bucket in buckets), default=0.0) for item in self.series),
            default=0.0,
        )
        maximum = maximum if maximum > 0 else 1.0
        if maximum < 10:
            maximum = 10.0

        for line in range(5):
            y = margin_top + plot_h * line / 4
            value = maximum * (4 - line) / 4
            self.canvas.create_line(
                margin_left, y, width - margin_right, y, fill=theme.BORDER, width=1
            )
            label = f"{value:.2f}" if maximum <= 2 else f"{value:.0f}"
            self.canvas.create_text(
                margin_left - 8, y, text=label, anchor="e", fill=theme.MUTED, font=theme.ui_font(7)
            )
        step = plot_w / max(1, len(buckets) - 1)
        for bucket in buckets:
            if bucket not in self.markers:
                continue
            x = margin_left + buckets.index(bucket) * step
            self.canvas.create_line(
                x, margin_top, x, margin_top + plot_h, fill="#cbd5e1", dash=(3, 3)
            )
            self.canvas.create_text(
                x, margin_top - 9, text=self.markers[bucket][:18], fill=theme.MUTED,
                font=theme.ui_font(7), anchor="n",
            )
        for item in self.series:
            points: list[tuple[float, float]] = []
            for index, bucket in enumerate(buckets):
                value = item["values"].get(bucket, 0.0)
                x = margin_left + index * step
                y = margin_top + plot_h * (1.0 - min(1.0, max(0.0, value / maximum)))
                points.append((x, y))
            if len(points) > 1:
                self.canvas.create_line(
                    [coordinate for point in points for coordinate in point],
                    fill=item["color"], width=2.2, smooth=False,
                )
            if len(points) <= 80:
                for index, (x, y) in enumerate(points):
                    bucket = buckets[index]
                    if bucket in self.anomalies:
                        self.canvas.create_oval(
                            x - 4, y - 4, x + 4, y + 4, fill=theme.RED, outline="#ffffff", width=1
                        )
                    else:
                        self.canvas.create_oval(
                            x - 2.2, y - 2.2, x + 2.2, y + 2.2, fill=item["color"], outline=""
                        )
        for index in sorted({0, len(buckets) // 2, len(buckets) - 1}):
            x = margin_left + index * step
            self.canvas.create_text(
                x, margin_top + plot_h + 14, text=buckets[index][5:], fill=theme.MUTED,
                font=theme.ui_font(7), anchor="n",
            )
        legend_x = margin_left
        for index, item in enumerate(self.series):
            y = height - 9
            self.canvas.create_rectangle(legend_x, y - 4, legend_x + 8, y + 4, fill=item["color"], outline="")
            self.canvas.create_text(
                legend_x + 13, y, text=item["name"][:28], fill=theme.MUTED, font=theme.ui_font(7), anchor="w"
            )
            legend_x += 165
        if self.y_unit:
            self.canvas.create_text(
                width - margin_right, height - 9, text=self.y_unit, fill="#94a3b8",
                font=theme.ui_font(7), anchor="e",
            )
        if self._hover_bucket:
            self._draw_hover(margin_left, margin_top, plot_w, plot_h, buckets, step, maximum)

    def _draw_hover(self, left, top, plot_w, plot_h, buckets, step, maximum) -> None:
        bucket = self._hover_bucket
        if bucket not in buckets:
            return
        index = buckets.index(bucket)
        x = left + index * step
        self.canvas.create_line(x, top, x, top + plot_h, fill=theme.ACCENT, dash=(2, 2), tags="hover")
        lines = [bucket]
        for item in self.series:
            value = item["values"].get(bucket, 0.0)
            lines.append(f"{item['name']}: {value:.2f}")
        self.hover_label.configure(text="   ".join(lines))

    def _bucket_at(self, event) -> str | None:
        if not self.buckets:
            return None
        width = max(420, self.canvas.winfo_width())
        margin_left, margin_right = 52, 18
        visible = self._visible_count()
        start = max(0, min(self.offset, self._max_offset()))
        buckets = self.buckets[start : start + visible]
        step = (width - margin_left - margin_right) / max(1, len(buckets) - 1)
        index = int(round((event.x - margin_left) / max(1e-9, step)))
        if 0 <= index < len(buckets):
            return buckets[index]
        return None

    def _motion(self, event) -> None:
        bucket = self._bucket_at(event)
        if bucket and bucket != self._hover_bucket:
            self._hover_bucket = bucket
            self._redraw()
        elif bucket is None and self._hover_bucket is not None:
            self._hover_bucket = None
            self.hover_label.configure(text="")
            self.canvas.delete("hover")
            self._redraw()

    def _click(self, event) -> None:
        bucket = self._bucket_at(event)
        if bucket and self.on_select:
            self.on_select(bucket)

    def _wheel(self, event) -> None:
        if event.state & 0x0004:  # Ctrl - зум
            self.set_zoom(self.zoom * (1.2 if event.delta > 0 else 1 / 1.2))
        else:
            self.pan(-1 if event.delta > 0 else 1)


class EgoGraph(tk.Canvas):
    """Радиальная схема выбранного узла и его соседей."""

    def __init__(self, master, on_node_click: Callable[[str], None] | None = None) -> None:
        super().__init__(master, background=theme.SURFACE, highlightthickness=0, height=520)
        self.on_node_click = on_node_click
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.center_id = ""
        self._hit: list[tuple[float, float, float, str]] = []
        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", self._motion)

    def set_graph(self, nodes: Sequence[dict], edges: Sequence[dict], center_id: str) -> None:
        self.nodes = {row["node_id"]: row for row in nodes}
        self.edges = list(edges)
        self.center_id = center_id
        self.redraw()

    def _neighbors(self) -> list[tuple[str, str, int]]:
        rows: dict[str, tuple[str, int]] = {}
        for edge in self.edges:
            if edge["src"] == self.center_id:
                other = edge["dst"]
                direction = "out"
            elif edge["dst"] == self.center_id:
                other = edge["src"]
                direction = "in"
            else:
                continue
            if other not in self.nodes or other == self.center_id:
                continue
            previous = rows.get(other)
            if previous is None:
                rows[other] = (direction, 1)
            else:
                rows[other] = (previous[0] if previous[0] == direction else "both", previous[1] + 1)
        return [(node_id, direction, weight) for node_id, (direction, weight) in sorted(rows.items())]

    def redraw(self) -> None:
        self.delete("all")
        self._hit = []
        width = self.winfo_width() or 600
        height = self.winfo_height() or 500
        if not self.center_id or self.center_id not in self.nodes:
            self.create_text(
                width / 2, height / 2, text="Выберите узел в списке слева",
                fill=theme.MUTED, font=theme.ui_font(9),
            )
            return
        center = self.nodes[self.center_id]
        cx, cy = width / 2, height / 2
        neighbours = self._neighbors()
        if len(neighbours) > 26:
            neighbours = neighbours[:26]
        self.create_text(
            12, 12, text=f"{center.get('name', center['node_id'])} ({center.get('kind', '')})",
            anchor="nw", fill=theme.INK, font=theme.ui_font(9, "bold"),
        )
        self.create_text(
            12, 30, text=f"соседей: {len(self._neighbors())}, показано: {len(neighbours)}",
            anchor="nw", fill=theme.MUTED, font=theme.ui_font(7),
        )
        radius = min(width, height) / 2 - 76
        positions: list[tuple[float, float]] = []
        count = max(1, len(neighbours))
        for index in range(len(neighbours)):
            angle = 2 * math.pi * index / count - math.pi / 2
            positions.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        for index, (node_id, direction, weight) in enumerate(neighbours):
            x, y = positions[index]
            color = theme.BLUE if direction in {"out", "both"} else theme.ORANGE
            self.create_line(cx, cy, x, y, fill=color, width=1.2, arrow="last" if direction in {"out", "both"} else None)
            node = self.nodes.get(node_id, {})
            node_color = {
                "file": theme.ACCENT, "module": theme.ACCENT, "class": theme.PURPLE, "function": theme.BLUE
            }.get(node.get("kind", ""), theme.MUTED)
            self.create_oval(x - 7, y - 7, x + 7, y + 7, fill=node_color, outline="#ffffff", width=2)
            label = str(node.get("name", node_id))
            if node.get("kind") == "file":
                parts = label.replace("\\", "/").split("/")
                if len(parts) > 2:
                    label = "/".join(parts[-2:])
            if len(label) > 26:
                label = label[:24] + ".."
            self.create_text(x, y + 14, text=label, fill=theme.INK, font=theme.ui_font(7), anchor="n")
            self._hit.append((x, y, 12, node_id))
        self.create_oval(cx - 13, cy - 13, cx + 13, cy + 13, fill=theme.INK, outline="#ffffff", width=3)
        self.create_text(
            cx, cy + 20, text=center.get("name", self.center_id), fill=theme.INK,
            font=theme.ui_font(9, "bold"), anchor="n",
        )
        legend = "синяя стрелка: исходящая, оранжевая: входящая"
        self.create_text(width - 12, height - 10, text=legend, anchor="se", fill=theme.MUTED, font=theme.ui_font(7))

    def _click(self, event) -> None:
        for x, y, radius, node_id in self._hit:
            if (event.x - x) ** 2 + (event.y - y) ** 2 <= radius ** 2:
                if self.on_node_click:
                    self.on_node_click(node_id)
                return

    def _motion(self, _event) -> None:
        pass


class EmptyState(tk.Frame):
    def __init__(self, master, title: str, text: str) -> None:
        super().__init__(master, background=theme.SURFACE)
        tk.Label(
            self, text=title, background=theme.SURFACE, foreground=theme.INK,
            font=theme.ui_font(14, "bold"),
        ).pack(pady=(80, 8))
        tk.Label(
            self, text=text, background=theme.SURFACE, foreground=theme.MUTED,
            font=theme.ui_font(9), wraplength=480, justify="center",
        ).pack()


def treeview_with_scroll(master, columns: Sequence[tuple[str, str, int]], height: int = 10) -> tuple[ttk.Frame, ttk.Treeview]:
    frame = ttk.Frame(master, style="Surface.TFrame")
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height)
    for key, title, width in columns:
        tree.heading(key, text=title)
        tree.column(key, width=width, anchor="w", stretch=key == columns[-1][0])
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return frame, tree


def clear_tree(tree: ttk.Treeview) -> None:
    for item in tree.get_children():
        tree.delete(item)
