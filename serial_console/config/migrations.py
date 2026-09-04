"""Forward migration of stored configuration documents.

Each migration takes the raw ``dict`` from disk and returns the next schema
version.  Keeping them as pure dict transforms (rather than model methods)
means an old file can always be read, even if the dataclasses have since
changed shape.
"""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Any

from ..core.logging_setup import get_logger
from ..models.settings import SCHEMA_VERSION

_log = get_logger(__name__)

Migration = Callable[[MutableMapping[str, Any]], MutableMapping[str, Any]]


def _migrate_0_to_1(data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Version 0 was the unversioned pre-release layout: a flat button list."""
    if "profiles" not in data and "buttons" in data:
        data["profiles"] = [
            {
                "name": "Default",
                "buttons": data.pop("buttons"),
                "history": data.pop("history", []),
            }
        ]
    data["schema_version"] = 1
    return data


#: Ordered registry: index N migrates version N to N+1.
_MIGRATIONS: dict[int, Migration] = {
    0: _migrate_0_to_1,
}


def migrate(data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Bring ``data`` up to :data:`SCHEMA_VERSION`."""
    try:
        version = int(data.get("schema_version", 0))
    except (TypeError, ValueError):
        version = 0

    if version > SCHEMA_VERSION:
        # A newer build wrote this file. Load it best-effort rather than
        # refusing to start; unknown keys are ignored by the models.
        _log.warning(
            "Configuration schema %s is newer than supported %s; loading best-effort",
            version,
            SCHEMA_VERSION,
        )
        return data

    while version < SCHEMA_VERSION:
        migration = _MIGRATIONS.get(version)
        if migration is None:
            _log.warning("No migration registered from schema %s; stopping", version)
            data["schema_version"] = SCHEMA_VERSION
            break
        _log.info("Migrating configuration schema %s -> %s", version, version + 1)
        data = migration(data)
        version = int(data.get("schema_version", version + 1))
    return data
