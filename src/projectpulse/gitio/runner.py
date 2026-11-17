"""Обёртка над git CLI: история, деревья, blob-ы, ссылки."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from projectpulse.core.events import GitError
from projectpulse.core.utils import stable_id


@dataclass(frozen=True)
class FileChange:
    path: str
    additions: int
    deletions: int
    is_binary: bool = False


@dataclass(frozen=True)
class CommitRecord:
    sha: str
    author_name: str
    author_email: str
    ts: int
    message: str
    changes: tuple[FileChange, ...] = ()
    is_bugfix: bool = False

    @property
    def insertions(self) -> int:
        return sum(change.additions for change in self.changes)

    @property
    def deletions(self) -> int:
        return sum(change.deletions for change in self.changes)

    @property
    def files_changed(self) -> int:
        return len(self.changes)

    def as_dict(self) -> dict:
        return {
            "sha": self.sha,
            "author_name": self.author_name,
            "author_email": self.author_email,
            "ts": self.ts,
            "message": self.message,
            "is_bugfix": int(self.is_bugfix),
            "insertions": self.insertions,
            "deletions": self.deletions,
            "files_changed": self.files_changed,
        }


@dataclass(frozen=True)
class BlobInfo:
    path: str
    sha: str
    mode: str


@dataclass(frozen=True)
class RefInfo:
    name: str
    sha: str
    ts: int


_BUGFIX_RE = re.compile(
    r"(?i)\b(fix|fixes|fixed|bug|bugfix|hotfix|issue|crash|regression|"
    r"исправ|почин|баг)\w*"
)


def mark_bugfix(message: str, pattern: str | None = None) -> bool:
    regex = re.compile(pattern) if pattern else _BUGFIX_RE
    return bool(regex.search(message or ""))


class GitRunner:
    def __init__(self, git_path: str = "git", timeout: int = 120) -> None:
        self.git_path = git_path
        self.timeout = timeout

    # ------------------------------------------------------------------ base
    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "GIT_PAGER": "cat",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "0",
                "LC_ALL": "C.UTF-8",
                "LANG": "C.UTF-8",
            }
        )
        return env

    def _cmd(self, repo: Path | str, args: Sequence[str]) -> list[str]:
        return [
            self.git_path,
            "-C",
            str(repo),
            "-c",
            "core.quotepath=false",
            "-c",
            "i18n.logOutputEncoding=UTF-8",
            *args,
        ]

    def _run(
        self,
        repo: Path | str,
        args: Sequence[str],
        *,
        timeout: int | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        command = self._cmd(repo, args)
        creationflags = 0
        if os.name == "nt":
            creationflags = 0x08000000  # CREATE_NO_WINDOW
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout or self.timeout,
                env=self._env(),
                creationflags=creationflags,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GitError("git не найден в PATH. Установите Git для Windows.") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git превысил таймаут ({timeout or self.timeout} с)") from exc
        if check and result.returncode != 0:
            message = result.stderr.decode("utf-8", "replace").strip()
            raise GitError(f"git {' '.join(args)} завершился с ошибкой: {message}")
        return result

    def run_text(self, repo: Path | str, args: Sequence[str], *, timeout: int | None = None, check: bool = True) -> str:
        result = self._run(repo, args, timeout=timeout, check=check)
        return result.stdout.decode("utf-8", "replace")

    def run_bytes(self, repo: Path | str, args: Sequence[str], *, timeout: int | None = None, check: bool = True) -> bytes:
        return self._run(repo, args, timeout=timeout, check=check).stdout

    def version(self) -> str:
        try:
            result = subprocess.run(
                [self.git_path, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                creationflags=0x08000000 if os.name == "nt" else 0,
                check=False,
            )
        except FileNotFoundError:
            return "not found"
        return result.stdout.decode("utf-8", "replace").strip()

    # ------------------------------------------------------------ repository
    @staticmethod
    def normalize_path(path: Path | str) -> Path:
        return Path(path).expanduser().resolve()

    def ensure_repository(self, path: Path | str) -> Path:
        repo = self.normalize_path(path)
        if not repo.exists():
            raise GitError(f"Каталог не найден: {repo}")
        if not repo.is_dir():
            raise GitError(f"Путь не является каталогом: {repo}")
        result = self._run(repo, ["rev-parse", "--git-dir"], check=False)
        if result.returncode != 0:
            raise GitError(f"Каталог не является git-репозиторием: {repo}")
        return repo

    def head_sha(self, repo: Path | str) -> str | None:
        result = self._run(repo, ["rev-parse", "--verify", "HEAD"], check=False)
        if result.returncode != 0:
            return None
        value = result.stdout.decode("utf-8", "replace").strip()
        return value or None

    def current_branch(self, repo: Path | str) -> str:
        result = self._run(repo, ["rev-parse", "--abbrev-ref", "HEAD"], check=False)
        if result.returncode != 0:
            return ""
        return result.stdout.decode("utf-8", "replace").strip()

    def remote_url(self, repo: Path | str) -> str | None:
        result = self._run(repo, ["config", "--get", "remote.origin.url"], check=False)
        if result.returncode != 0:
            return None
        value = result.stdout.decode("utf-8", "replace").strip()
        return value or None

    def commit_count(self, repo: Path | str) -> int:
        result = self._run(repo, ["rev-list", "--count", "HEAD"], check=False)
        if result.returncode != 0:
            return 0
        try:
            return int(result.stdout.decode("utf-8", "replace").strip())
        except ValueError:
            return 0

    def resolve_ref(self, repo: Path | str, ref: str) -> str | None:
        result = self._run(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"], check=False)
        if result.returncode != 0:
            return None
        value = result.stdout.decode("utf-8", "replace").strip()
        return value or None

    def is_ancestor(self, repo: Path | str, ancestor: str, descendant: str) -> bool:
        result = self._run(repo, ["merge-base", "--is-ancestor", ancestor, descendant], check=False)
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        raise GitError(result.stderr.decode("utf-8", "replace").strip())

    def parent(self, repo: Path | str, sha: str) -> str | None:
        result = self._run(repo, ["rev-parse", "--verify", f"{sha}^"], check=False)
        if result.returncode != 0:
            return None
        value = result.stdout.decode("utf-8", "replace").strip()
        return value or None

    def clone(self, url: str, destination: Path | str) -> Path:
        target = Path(destination).expanduser().resolve()
        if target.exists() and any(target.iterdir()):
            raise GitError(f"Каталог для клонирования не пуст: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [self.git_path, "clone", "--quiet", url, str(target)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
            creationflags=0x08000000 if os.name == "nt" else 0,
            check=False,
            timeout=900,
        )
        if result.returncode != 0:
            raise GitError(
                "Не удалось клонировать репозиторий: "
                + result.stderr.decode("utf-8", "replace").strip()
            )
        return target

    # ---------------------------------------------------------------- history
    def history(
        self,
        repo: Path | str,
        *,
        since: str | None = None,
        limit: int | None = None,
        bugfix_pattern: str | None = None,
    ) -> list[CommitRecord]:
        range_spec = f"{since}..HEAD" if since else "HEAD"
        args = [
            "log",
            "--reverse",
            "--no-merges",
            "--no-renames",
            "--numstat",
            "--date=unix",
            "--pretty=format:%x01%H%x1f%an%x1f%ae%x1f%at%x1f%s",
            range_spec,
        ]
        if limit:
            args.insert(4, f"--max-count={limit}")
        output = self.run_text(repo, args, timeout=max(self.timeout, 180))
        return self._parse_history(output, bugfix_pattern)

    @staticmethod
    def _parse_history(output: str, bugfix_pattern: str | None = None) -> list[CommitRecord]:
        records: list[CommitRecord] = []
        current: dict | None = None
        changes: list[FileChange] = []

        def flush() -> None:
            nonlocal current, changes
            if current is None:
                return
            records.append(
                CommitRecord(
                    sha=current["sha"],
                    author_name=current["author_name"],
                    author_email=current["author_email"],
                    ts=current["ts"],
                    message=current["message"],
                    changes=tuple(changes),
                    is_bugfix=mark_bugfix(current["message"], bugfix_pattern),
                )
            )
            current = None
            changes = []

        for line in output.splitlines():
            if "\x01" in line:
                flush()
                header = line.split("\x01", 1)[1]
                parts = header.split("\x1f", 4)
                if len(parts) < 5:
                    continue
                try:
                    ts = int(parts[3])
                except ValueError:
                    ts = 0
                current = {
                    "sha": parts[0].strip(),
                    "author_name": parts[1],
                    "author_email": parts[2],
                    "ts": ts,
                    "message": parts[4],
                }
                continue
            if current is None or not line.strip():
                continue
            pieces = line.split("\t", 2)
            if len(pieces) != 3:
                continue
            add_raw, del_raw, path = pieces
            is_binary = add_raw == "-" and del_raw == "-"
            try:
                additions = 0 if is_binary else int(add_raw)
                deletions = 0 if is_binary else int(del_raw)
            except ValueError:
                additions = deletions = 0
            changes.append(FileChange(path=path, additions=additions, deletions=deletions, is_binary=is_binary))
        flush()
        return records

    def rev_list(self, repo: Path | str, spec: str) -> list[str]:
        output = self.run_text(repo, ["rev-list", "--reverse", spec])
        return [line.strip() for line in output.splitlines() if line.strip()]

    # ------------------------------------------------------------------ tree
    def tree_files(self, repo: Path | str, rev: str) -> list[BlobInfo]:
        output = self.run_bytes(repo, ["ls-tree", "-r", "-z", "--full-tree", rev])
        result: list[BlobInfo] = []
        for entry in output.split(b"\x00"):
            if not entry:
                continue
            try:
                meta, raw_path = entry.split(b"\t", 1)
                mode, kind, sha = meta.split(b" ", 2)
            except ValueError:
                continue
            if kind != b"blob":
                continue
            path = raw_path.decode("utf-8", "replace")
            result.append(
                BlobInfo(path=path, sha=sha.decode("ascii", "replace"), mode=mode.decode("ascii", "replace"))
            )
        return result

    def read_blobs(self, repo: Path | str, shas: Iterable[str]) -> dict[str, bytes | None]:
        unique = list(dict.fromkeys(shas))
        if not unique:
            return {}
        result: dict[str, bytes | None] = {}
        creationflags = 0x08000000 if os.name == "nt" else 0
        process = subprocess.Popen(
            self._cmd(repo, ["cat-file", "--batch"]),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
            creationflags=creationflags,
        )
        assert process.stdin and process.stdout
        try:
            for sha in unique:
                process.stdin.write(sha.encode("ascii") + b"\n")
                process.stdin.flush()
                header = process.stdout.readline()
                if not header:
                    result[sha] = None
                    continue
                parts = header.strip().split(b" ")
                if len(parts) < 3 or parts[1] != b"blob":
                    result[sha] = None
                    continue
                size = int(parts[2])
                data = process.stdout.read(size)
                process.stdout.read(1)
                result[sha] = data
                if len(data) != size:
                    result[sha] = None
        finally:
            try:
                if process.stdin:
                    process.stdin.close()
            except OSError:
                pass
            process.wait(timeout=30)
            for stream in (process.stdout, process.stderr):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass
        return result

    def file_at(self, repo: Path | str, rev: str, path: str) -> bytes | None:
        result = self._run(repo, ["show", f"{rev}:{path}"], check=False)
        if result.returncode != 0:
            return None
        return result.stdout

    def patch_history(self, repo: Path | str, path: str, limit: int = 20) -> str:
        return self.run_text(
            repo,
            [
                "log",
                "--no-merges",
                "--no-renames",
                "--unified=0",
                "--no-color",
                f"--max-count={limit}",
                "--format=%x01%H%x1f%at",
                "--",
                path,
            ],
            timeout=max(self.timeout, 120),
            check=False,
        )

    # ------------------------------------------------------------------ refs
    def tags(self, repo: Path | str, limit: int = 8) -> list[RefInfo]:
        output = self.run_text(
            repo,
            [
                "for-each-ref",
                "--sort=-creatordate",
                "--format=%(refname:short)%00%(objectname)%00%(objecttype)%00%(creatordate:unix)",
                "refs/tags",
            ],
            check=False,
        )
        result: list[RefInfo] = []
        for line in output.splitlines():
            fields = line.split("\x00")
            if len(fields) != 4:
                continue
            name, obj, obj_type, ts_raw = fields
            sha = obj
            if obj_type == "tag":
                resolved = self.resolve_ref(repo, name)
                if not resolved:
                    continue
                sha = resolved
            try:
                ts = int(ts_raw or 0)
            except ValueError:
                ts = 0
            result.append(RefInfo(name=name, sha=sha, ts=ts))
            if len(result) >= limit:
                break
        return result

    def branches(self, repo: Path | str, limit: int = 5) -> list[RefInfo]:
        output = self.run_text(
            repo,
            [
                "for-each-ref",
                "--sort=-committerdate",
                "--format=%(refname:short)%00%(objectname)%00%(committerdate:unix)",
                "refs/heads",
            ],
            check=False,
        )
        result: list[RefInfo] = []
        for line in output.splitlines():
            fields = line.split("\x00")
            if len(fields) != 3:
                continue
            name, sha, ts_raw = fields
            try:
                ts = int(ts_raw or 0)
            except ValueError:
                ts = 0
            result.append(RefInfo(name=name, sha=sha, ts=ts))
            if len(result) >= limit:
                break
        return result


def file_extension(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def is_python_path(path: str) -> bool:
    return file_extension(path) in {".py", ".pyi"}


def path_id(path: str) -> str:
    return stable_id("file", path)
