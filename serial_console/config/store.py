"""Atomic, self-healing JSON persistence.

Guarantees
----------
1. **Atomic writes** — the document is written to a temporary file in the same
   directory and then ``os.replace``-d over the target, so a crash or a power
   cut can never leave a truncated ``config.json``.
2. **Rolling backup** — the previous good file is kept as ``config.json.bak``.
3. **Corruption recovery** — an unparsable file is quarantined with a timestamp
   and the backup (or the defaults) is used instead.  Starting the application
   always succeeds.
4. **Debounced saves** — :meth:`ConfigStore.save` is cheap enough to call after
   every edit; ``save_if_dirty`` batches them for the autosave timer.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from ..core.logging_setup import get_logger
from ..models.errors import ConfigError
from ..models.settings import AppConfig
from .migrations import migrate
from .paths import config_file

_log = get_logger(__name__)


class LoadResult:
    """Outcome of :meth:`ConfigStore.load`, including any recovery that ran."""

    __slots__ = ("config", "message", "quarantine_path", "recovered")

    def __init__(
        self,
        config: AppConfig,
        *,
        recovered: bool = False,
        message: str = "",
        quarantine_path: Path | None = None,
    ) -> None:
        self.config = config
        self.recovered = recovered
        self.message = message
        self.quarantine_path = quarantine_path


class ConfigStore:
    """Reads and writes the single :class:`AppConfig` document."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else config_file()
        self._dirty = False
        self._last_saved_payload: str | None = None

    # ------------------------------------------------------------------
    @property
    def path(self) -> Path:
        return self._path

    @property
    def backup_path(self) -> Path:
        return self._path.with_suffix(self._path.suffix + ".bak")

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self) -> None:
        self._dirty = True

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load(self) -> LoadResult:
        """Load the configuration, never raising for a broken file."""
        if not self._path.exists():
            _log.info("No configuration at %s; starting with defaults", self._path)
            return LoadResult(AppConfig.create_default())

        primary = self._try_read(self._path)
        if primary is not None:
            return LoadResult(primary)

        quarantine = self._quarantine(self._path)
        backup = self._try_read(self.backup_path)
        if backup is not None:
            _log.warning("Recovered configuration from backup %s", self.backup_path)
            return LoadResult(
                backup,
                recovered=True,
                message=(
                    "The settings file was damaged and has been restored from the "
                    "automatic backup."
                ),
                quarantine_path=quarantine,
            )

        _log.error("Configuration and backup are both unusable; using defaults")
        return LoadResult(
            AppConfig.create_default(),
            recovered=True,
            message=(
                "The settings file could not be read and has been reset to defaults. "
                "A copy of the damaged file was kept for inspection."
            ),
            quarantine_path=quarantine,
        )

    def _try_read(self, path: Path) -> AppConfig | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            _log.error("Cannot read %s: %s", path, exc)
            return None

        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            _log.error("Invalid JSON in %s: %s", path, exc)
            return None
        except ValueError as exc:  # pragma: no cover - defensive
            _log.error("Unreadable configuration %s: %s", path, exc)
            return None

        if not isinstance(data, dict):
            _log.error("Configuration root in %s is %s, expected object", path, type(data).__name__)
            return None

        try:
            migrated = migrate(dict(data))
            config = AppConfig.from_dict(migrated)
        except Exception:
            _log.exception("Failed to interpret configuration at %s", path)
            return None
        self._last_saved_payload = self._serialise(config)
        return config

    def _quarantine(self, path: Path) -> Path | None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
        try:
            shutil.copy2(path, target)
        except OSError as exc:
            _log.error("Could not quarantine %s: %s", path, exc)
            return None
        _log.warning("Damaged configuration copied to %s", target)
        self._prune_quarantine(path)
        return target

    def _prune_quarantine(self, path: Path, keep: int = 5) -> None:
        """Keep only the newest few quarantined copies."""
        try:
            candidates = sorted(
                path.parent.glob(f"{path.stem}.corrupt-*{path.suffix}"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        for stale in candidates[keep:]:
            try:
                stale.unlink()
            except OSError:
                _log.debug("Could not remove stale quarantine file %s", stale)

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------
    @staticmethod
    def _serialise(config: AppConfig) -> str:
        return json.dumps(config.to_dict(), indent=2, ensure_ascii=False, sort_keys=False)

    def save(self, config: AppConfig, *, force: bool = False) -> Path:
        """Persist ``config`` atomically.

        Raises:
            ConfigError: if the file could not be written; the caller shows a
                mapped, user-friendly message and keeps running.
        """
        payload = self._serialise(config)
        if not force and payload == self._last_saved_payload:
            self._dirty = False
            return self._path

        directory = self._path.parent
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(f"Cannot create settings folder {directory}: {exc}") from exc

        tmp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=directory,
                prefix=self._path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp_name = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())

            if self._path.exists():
                try:
                    shutil.copy2(self._path, self.backup_path)
                except OSError as exc:
                    # A missing backup is not worth failing the save over.
                    _log.warning("Could not refresh backup %s: %s", self.backup_path, exc)

            os.replace(tmp_name, self._path)
            tmp_name = None
        except OSError as exc:
            raise ConfigError(f"Cannot write settings to {self._path}: {exc}") from exc
        finally:
            if tmp_name:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)

        self._last_saved_payload = payload
        self._dirty = False
        _log.debug("Configuration saved to %s (%d bytes)", self._path, len(payload))
        return self._path

    def save_if_dirty(self, config: AppConfig) -> Path | None:
        if not self._dirty:
            return None
        return self.save(config)
