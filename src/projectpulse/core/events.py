"""События прогресса, отмена операций и логирование."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Protocol


class AppError(Exception):
    """Базовая ошибка приложения."""


class RepoError(AppError):
    """Ошибка работы с репозиторием."""


class IndexCancelled(AppError):
    """Индексация отменена пользователем."""


class ReportError(AppError):
    """Ошибка формирования отчёта."""


class GitError(AppError):
    """Ошибка вызова git."""


@dataclass(frozen=True)
class Progress:
    phase: str
    message: str
    current: int = 0
    total: int = 0

    @property
    def fraction(self) -> float:
        if self.total <= 0:
            return 0.0
        return max(0.0, min(1.0, self.current / self.total))


class ProgressCallback(Protocol):
    def __call__(self, event: Progress) -> None: ...


class NullProgress:
    def __call__(self, event: Progress) -> None:
        return None


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise IndexCancelled("Операция отменена пользователем")


def make_logger(name: str = "projectpulse") -> logging.Logger:
    return logging.getLogger(name)


def setup_logging(log_path: Path, level: int = logging.INFO) -> logging.Logger:
    """Настраивает ротацию логов и консольный вывод. Идемпотентно."""
    logger = logging.getLogger("projectpulse")
    logger.setLevel(level)
    if getattr(setup_logging, "_configured", False):
        return logger

    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(formatter)
    logger.addHandler(console)

    setup_logging._configured = True  # type: ignore[attr-defined]
    return logger


def close_logging() -> None:
    """Закрывает файловые обработчики, чтобы процесс мог завершиться без блокировок."""
    logger = logging.getLogger("projectpulse")
    for handler in list(logger.handlers):
        try:
            handler.flush()
            handler.close()
        except OSError:  # pragma: no cover - сбой закрытия не должен ломать выход
            pass
        logger.removeHandler(handler)
    setup_logging._configured = False  # type: ignore[attr-defined]


def read_log_tail(log_path: Path, lines: int = 300) -> str:
    if not log_path.exists():
        return ""
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            content = handle.readlines()
        return "".join(content[-lines:])
    except OSError as exc:  # pragma: no cover - редкий сбой файловой системы
        return f"Не удалось прочитать журнал: {exc}"


class TaskRunner:
    """Фоновое выполнение задач с очередью событий для Tkinter."""

    def __init__(self, on_done: Callable[[object], None], on_error: Callable[[Exception], None]):
        self._on_done = on_done
        self._on_error = on_error

    def run(self, target: Callable[[], object]) -> threading.Thread:
        thread = threading.Thread(target=self._wrapper, args=(target,), daemon=True)
        thread.start()
        return thread

    def _wrapper(self, target: Callable[[], object]) -> None:
        try:
            result = target()
        except Exception as exc:  # noqa: BLE001 - ошибка должна попасть в UI
            self._on_error(exc)
        else:
            self._on_done(result)
