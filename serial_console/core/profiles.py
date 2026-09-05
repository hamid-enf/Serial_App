"""Profile lifecycle: create, rename, delete, duplicate, import and export."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..models.errors import ValidationError
from ..models.profile import Profile
from ..models.settings import AppConfig

MAX_PROFILES = 200
PROFILE_FILE_VERSION = 1


class ProfileManager:
    """Owns the profile list of an :class:`AppConfig`."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        if not config.profiles:
            starter = Profile.create_starter()
            config.profiles.append(starter)
            config.active_profile_id = starter.id

    # ------------------------------------------------------------------
    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def profiles(self) -> list[Profile]:
        return self._config.profiles

    def __len__(self) -> int:
        return len(self._config.profiles)

    def names(self) -> list[str]:
        return [p.name for p in self._config.profiles]

    def active(self) -> Profile:
        return self._config.active_profile()

    def get(self, profile_id: str) -> Profile:
        for profile in self._config.profiles:
            if profile.id == profile_id:
                return profile
        raise ValidationError("That profile no longer exists.")

    def index_of(self, profile_id: str) -> int:
        for index, profile in enumerate(self._config.profiles):
            if profile.id == profile_id:
                return index
        raise ValidationError("That profile no longer exists.")

    def set_active(self, profile_id: str) -> Profile:
        profile = self.get(profile_id)
        self._config.active_profile_id = profile.id
        return profile

    # ------------------------------------------------------------------
    def create(self, name: str, *, button_count: int = 20, description: str = "") -> Profile:
        """Create an empty profile pre-filled with blank buttons."""
        clean = self._validate_name(name)
        if len(self._config.profiles) >= MAX_PROFILES:
            raise ValidationError(f"You can keep at most {MAX_PROFILES} profiles.")
        profile = Profile.create_default(clean, button_count=button_count)
        profile.description = description
        self._config.profiles.append(profile)
        return profile

    def rename(self, profile_id: str, name: str) -> Profile:
        clean = self._validate_name(name, exclude_id=profile_id)
        profile = self.get(profile_id)
        profile.name = clean
        return profile

    def duplicate(self, profile_id: str, new_name: str | None = None) -> Profile:
        if len(self._config.profiles) >= MAX_PROFILES:
            raise ValidationError(f"You can keep at most {MAX_PROFILES} profiles.")
        source = self.get(profile_id)
        name = new_name or self._unique_name(f"{source.name} copy")
        clone = source.duplicate(self._validate_name(name))
        self._config.profiles.insert(self.index_of(profile_id) + 1, clone)
        return clone

    def delete(self, profile_id: str) -> Profile:
        """Delete a profile. The last remaining profile cannot be deleted."""
        if len(self._config.profiles) <= 1:
            raise ValidationError(
                "At least one profile must exist. Rename or reset this one instead."
            )
        index = self.index_of(profile_id)
        removed = self._config.profiles.pop(index)
        if self._config.active_profile_id == removed.id:
            fallback = self._config.profiles[min(index, len(self._config.profiles) - 1)]
            self._config.active_profile_id = fallback.id
        return removed

    # ------------------------------------------------------------------
    # Import / export
    # ------------------------------------------------------------------
    @staticmethod
    def to_document(profile: Profile) -> dict[str, Any]:
        """Wrap a profile in a self-describing, shareable document."""
        return {
            "kind": "serial-command-console.profile",
            "version": PROFILE_FILE_VERSION,
            "profile": profile.to_dict(),
        }

    def export_to_file(self, profile_id: str, path: str | Path) -> Path:
        profile = self.get(profile_id)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_document(profile), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return target

    @staticmethod
    def parse_document(data: Mapping[str, Any] | Any) -> Profile:
        """Read either a wrapped document or a bare profile object."""
        if not isinstance(data, Mapping):
            raise ValidationError("The selected file is not a valid profile export.")
        payload: Any = data
        if "profile" in data:
            kind = str(data.get("kind") or "")
            if kind and kind != "serial-command-console.profile":
                raise ValidationError(
                    "The selected file is not a Serial Command Console profile."
                )
            payload = data.get("profile")
        if not isinstance(payload, Mapping) or "buttons" not in payload:
            raise ValidationError("The selected file does not contain any command buttons.")
        return Profile.from_dict(payload)

    def import_from_file(self, path: str | Path, *, activate: bool = True) -> Profile:
        source = Path(path)
        try:
            raw = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValidationError(f"The profile file could not be read: {exc.strerror}.") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"The profile file is not valid JSON (line {exc.lineno}, column {exc.colno})."
            ) from exc

        profile = self.parse_document(data)
        # Always re-key on import so importing twice never collides.
        profile.id = Profile().id
        profile.name = self._unique_name(profile.name)
        if len(self._config.profiles) >= MAX_PROFILES:
            raise ValidationError(f"You can keep at most {MAX_PROFILES} profiles.")
        self._config.profiles.append(profile)
        if activate:
            self._config.active_profile_id = profile.id
        return profile

    # ------------------------------------------------------------------
    def _validate_name(self, name: str, *, exclude_id: str | None = None) -> str:
        clean = (name or "").strip()
        if not clean:
            raise ValidationError("Profile name cannot be empty.")
        if len(clean) > 64:
            raise ValidationError("Profile name is too long (maximum 64 characters).")
        for profile in self._config.profiles:
            if profile.id != exclude_id and profile.name.lower() == clean.lower():
                raise ValidationError(f"A profile named “{clean}” already exists.")
        return clean

    def _unique_name(self, base: str) -> str:
        existing = {p.name.lower() for p in self._config.profiles}
        candidate = (base or "Profile").strip()[:64] or "Profile"
        if candidate.lower() not in existing:
            return candidate
        index = 2
        while f"{candidate} {index}".lower() in existing:
            index += 1
        return f"{candidate} {index}"[:64]
