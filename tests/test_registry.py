"""Tests for the Registry CRUD operations.

Covers:
- Load: nonexistent / valid / malformed / wrong version / legacy compat / crash recovery
- Save: creates file / parent dirs / roundtrip / fsync
- Register: new / update existing / empty name / link_method / depends_on
- Unregister: existing / nonexistent
- Query: is_registered true / false / list sorted
- Lock: creation / concurrent access guard
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path

import pytest

from opentree.registry.models import RegistryData, RegistryEntry
from opentree.registry.registry import Registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def registry_path(tmp_path: Path) -> Path:
    """Return a path for registry.json inside a temp directory."""
    return tmp_path / "config" / "registry.json"


@pytest.fixture()
def sample_registry_data() -> RegistryData:
    """A RegistryData with two modules for testing."""
    return RegistryData(
        version=1,
        modules=(
            (
                "core",
                RegistryEntry(
                    name="core",
                    version="1.0.0",
                    module_type="pre-installed",
                    installed_at="2026-03-29T10:00:00+08:00",
                    source="bundled",
                ),
            ),
            (
                "youtube",
                RegistryEntry(
                    name="youtube",
                    version="1.0.0",
                    module_type="optional",
                    installed_at="2026-03-30T14:30:00+08:00",
                    source="https://github.com/opentree-modules/youtube.git",
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Load tests
# ---------------------------------------------------------------------------

class TestLoad:
    """Registry.load() tests."""

    def test_load_nonexistent_returns_empty(self, registry_path: Path) -> None:
        """When registry file does not exist, return empty RegistryData."""
        result = Registry.load(registry_path)

        assert result.version == 1
        assert result.modules == ()

    def test_load_valid_registry(self, registry_path: Path) -> None:
        """Load a pre-written registry file and verify correct RegistryData."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "modules": {
                "core": {
                    "name": "core",
                    "version": "1.0.0",
                    "module_type": "pre-installed",
                    "installed_at": "2026-03-29T10:00:00+08:00",
                    "source": "bundled",
                },
            },
        }
        registry_path.write_text(json.dumps(data), encoding="utf-8")

        result = Registry.load(registry_path)

        assert result.version == 1
        assert len(result.modules) == 1
        entry = result.get("core")
        assert entry is not None
        assert entry.version == "1.0.0"
        assert entry.module_type == "pre-installed"
        assert entry.source == "bundled"

    def test_load_malformed_json_raises(self, registry_path: Path) -> None:
        """Malformed JSON should raise ValueError."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text("{not valid json!!!", encoding="utf-8")

        with pytest.raises(ValueError, match="malformed"):
            Registry.load(registry_path)

    def test_load_wrong_version_raises(self, registry_path: Path) -> None:
        """Unsupported schema version should raise ValueError."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 99, "modules": {}}
        registry_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(ValueError, match="version"):
            Registry.load(registry_path)

    def test_load_missing_entry_field_raises(self, tmp_path: Path) -> None:
        """Loading a registry with missing entry fields raises ValueError."""
        registry_path = tmp_path / "registry.json"
        # Entry missing "version" field
        registry_path.write_text(json.dumps({
            "version": 1,
            "modules": {
                "broken": {
                    "module_type": "pre-installed",
                    "installed_at": "2026-01-01T00:00:00Z",
                    "source": "bundled",
                }
            }
        }), encoding="utf-8")

        with pytest.raises(ValueError, match="missing required field"):
            Registry.load(registry_path)

    def test_load_legacy_registry_without_new_fields(self, registry_path: Path) -> None:
        """Load a legacy registry.json that lacks link_method/depends_on.

        Must apply defaults: link_method='symlink', depends_on=().
        """
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "modules": {
                "core": {
                    "name": "core",
                    "version": "1.0.0",
                    "module_type": "pre-installed",
                    "installed_at": "2026-03-29T10:00:00+08:00",
                    "source": "bundled",
                    # No link_method, no depends_on
                },
            },
        }
        registry_path.write_text(json.dumps(data), encoding="utf-8")

        result = Registry.load(registry_path)
        entry = result.get("core")

        assert entry is not None
        assert entry.link_method == "symlink"
        assert entry.depends_on == ()

    def test_crash_recovery_from_tmp(self, registry_path: Path) -> None:
        """When registry.json is missing but a valid .tmp exists, load recovers."""
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        # Create a valid .tmp file (simulating crash after write, before rename)
        tmp_path = registry_path.with_name(f"{registry_path.stem}.99999.tmp")
        data = {
            "version": 1,
            "modules": {
                "core": {
                    "name": "core",
                    "version": "1.0.0",
                    "module_type": "pre-installed",
                    "installed_at": "2026-03-29T10:00:00+08:00",
                    "source": "bundled",
                },
            },
        }
        tmp_path.write_text(json.dumps(data), encoding="utf-8")

        # registry.json does NOT exist
        assert not registry_path.exists()

        result = Registry.load(registry_path)

        # Should have recovered
        assert registry_path.exists()
        assert result.get("core") is not None
        assert result.get("core").version == "1.0.0"
        # tmp file should be gone (renamed to registry.json)
        assert not tmp_path.exists()


