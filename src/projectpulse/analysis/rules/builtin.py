"""Встроенные правила риска: 10 правил, 4 из них на трендах."""

from __future__ import annotations

from projectpulse.analysis.anomalies import zscore_anomalies
from projectpulse.analysis.rules.base import Finding, Rule
from projectpulse.core.utils import is_support_module, is_support_path, mean, percentage, percentile, safe_div


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


class HotspotRule(Rule):
    name = "hotspot_complex_churn"
    description = "Файл одновременно сложный и часто меняется"

    def evaluate(self, ctx, metrics) -> list[Finding]:
        complexity = {
            path: value
            for path, value in metrics.files("complexity_max")
            if not is_support_path(path)
        }
        churn = {
            path: value for path, value in metrics.files("churn_90d") if not is_support_path(path)
        }
        if not complexity:
            return []
        threshold = ctx.thresholds
        p90 = percentile(list(complexity.values()), threshold.hotspot_complexity_percentile)
        p75_churn = percentile(list(churn.values()), threshold.hotspot_churn_percentile)
        rows = []
        for path, value in complexity.items():
            if value < max(threshold.hotspot_min_complexity, p90):
                continue
            if churn.get(path, 0) < max(1.0, p75_churn):
                continue
            risk = (value / max(p90, 1)) * (churn.get(path, 0) / max(p75_churn, 1))
            rows.append((risk, path, value, churn.get(path, 0)))
        rows.sort(reverse=True)
        findings: list[Finding] = []
        for risk, path, value, churn_value in rows[:8]:
            critical = value >= percentile(list(complexity.values()), 0.95) and churn_value >= percentile(
                list(churn.values()), 0.90
            )
            findings.append(
                Finding(
                    rule=self.name,
                    severity="critical" if critical else "warning",
                    target=path,
                    title="Сложный и часто изменяемый файл",
                    explanation=(
                        f"Максимальная сложность функции {value:.0f} (порог P90 = {p90:.0f}), "
                        f"churn за 90 дней {churn_value:.0f} строк (порог P75 = {p75_churn:.0f}). "
                        "Высокая сложность вместе с частыми правками повышает вероятность дефектов."
                    ),
                    recommendation=(
                        "Разбить крупные функции на более простые, покрыть изменяемые ветки тестами "
                        "и вынести стабильную часть в отдельный модуль."
                    ),
                    value={"complexity_max": value, "p90_complexity": p90, "churn_90d": churn_value, "p75_churn": p75_churn},
                )
            )
        return findings


class BusFactorRule(Rule):
    name = "bus_factor_one"
    description = "Модуль держится на одном авторе"

    def evaluate(self, ctx, metrics) -> list[Finding]:
        factors = dict(metrics.modules("bus_factor"))
        commits = dict(metrics.modules("module_commits"))
        authors = dict(metrics.modules("bus_factor_authors"))
        rows = [
            (commits.get(module, 0), module)
            for module, value in factors.items()
            if value <= 1
            and commits.get(module, 0) >= ctx.thresholds.bus_factor_commits_min
            and not is_support_module(module)
        ]
        rows.sort(reverse=True)
        findings: list[Finding] = []
        for commit_count, module in rows[:8]:
            findings.append(
                Finding(
                    rule=self.name,
                    severity="critical" if commit_count >= 20 else "warning",
                    target=module,
                    title="Bus factor равен 1",
                    explanation=(
                        f"Модуль {module} имеет bus factor 1 при {commit_count:.0f} коммитах "
                        f"и {authors.get(module, 1):.0f} авторах. "
                        "Уход единственного носителя знаний остановит развитие модуля."
                    ),
                    recommendation=(
                        "Провести парное программирование, назначить второго сопровождающего, "
                        "добавить архитектурные заметки и тесты на ключевые сценарии."
                    ),
                    value={"bus_factor": 1, "commits": commit_count, "authors": authors.get(module, 1)},
                )
            )
        return findings


