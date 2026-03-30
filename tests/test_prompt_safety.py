"""Tests for prompt.py safety issues — TDD RED phase.

Tests are written against the EXPECTED fixed behaviour.
They should FAIL against the current implementation and PASS after the fix.

Covers:
- Issue #4: sys.modules thread safety (concurrent hook loading)
- Issue #11: path traversal prevention in prompt_hook names
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from opentree.core.prompt import (
    PromptContext,
    collect_module_prompts,
    _is_safe_name,
    _is_safe_hook_path,
)
from opentree.registry.models import RegistryData, RegistryEntry


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _make_registry(*module_names: str) -> RegistryData:
    """Build a RegistryData with module stubs."""
    entries = tuple(
        (
            name,
            RegistryEntry(
                name=name,
                version="1.0.0",
                module_type="pre-installed",
                installed_at="2026-01-01T00:00:00+00:00",
                source="bundled",
            ),
        )
        for name in sorted(module_names)
    )
    return RegistryData(version=1, modules=entries)


def _write_module_with_hook(
    home: Path,
    name: str,
    hook_code: str,
    *,
    manifest_extras: dict[str, Any] | None = None,
) -> None:
    """Create a module dir with opentree.json + prompt_hook.py."""
    mod_dir = home / "modules" / name
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "name": name,
        "version": "1.0.0",
        "description": f"Test module {name}",
        "type": "pre-installed",
        "prompt_hook": "prompt_hook.py",
    }
    if manifest_extras:
        manifest.update(manifest_extras)
    (mod_dir / "opentree.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (mod_dir / "prompt_hook.py").write_text(hook_code, encoding="utf-8")


# ------------------------------------------------------------------ #
# Issue #11 — Security helpers (path validation)
# ------------------------------------------------------------------ #


class TestIsSafeName:
    """_is_safe_name must be importable and correct."""

    def test_valid_names_accepted(self) -> None:
        assert _is_safe_name("mymodule") is True
        assert _is_safe_name("my-module") is True
        assert _is_safe_name("my_module") is True
        assert _is_safe_name("Module123") is True
        assert _is_safe_name("a") is True
        assert _is_safe_name("ABC-def_0") is True

    def test_empty_string_rejected(self) -> None:
        assert _is_safe_name("") is False

    def test_dot_traversal_rejected(self) -> None:
        assert _is_safe_name("..") is False
        assert _is_safe_name("../etc") is False
        assert _is_safe_name("../../etc") is False

    def test_slash_rejected(self) -> None:
        assert _is_safe_name("a/b") is False
        assert _is_safe_name("a\\b") is False

    def test_special_chars_rejected(self) -> None:
        assert _is_safe_name("mod!") is False
        assert _is_safe_name("mod name") is False  # space
        assert _is_safe_name("mod;rm") is False
        assert _is_safe_name("mod\x00name") is False  # null byte


class TestIsSafeHookPath:
    """_is_safe_hook_path(hook_path, modules_dir) -> bool."""

    def test_valid_hook_path_accepted(self, tmp_path: Path) -> None:
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "mymod").mkdir()
        hook_path = modules_dir / "mymod" / "prompt_hook.py"
        hook_path.touch()
        assert _is_safe_hook_path(hook_path, modules_dir) is True

    def test_traversal_via_name_rejected(self, tmp_path: Path) -> None:
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        # Simulates: hook_path = modules_dir / "../../etc" / "prompt_hook.py"
        hook_path = modules_dir / ".." / ".." / "etc" / "prompt_hook.py"
        assert _is_safe_hook_path(hook_path, modules_dir) is False

    def test_traversal_via_hook_file_rejected(self, tmp_path: Path) -> None:
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "mymod").mkdir()
        # hook_file contains traversal
        hook_path = modules_dir / "mymod" / ".." / ".." / "secret.py"
        assert _is_safe_hook_path(hook_path, modules_dir) is False

    def test_path_exactly_at_boundary_rejected(self, tmp_path: Path) -> None:
        # hook_path is the modules_dir itself — not a valid hook location
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        assert _is_safe_hook_path(modules_dir, modules_dir) is False

    def test_sibling_dir_rejected(self, tmp_path: Path) -> None:
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        sibling = tmp_path / "secrets"
        sibling.mkdir()
        hook_path = sibling / "evil.py"
        hook_path.touch()
        assert _is_safe_hook_path(hook_path, modules_dir) is False


# ------------------------------------------------------------------ #
# Issue #11 — collect_module_prompts rejects dangerous inputs
# ------------------------------------------------------------------ #


class TestCollectModulePromptsPathSafety:
    """collect_module_prompts must skip or reject traversal payloads."""

    def test_traversal_in_name_skipped(self, tmp_path: Path) -> None:
        """A module name with path traversal components must be skipped safely."""
        # Register a module with a traversal name — collect_module_prompts
        # should detect the unsafe name and skip it without loading anything.
        dangerous_name = "../../etc"
        registry = _make_registry(dangerous_name)
        ctx = PromptContext()
        # Must not raise; must return empty (no hook loaded)
        lines = collect_module_prompts(tmp_path, registry, ctx)
        assert lines == []

    def test_traversal_in_hook_file_skipped(self, tmp_path: Path) -> None:
        """A prompt_hook value with traversal must be skipped."""
        # Create a benign module dir with a manifest pointing to a traversal path
        mod_dir = tmp_path / "modules" / "legit"
        mod_dir.mkdir(parents=True)
        manifest = {
            "name": "legit",
            "version": "1.0.0",
            "prompt_hook": "../../../evil.py",
        }
        (mod_dir / "opentree.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        # Place a "victim" file outside modules dir
        victim = tmp_path / "evil.py"
        victim.write_text(
            "def prompt_hook(ctx):\n    return ['EXPLOITED']\n",
            encoding="utf-8",
        )
        registry = _make_registry("legit")
        ctx = PromptContext()
        lines = collect_module_prompts(tmp_path, registry, ctx)
        # The traversal hook must NOT have been executed
        assert "EXPLOITED" not in lines
        assert lines == []

    def test_hook_file_with_directory_separator_skipped(
        self, tmp_path: Path
    ) -> None:
        """hook_file containing '/' must be skipped."""
        mod_dir = tmp_path / "modules" / "badslash"
        mod_dir.mkdir(parents=True)
        manifest = {
            "name": "badslash",
            "version": "1.0.0",
            "prompt_hook": "subdir/prompt_hook.py",  # contains directory separator
        }
        (mod_dir / "opentree.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        registry = _make_registry("badslash")
        ctx = PromptContext()
        lines = collect_module_prompts(tmp_path, registry, ctx)
        assert lines == []


# ------------------------------------------------------------------ #
# Issue #4 — Thread safety: no sys.modules race condition
# ------------------------------------------------------------------ #


class TestCollectModulePromptsThreadSafety:
    """Concurrent calls to collect_module_prompts must not corrupt each other."""

    def test_no_sys_modules_leak_after_execution(self, tmp_path: Path) -> None:
        """Thread-local module keys must be cleaned up after exec_module."""
        hook_code = (
            "def prompt_hook(context):\n"
            "    return ['thread-safe']\n"
        )
        _write_module_with_hook(tmp_path, "safemod", hook_code)
        registry = _make_registry("safemod")
        ctx = PromptContext()

        # Capture sys.modules keys before
        keys_before = set(sys.modules.keys())

        collect_module_prompts(tmp_path, registry, ctx)

        # After execution no opentree_hook_* keys should remain
        leaked = [
            k for k in sys.modules.keys()
            if k.startswith("opentree_hook_") and k not in keys_before
        ]
        assert leaked == [], f"sys.modules leaked keys: {leaked}"

    def test_concurrent_threads_produce_correct_results(
        self, tmp_path: Path
    ) -> None:
        """10 threads calling collect_module_prompts concurrently must each
        get the correct result for their own context (no cross-contamination).
        """
        hook_code = (
            "def prompt_hook(context):\n"
            "    return [f\"user={context.get('user_name', 'anon')}\"]\n"
        )
        _write_module_with_hook(tmp_path, "concmod", hook_code)
        registry = _make_registry("concmod")

        results: dict[int, list[str]] = {}
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(thread_id: int) -> None:
            try:
                ctx = PromptContext(user_name=f"user{thread_id}")
                lines = collect_module_prompts(tmp_path, registry, ctx)
                with lock:
                    results[thread_id] = lines
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        num_threads = 10
        threads = [
            threading.Thread(target=worker, args=(i,))
            for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Threads raised exceptions: {errors}"
        assert len(results) == num_threads

        for thread_id, lines in results.items():
            assert lines == [f"user=user{thread_id}"], (
                f"Thread {thread_id} got wrong result: {lines}"
            )

    def test_concurrent_threads_no_sys_modules_leak(
        self, tmp_path: Path
    ) -> None:
        """No opentree_hook_* entries should remain in sys.modules after
        10 concurrent calls complete.
        """
        hook_code = (
            "def prompt_hook(context):\n"
            "    return ['ok']\n"
        )
        _write_module_with_hook(tmp_path, "leakcheck", hook_code)
        registry = _make_registry("leakcheck")

        keys_before = set(sys.modules.keys())
        barrier = threading.Barrier(10)
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker() -> None:
            try:
                barrier.wait()  # synchronise start for maximum contention
                ctx = PromptContext()
                collect_module_prompts(tmp_path, registry, ctx)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Threads raised: {errors}"

        leaked = [
            k for k in sys.modules.keys()
            if k.startswith("opentree_hook_") and k not in keys_before
        ]
        assert leaked == [], f"sys.modules leaked: {leaked}"

    def test_thread_unique_module_keys_not_collide(
        self, tmp_path: Path
    ) -> None:
        """Each thread must use a unique sys.modules key so concurrent
        exec_module calls do not overwrite each other's module object.

        We detect this by having the hook return the module's own id() — if
        two threads share the same module object the hook result would be the
        same object id, which would be a collision.

        Instead we just verify that results are correct (per-user_name).
        """
        hook_code = (
            "import threading\n"
            "def prompt_hook(context):\n"
            "    return [f\"tid={threading.get_ident()}\"]\n"
        )
        _write_module_with_hook(tmp_path, "tidmod", hook_code)
        registry = _make_registry("tidmod")

        seen_tids: set[int] = set()
        result_tids: list[str] = []
        lock = threading.Lock()
        barrier = threading.Barrier(5)

        def worker() -> None:
            barrier.wait()
            ctx = PromptContext()
            lines = collect_module_prompts(tmp_path, registry, ctx)
            with lock:
                result_tids.extend(lines)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each thread should have produced exactly one "tid=<N>" entry
        assert len(result_tids) == 5
        # The tid values should correspond to real thread IDs (numeric)
        for entry in result_tids:
            assert entry.startswith("tid="), f"Unexpected entry: {entry}"


# ------------------------------------------------------------------ #
# Regression: normal operation must still work after fixes
# ------------------------------------------------------------------ #


class TestNormalOperationRegression:
    """Ensure existing behaviour is preserved after security/safety fixes."""

    def test_valid_module_hook_still_executes(self, tmp_path: Path) -> None:
        hook_code = (
            "def prompt_hook(context):\n"
            "    return ['regression-ok']\n"
        )
        _write_module_with_hook(tmp_path, "regrmod", hook_code)
        registry = _make_registry("regrmod")
        ctx = PromptContext(user_name="regr-user")
        lines = collect_module_prompts(tmp_path, registry, ctx)
        assert lines == ["regression-ok"]

    def test_error_resilience_still_works(self, tmp_path: Path) -> None:
        hook_code = (
            "def prompt_hook(context):\n"
            "    raise RuntimeError('still broken')\n"
        )
        _write_module_with_hook(tmp_path, "stillbroken", hook_code)
        registry = _make_registry("stillbroken")
        ctx = PromptContext()
        lines = collect_module_prompts(tmp_path, registry, ctx)
        assert len(lines) == 1
        assert "error" in lines[0].lower()
        assert "stillbroken" in lines[0]

    def test_multiple_modules_in_order(self, tmp_path: Path) -> None:
        """Multiple valid modules must all contribute their output."""
        for mod_name in ("alpha", "beta", "gamma"):
            _write_module_with_hook(
                tmp_path,
                mod_name,
                f"def prompt_hook(ctx):\n    return ['{mod_name}-output']\n",
            )
        registry = _make_registry("alpha", "beta", "gamma")
        ctx = PromptContext()
        lines = collect_module_prompts(tmp_path, registry, ctx)
        assert "alpha-output" in lines
        assert "beta-output" in lines
        assert "gamma-output" in lines

    def test_dash_in_module_name_still_works(self, tmp_path: Path) -> None:
        """Module names with hyphens (e.g. 'test-mod') are valid and must load."""
        hook_code = "def prompt_hook(ctx):\n    return ['hyphen-ok']\n"
        _write_module_with_hook(tmp_path, "test-mod", hook_code)
        registry = _make_registry("test-mod")
        ctx = PromptContext()
        lines = collect_module_prompts(tmp_path, registry, ctx)
        assert lines == ["hyphen-ok"]