# ---------------------------------------------------------------------------
# Save tests
# ---------------------------------------------------------------------------

class TestSave:
    """Registry.save() tests."""

    def test_save_creates_file(
        self, registry_path: Path, sample_registry_data: RegistryData
    ) -> None:
        """save() should create the registry file with valid JSON."""
        Registry.save(registry_path, sample_registry_data)

        assert registry_path.exists()
        content = json.loads(registry_path.read_text(encoding="utf-8"))
        assert content["version"] == 1
        assert "core" in content["modules"]
        assert "youtube" in content["modules"]

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        """save() should create parent directories if they don't exist."""
        deep_path = tmp_path / "a" / "b" / "c" / "registry.json"
        empty_data = RegistryData(version=1, modules=())

        Registry.save(deep_path, empty_data)

        assert deep_path.exists()

    def test_save_then_load_roundtrip(
        self, registry_path: Path, sample_registry_data: RegistryData
    ) -> None:
        """Data should survive a save-then-load roundtrip."""
        Registry.save(registry_path, sample_registry_data)
        loaded = Registry.load(registry_path)

        assert loaded.version == sample_registry_data.version
        assert loaded.names() == sample_registry_data.names()
        for name in loaded.names():
            original = sample_registry_data.get(name)
            roundtripped = loaded.get(name)
            assert roundtripped is not None
            assert original is not None
            assert roundtripped.name == original.name
            assert roundtripped.version == original.version
            assert roundtripped.module_type == original.module_type
            assert roundtripped.installed_at == original.installed_at
            assert roundtripped.source == original.source

    def test_save_with_fsync(
        self, registry_path: Path, sample_registry_data: RegistryData
    ) -> None:
        """save() produces a valid file with correct content (fsync behavior)."""
        Registry.save(registry_path, sample_registry_data)

        assert registry_path.exists()
        content = json.loads(registry_path.read_text(encoding="utf-8"))
        assert content["version"] == 1
        assert "core" in content["modules"]
        # No leftover .tmp files
        tmp_files = list(registry_path.parent.glob("*.tmp"))
        assert tmp_files == []

    def test_save_load_roundtrip_with_new_fields(self, registry_path: Path) -> None:
        """link_method and depends_on survive a save-then-load roundtrip."""
        data = RegistryData(
            version=1,
            modules=(
                (
                    "slack",
                    RegistryEntry(
                        name="slack",
                        version="1.0.0",
                        module_type="pre-installed",
                        installed_at="2026-03-29T10:00:00+08:00",
                        source="bundled",
                        link_method="copy",
                        depends_on=("core", "memory"),
                    ),
                ),
            ),
        )

        Registry.save(registry_path, data)
        loaded = Registry.load(registry_path)

        entry = loaded.get("slack")
        assert entry is not None
        assert entry.link_method == "copy"
        assert entry.depends_on == ("core", "memory")


# ---------------------------------------------------------------------------
# Register tests
# ---------------------------------------------------------------------------