class OwnershipConcentrationRule(Rule):
    name = "ownership_concentration"
    description = "Файл почти полностью принадлежит одному автору"

    def evaluate(self, ctx, metrics) -> list[Finding]:
        shares = dict(metrics.files("ownership_top_share"))
        commits = dict(metrics.files("commit_count"))
        rows = [
            (share, path)
            for path, share in shares.items()
            if share >= ctx.thresholds.ownership_share_high
            and commits.get(path, 0) >= ctx.thresholds.ownership_commits_min
            and not is_support_path(path)
        ]
        rows.sort(reverse=True)
        findings: list[Finding] = []
        for share, path in rows[:8]:
            findings.append(
                Finding(
                    rule=self.name,
                    severity="warning",
                    target=path,
                    title="Высокая концентрация владения",
                    explanation=(
                        f"Доля ведущего автора {percentage(share)} при {commits.get(path, 0):.0f} коммитах. "
                        f"Порог концентрации {percentage(ctx.thresholds.ownership_share_high)}. "
                        "Знания о файле сосредоточены у одного человека."
                    ),
                    recommendation="Привлекать второго автора к правкам, проводить ревью и фиксировать решения в документации.",
                    value={"top_share": share, "commits": commits.get(path, 0)},
                )
            )
        return findings


class CycleRule(Rule):
    name = "dependency_cycle"
    description = "В графе импортов обнаружен цикл"

    def evaluate(self, ctx, metrics) -> list[Finding]:
        findings: list[Finding] = []
        for component in ctx.file_graph.cycles()[:5]:
            if any(is_support_path(path) for path in component):
                continue
            package_reexport = any(path.endswith("__init__.py") for path in component)
            findings.append(
                Finding(
                    rule=self.name,
                    severity="warning" if package_reexport else "critical",
                    target=" -> ".join(component),
                    title="Цикл через реэкспорт пакета" if package_reexport else "Циклическая зависимость файлов",
                    explanation=(
                        f"Компонента сильной связности из {len(component)} файлов: "
                        + ", ".join(component)
                        + ". Циклы усложняют повторное использование и тестирование."
                        + (" Цикл проходит через __init__.py, что типично для реэкспорта, но повышает связность." if package_reexport else "")
                    ),
                    recommendation="Вынести общую часть в отдельный модуль или применить инверсию зависимостей.",
                    value={"cycle_nodes": component, "size": len(component), "package_reexport": package_reexport},
                )
            )
        return findings


class GodModuleRule(Rule):
    name = "god_module"
    description = "Модуль с высокой связностью и большим размером"

    def evaluate(self, ctx, metrics) -> list[Finding]:
        fan_in = dict(metrics.files("fan_in"))
        fan_out = dict(metrics.files("fan_out"))
        loc = {path: float(ctx.files_by_path[path].get("loc", 0)) for path in ctx.files_by_path}
        findings: list[Finding] = []
        rows = []
        for path in fan_in:
            if is_support_path(path):
                continue
            if (
                fan_in[path] >= ctx.thresholds.god_module_fan_in
                and fan_out.get(path, 0) >= ctx.thresholds.god_module_fan_out
                and loc.get(path, 0) >= ctx.thresholds.god_module_loc
            ):
                rows.append((fan_in[path] + fan_out[path], path))
        rows.sort(reverse=True)
        for score, path in rows[:5]:
            findings.append(
                Finding(
                    rule=self.name,
                    severity="warning",
                    target=path,
                    title="Модуль-посредник с высокой связностью",
                    explanation=(
                        f"fan-in {fan_in[path]:.0f}, fan-out {fan_out.get(path, 0):.0f}, "
                        f"LOC {loc.get(path, 0):.0f}. Пороговые значения: "
                        f"{ctx.thresholds.god_module_fan_in}/{ctx.thresholds.god_module_fan_out}/"
                        f"{ctx.thresholds.god_module_loc}."
                    ),
                    recommendation="Разделить модуль по ответственностям и уменьшить число зависимостей.",
                    value={"fan_in": fan_in[path], "fan_out": fan_out.get(path, 0), "loc": loc.get(path, 0)},
                )
            )
        return findings


