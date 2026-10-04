"""In-process registry of loaded Domain Packs."""

from __future__ import annotations

from pathlib import Path

from cairn.domain_packs.loader import load_domain_pack
from cairn.domain_packs.pack import DomainPack, DomainPackError


class DomainPackNotFound(LookupError):
    pass


class DomainPackVersionMismatch(LookupError):
    """The journey is pinned to a pack major version that is not loaded."""


class DomainPackRegistry:
    def __init__(self, packs: list[DomainPack]) -> None:
        self._packs: dict[str, DomainPack] = {}
        for pack in packs:
            if pack.id in self._packs:
                raise DomainPackError(f"duplicate domain pack id '{pack.id}'")
            self._packs[pack.id] = pack

    @classmethod
    def from_directory(cls, root: Path) -> DomainPackRegistry:
        if not root.is_dir():
            raise DomainPackError(f"domain pack directory not found: {root}")
        packs = [
            load_domain_pack(child)
            for child in sorted(root.iterdir())
            if child.is_dir() and (child / "manifest.yaml").exists()
        ]
        return cls(packs)

    def all(self) -> list[DomainPack]:
        return sorted(self._packs.values(), key=lambda p: p.id)

    def get(self, pack_id: str) -> DomainPack:
        try:
            return self._packs[pack_id]
        except KeyError as exc:
            raise DomainPackNotFound(pack_id) from exc

    def resolve_for_journey(self, pack_id: str, pinned_version: str) -> DomainPack:
        """Return the loaded pack if it is semver-compatible (same major) with the pin.

        Decisions always record the *loaded* version, so traceability is preserved even
        when a compatible minor/patch release is deployed mid-journey.
        """
        pack = self.get(pack_id)
        if pack.manifest.major_version != int(pinned_version.split(".")[0]):
            raise DomainPackVersionMismatch(
                f"journey pinned to {pack_id}@{pinned_version}, loaded {pack.version}"
            )
        return pack