class TestRegister:
    """Registry.register() tests."""

    def test_register_new_module(self) -> None:
        """Registering a new module returns new RegistryData with the module added.

        The original RegistryData must remain unchanged (immutability).
        """
        original = RegistryData(version=1, modules=())

        updated = Registry.register(
            original,
            name="slack",
            version="1.0.0",
            module_type="pre-installed",
            source="bundled",
        )

        # Original unchanged
        assert original.modules == ()
        # Updated has the new module
        assert len(updated.modules) == 1
        entry = updated.get("slack")
        assert entry is not None
        assert entry.name == "slack"
        assert entry.version == "1.0.0"
        assert entry.module_type == "pre-installed"
        assert entry.source == "bundled"
        assert entry.installed_at != ""  # auto-generated

    def test_register_update_existing(self, sample_registry_data: RegistryData) -> None:
        """Re-registering an existing module should update its version."""
        updated = Registry.register(
            sample_registry_data,
            name="core",
            version="2.0.0",
            module_type="pre-installed",
            source="bundled",
        )

        entry = updated.get("core")
        assert entry is not None
        assert entry.version == "2.0.0"
        # Module count should stay the same (update, not duplicate)
        assert len(updated.modules) == len(sample_registry_data.modules)

    def test_register_empty_name_raises(self) -> None:
        """Registering with an empty name should raise ValueError."""
        data = RegistryData(version=1, modules=())

        with pytest.raises(ValueError, match="name"):
            Registry.register(
                data,
                name="",
                version="1.0.0",
                module_type="optional",
            )

    def test_register_with_link_method(self) -> None:
        """Registering with link_method='copy' stores the value."""
        data = RegistryData(version=1, modules=())

        updated = Registry.register(
            data,
            name="slack",
            version="1.0.0",
            module_type="pre-installed",
            link_method="copy",
        )

        entry = updated.get("slack")
        assert entry is not None
        assert entry.link_method == "copy"

    def test_register_with_depends_on(self) -> None:
        """Registering with depends_on=('core',) stores the dependency tuple."""
        data = RegistryData(version=1, modules=())

        updated = Registry.register(
            data,
            name="memory",
            version="1.0.0",
            module_type="pre-installed",
            depends_on=("core",),
        )

        entry = updated.get("memory")
        assert entry is not None
        assert entry.depends_on == ("core",)

    def test_register_default_link_method(self) -> None:
        """Default link_method is 'symlink' when not specified."""
        data = RegistryData(version=1, modules=())

        updated = Registry.register(
            data,
            name="core",
            version="1.0.0",
            module_type="pre-installed",
        )

        entry = updated.get("core")
        assert entry is not None
        assert entry.link_method == "symlink"
        assert entry.depends_on == ()


# ---------------------------------------------------------------------------
# Unregister tests
# ---------------------------------------------------------------------------

class TestUnregister:
    """Registry.unregister() tests."""

    def test_unregister_existing(self, sample_registry_data: RegistryData) -> None:
        """Unregistering an existing module returns new RegistryData without it."""
        updated = Registry.unregister(sample_registry_data, name="youtube")

        assert updated.get("youtube") is None
        assert updated.get("core") is not None
        assert len(updated.modules) == len(sample_registry_data.modules) - 1
        # Original unchanged
        assert sample_registry_data.get("youtube") is not None

    def test_unregister_nonexistent_raises(
        self, sample_registry_data: RegistryData
    ) -> None:
        """Unregistering an unknown module should raise KeyError."""
        with pytest.raises(KeyError, match="not-installed"):
            Registry.unregister(sample_registry_data, name="not-installed")


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------

class TestQuery:
    """Registry query method tests."""

    def test_is_registered_true(self, sample_registry_data: RegistryData) -> None:
        """is_registered returns True for a registered module."""
        assert Registry.is_registered(sample_registry_data, "core") is True

    def test_is_registered_false(self, sample_registry_data: RegistryData) -> None:
        """is_registered returns False for an unregistered module."""
        assert Registry.is_registered(sample_registry_data, "nonexistent") is False

    def test_list_modules_sorted(self) -> None:
        """list_modules returns a sorted tuple even if registered in random order."""
        data = RegistryData(version=1, modules=())

        # Register in non-alphabetical order
        data = Registry.register(data, name="zebra", version="1.0.0", module_type="optional")
        data = Registry.register(data, name="alpha", version="1.0.0", module_type="optional")
        data = Registry.register(data, name="middle", version="1.0.0", module_type="optional")

        result = Registry.list_modules(data)

        assert result == ("alpha", "middle", "zebra")


# ---------------------------------------------------------------------------
# Lock tests
# ---------------------------------------------------------------------------

class TestLock:
    """Registry.lock() context manager tests."""

    @staticmethod
    def _lock_path_for(registry_path: Path) -> Path:
        """Compute the /tmp/ lock path matching Registry.lock() logic."""
        path_hash = hashlib.md5(str(registry_path).encode()).hexdigest()[:16]
        return Path(f"/tmp/opentree-registry-{path_hash}.lock")

    def test_lock_context_manager(self, registry_path: Path) -> None:
        """lock() creates a .lock file and the body executes normally."""
        lock_path = self._lock_path_for(registry_path)

        with Registry.lock(registry_path):
            # Lock file should exist while inside the context
            assert lock_path.exists()

        # After exit, lock file still exists on disk (it's just unlocked)
        assert lock_path.exists()

    def test_lock_already_held(self, registry_path: Path) -> None:
        """Attempting to acquire a held lock raises TimeoutError."""
        lock_path = self._lock_path_for(registry_path)

        # Hold the lock externally
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(TimeoutError, match="Another opentree operation"):
                with Registry.lock(registry_path):
                    pass  # Should never reach here
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