class ChurnSpikeRule(Rule):
    name = "churn_spike"
    description = "Резкий скачок недельного churn"
    trend = True

    def evaluate(self, ctx, metrics) -> list[Finding]:
        rows_series = ctx.series.get("churn_weekly", [])
        values = [float(row["value"]) for row in rows_series]
        buckets = [row["bucket"] for row in rows_series]
        anomalies = zscore_anomalies(values, threshold=ctx.thresholds.churn_spike_z)
        findings: list[Finding] = []
        recent_start = max(0, len(values) - ctx.thresholds.churn_spike_recent_weeks)
        for anomaly in [item for item in anomalies if item.index >= recent_start][-5:]:
            bucket = buckets[anomaly.index] if anomaly.index < len(buckets) else "?"
            findings.append(
                Finding(
                    rule=self.name,
                    severity="critical" if anomaly.z >= 4.5 else "warning",
                    target=bucket,
                    title="Скачок объёма изменений",
                    explanation=(
                        f"За неделю {bucket} churn {anomaly.value:.0f} строк, что выше среднего "
                        f"{anomaly.baseline_mean:.0f} на {anomaly.z:.2f} стандартных отклонения "
                        f"(std {anomaly.baseline_std:.0f}, порог {ctx.thresholds.churn_spike_z:.1f})."
                    ),
                    recommendation="Проверить крупные коммиты недели, разделить изменения и убедиться в наличии тестов.",
                    value={"bucket": bucket, "churn": anomaly.value, "z": anomaly.z, "mean": anomaly.baseline_mean, "std": anomaly.baseline_std},
                )
            )
        return findings


class ChurnVolatilityRiseRule(Rule):
    name = "churn_volatility_rise"
    description = "Рост волатильности churn относительно предыдущего окна"
    trend = True

    def evaluate(self, ctx, metrics) -> list[Finding]:
        recent = metrics.get("churn_volatility_recent")
        previous = metrics.get("churn_volatility_previous")
        threshold = ctx.thresholds
        ratio = safe_div(recent, previous, 0.0)
        if recent < threshold.volatility_min:
            return []
        if previous > 0 and ratio < threshold.volatility_ratio:
            return []
        if previous <= 0 and recent < threshold.volatility_min * 2:
            return []
        return [
            Finding(
                rule=self.name,
                severity="critical" if recent >= threshold.volatility_min * 2 else "warning",
                target="churn_weekly",
                title="Волатильность изменений растёт",
                explanation=(
                    f"Средний CV churn за последние 4 недели {recent:.2f}, за предыдущие 4 недели {previous:.2f}, "
                    f"отношение {ratio:.2f} (порог {threshold.volatility_ratio:.2f}), "
                    f"минимум {threshold.volatility_min:.2f}."
                ),
                recommendation="Сгладить поток изменений: ограничить размер коммитов, ввести регулярные релизы и планирование.",
                value={"recent": recent, "previous": previous, "ratio": ratio},
            )
        ]


class FixPressureTrendRule(Rule):
    name = "fix_pressure_trend"
    description = "Рост доли багфикс-коммитов к предыдущему периоду"
    trend = True

    def evaluate(self, ctx, metrics) -> list[Finding]:
        recent = metrics.get("fix_pressure_recent")
        previous = metrics.get("fix_pressure_previous")
        threshold = ctx.thresholds
        if recent <= 0:
            return []
        growth = safe_div(recent - previous, max(previous, 1e-9), 0.0)
        if previous > 0 and growth < threshold.fix_pressure_growth:
            return []
        if previous <= 0 and recent < 0.25:
            return []
        if recent < 0.20:
            return []
        file_rows = sorted(
            (
                (metrics.get("fix_pressure_growth", path, scope="file"), path, metrics.get("fix_pressure_recent", path, scope="file"))
                for path in ctx.files_by_path
                if not is_support_path(path)
            ),
            reverse=True,
        )
        top_file = file_rows[0] if file_rows else ("", 0.0, 0.0)
        critical = growth >= threshold.fix_pressure_critical_growth and recent >= threshold.fix_pressure_critical_recent
        return [
            Finding(
                rule=self.name,
                severity="critical" if critical else "warning",
                target=top_file[1] or "project",
                title="Растёт давление багфиксов",
                explanation=(
                    f"FPI за последние {threshold.fix_pressure_recent_days} дней {percentage(recent)}, "
                    f"за предыдущий период {percentage(previous)}, рост {percentage(max(0.0, growth))} "
                    f"(порог {percentage(threshold.fix_pressure_growth)}). "
                    f"Наибольший вклад у файла {top_file[1] or 'n/a'} ({percentage(top_file[2])})."
                ),
                recommendation="Выделить время на рефакторинг и регрессионные тесты, проверить качество ревью и стабильность API.",
                value={"recent": recent, "previous": previous, "growth": growth, "top_file": top_file[1]},
            )
        ]


class OwnershipDriftRule(Rule):
    name = "ownership_drift"
    description = "Сильное смещение доли ведущего автора"
    trend = True

    def evaluate(self, ctx, metrics) -> list[Finding]:
        latest = metrics.get("ownership_drift")
        authors = metrics.get("bus_factor_authors")
        threshold = ctx.thresholds
        if latest < threshold.ownership_drift_threshold or authors < 3:
            return []
        return [
            Finding(
                rule=self.name,
                severity="critical" if latest >= threshold.ownership_drift_threshold * 2 else "warning",
                target="ownership",
                title="Дрейф владения кодом",
                explanation=(
                    f"Смещение доли ведущего автора между 4-недельными окнами {percentage(latest)}, "
                    f"порог {percentage(threshold.ownership_drift_threshold)}, авторов {authors:.0f}. "
                    "Резкая смена ведущего автора создаёт риск потери контекста."
                ),
                recommendation="Зафиксировать передачу знаний: ревью, парное программирование, актуализация документации.",
                value={"ownership_drift": latest, "authors": authors},
            )
        ]


class ApiVolatilityRule(Rule):
    name = "api_volatility_high"
    description = "Публичный API файла часто меняется"

    def evaluate(self, ctx, metrics) -> list[Finding]:
        values = dict(metrics.files("interface_volatility"))
        changes = dict(metrics.files("api_change_commits"))
        rows = [
            (value, path)
            for path, value in values.items()
            if value >= ctx.thresholds.api_volatility_threshold
            and changes.get(path, 0) >= ctx.thresholds.api_min_public_changes
            and not is_support_path(path)
        ]
        rows.sort(reverse=True)
        findings: list[Finding] = []
        for value, path in rows[:8]:
            findings.append(
                Finding(
                    rule=self.name,
                    severity="warning",
                    target=path,
                    title="Нестабильный публичный API",
                    explanation=(
                        f"IVI {percentage(value)} при {changes.get(path, 0):.0f} коммитах с изменением "
                        f"публичных def/class. Порог {percentage(ctx.thresholds.api_volatility_threshold)}, "
                        f"минимум {ctx.thresholds.api_min_public_changes} изменений."
                    ),
                    recommendation="Стабилизировать публичные имена, добавить слой совместимости и зафиксировать API в тестах.",
                    value={"interface_volatility": value, "public_change_commits": changes.get(path, 0)},
                )
            )
        return findings


def default_rules() -> list[Rule]:
    return [
        HotspotRule(),
        BusFactorRule(),
        OwnershipConcentrationRule(),
        CycleRule(),
        GodModuleRule(),
        ChurnSpikeRule(),
        ChurnVolatilityRiseRule(),
        FixPressureTrendRule(),
        OwnershipDriftRule(),
        ApiVolatilityRule(),
    ]


def register_default_rules(registry) -> None:
    for rule in default_rules():
        registry.register(rule, source="builtin")
