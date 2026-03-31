"""Tests for Bot lifecycle manager — written FIRST (TDD Red phase).

Tests cover:
  - _load_tokens: success, missing bot token, missing app token,
    missing env file, with comments/blank lines, quoted values
  - start: component init order, auth failure path
  - _setup_signal_handlers: registers SIGTERM and SIGINT
  - _handle_signal: sets shutdown event, stops receiver
  - _shutdown: drains tasks, removes heartbeat file
  - uptime_seconds: computed from start time
  - is_running: reflects running state
  - CLI integration: --mode slack calls Bot.start()
  - CLI integration: --mode interactive calls os.execvp (not Bot)
"""
from __future__ import annotations

import signal
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Mock slack_bolt and slack_sdk before importing anything from opentree.runner
# so the import guards in receiver.py / slack_api.py don't fire.
# ---------------------------------------------------------------------------
_mock_bolt = MagicMock()
_mock_bolt_adapter = MagicMock()
_mock_sdk = MagicMock()
sys.modules.setdefault("slack_bolt", _mock_bolt)
sys.modules.setdefault("slack_bolt.adapter.socket_mode", _mock_bolt_adapter)
sys.modules.setdefault("slack_sdk", _mock_sdk)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_home(tmp_path: Path, *, bot_token: str = "xoxb-test", app_token: str = "xapp-test") -> Path:
    """Create a minimal opentree home with config/.env and config/runner.json."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    env_content = f"SLACK_BOT_TOKEN={bot_token}\nSLACK_APP_TOKEN={app_token}\n"
    (config_dir / ".env").write_text(env_content, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Import Bot after stubs are registered
# ---------------------------------------------------------------------------

from opentree.runner.bot import Bot  # noqa: E402


# ===========================================================================
# _load_tokens tests
# ===========================================================================

class TestLoadTokens:
    def test_load_tokens_success(self, tmp_path):
        home = _make_home(tmp_path)
        bot = Bot(home)
        bot_token, app_token = bot._load_tokens()
        assert bot_token == "xoxb-test"
        assert app_token == "xapp-test"

    def test_load_tokens_missing_env_file(self, tmp_path):
        (tmp_path / "config").mkdir(parents=True, exist_ok=True)
        bot = Bot(tmp_path)
        with pytest.raises(RuntimeError, match=r"\.env"):
            bot._load_tokens()

    def test_load_tokens_missing_bot_token(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / ".env").write_text("SLACK_APP_TOKEN=xapp-test\n", encoding="utf-8")
        bot = Bot(tmp_path)
        with pytest.raises(RuntimeError, match="SLACK_BOT_TOKEN"):
            bot._load_tokens()

    def test_load_tokens_missing_app_token(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / ".env").write_text("SLACK_BOT_TOKEN=xoxb-test\n", encoding="utf-8")
        bot = Bot(tmp_path)
        with pytest.raises(RuntimeError, match="SLACK_APP_TOKEN"):
            bot._load_tokens()

    def test_load_tokens_with_comments_and_blanks(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        env_content = (
            "# OpenTree Bot Configuration\n"
            "\n"
            "SLACK_BOT_TOKEN=xoxb-real\n"
            "# a comment\n"
            "\n"
            "SLACK_APP_TOKEN=xapp-real\n"
        )
        (config_dir / ".env").write_text(env_content, encoding="utf-8")
        bot = Bot(tmp_path)
        bot_token, app_token = bot._load_tokens()
        assert bot_token == "xoxb-real"
        assert app_token == "xapp-real"

    def test_load_tokens_quoted_values(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        env_content = (
            'SLACK_BOT_TOKEN="xoxb-quoted"\n'
            "SLACK_APP_TOKEN='xapp-single'\n"
        )
        (config_dir / ".env").write_text(env_content, encoding="utf-8")
        bot = Bot(tmp_path)
        bot_token, app_token = bot._load_tokens()
        assert bot_token == "xoxb-quoted"
        assert app_token == "xapp-single"

    # --- Placeholder sentinel tests ---

    def test_load_tokens_rejects_bot_token_placeholder_your(self, tmp_path):
        """Placeholder 'xoxb-your-bot-token' must be rejected."""
        home = _make_home(tmp_path, bot_token="xoxb-your-bot-token", app_token="xapp-real")
        bot = Bot(home)
        with pytest.raises(RuntimeError, match="placeholder"):
            bot._load_tokens()

    def test_load_tokens_rejects_app_token_placeholder_your(self, tmp_path):
        """Placeholder 'xapp-your-app-token' must be rejected."""
        home = _make_home(tmp_path, bot_token="xoxb-real", app_token="xapp-your-app-token")
        bot = Bot(home)
        with pytest.raises(RuntimeError, match="placeholder"):
            bot._load_tokens()

    def test_load_tokens_rejects_bot_token_placeholder_xxx(self, tmp_path):
        """Placeholder 'xoxb-xxx...' must be rejected."""
        home = _make_home(tmp_path, bot_token="xoxb-xxx-fake", app_token="xapp-real")
        bot = Bot(home)
        with pytest.raises(RuntimeError, match="placeholder"):
            bot._load_tokens()

    def test_load_tokens_rejects_app_token_placeholder_xxx(self, tmp_path):
        """Placeholder 'xapp-xxx...' must be rejected."""
        home = _make_home(tmp_path, bot_token="xoxb-real", app_token="xapp-xxx-fake")
        bot = Bot(home)
        with pytest.raises(RuntimeError, match="placeholder"):
            bot._load_tokens()

    def test_load_tokens_rejects_generic_your_prefix(self, tmp_path):
        """Placeholder starting with 'your-' must be rejected."""
        home = _make_home(tmp_path, bot_token="your-token-here", app_token="xapp-real")
        bot = Bot(home)
        with pytest.raises(RuntimeError, match="placeholder"):
            bot._load_tokens()

    def test_load_tokens_accepts_real_tokens(self, tmp_path):
        """Real tokens (xoxb-1234..., xapp-5678...) must be accepted."""
        home = _make_home(tmp_path, bot_token="xoxb-1234567890-abcdef", app_token="xapp-1-abc-def")
        bot = Bot(home)
        bot_token, app_token = bot._load_tokens()
        assert bot_token == "xoxb-1234567890-abcdef"
        assert app_token == "xapp-1-abc-def"


# ===========================================================================
# start() sequence tests
# ===========================================================================

class TestStartSequence:
    def test_start_sequence(self, tmp_path):
        """start() must init SlackAPI, call auth_test, init Dispatcher and Receiver in order."""
        home = _make_home(tmp_path)
        bot = Bot(home)

        # We need minimal runner config and registry for Dispatcher to init.
        # Patch all three component classes so no real Slack calls happen.
        mock_slack_api_instance = MagicMock()
        mock_slack_api_instance.auth_test.return_value = {"user_id": "UBOT1"}
        mock_slack_api_instance.bot_user_id = "UBOT1"

        mock_dispatcher_instance = MagicMock()
        mock_dispatcher_instance.task_queue = MagicMock()
        mock_dispatcher_instance.task_queue.wait_for_drain = MagicMock(return_value=True)
        mock_dispatcher_instance.exit_code = 0

        mock_receiver_instance = MagicMock()

        call_order: list[str] = []

        def track_slack_api(*a, **kw):
            call_order.append("SlackAPI")
            return mock_slack_api_instance

        def track_dispatcher(*a, **kw):
            call_order.append("Dispatcher")
            return mock_dispatcher_instance

        def track_receiver(*a, **kw):
            call_order.append("Receiver")
            return mock_receiver_instance

        with (
            patch("opentree.runner.bot.SlackAPI", side_effect=track_slack_api),
            patch("opentree.runner.bot.Dispatcher", side_effect=track_dispatcher),
            patch("opentree.runner.bot.Receiver", side_effect=track_receiver),
        ):
            bot.start()

        assert call_order == ["SlackAPI", "Dispatcher", "Receiver"]
        mock_slack_api_instance.auth_test.assert_called_once()
        mock_receiver_instance.start.assert_called_once()

    def test_start_with_auth_failure(self, tmp_path):
        """start() propagates RuntimeError when auth_test returns empty dict (no user_id)."""
        home = _make_home(tmp_path)
        bot = Bot(home)

        mock_slack_api_instance = MagicMock()
        mock_slack_api_instance.auth_test.return_value = {}  # failure
        mock_slack_api_instance.bot_user_id = ""

        with (
            patch("opentree.runner.bot.SlackAPI", return_value=mock_slack_api_instance),
            patch("opentree.runner.bot.Dispatcher"),
            patch("opentree.runner.bot.Receiver"),
        ):
            with pytest.raises(RuntimeError, match="auth_test"):
                bot.start()

    def test_start_passes_dispatch_to_receiver(self, tmp_path):
        """start() passes dispatcher.dispatch as the dispatch_callback to Receiver."""
        home = _make_home(tmp_path)
        bot = Bot(home)

        mock_slack_api_instance = MagicMock()
        mock_slack_api_instance.auth_test.return_value = {"user_id": "UBOT1"}
        mock_slack_api_instance.bot_user_id = "UBOT1"

        mock_dispatcher_instance = MagicMock()
        mock_dispatcher_instance.task_queue = MagicMock()
        mock_dispatcher_instance.task_queue.wait_for_drain = MagicMock(return_value=True)
        mock_dispatcher_instance.exit_code = 0

        mock_receiver_cls = MagicMock()
        mock_receiver_instance = MagicMock()
        mock_receiver_cls.return_value = mock_receiver_instance

        with (
            patch("opentree.runner.bot.SlackAPI", return_value=mock_slack_api_instance),
            patch("opentree.runner.bot.Dispatcher", return_value=mock_dispatcher_instance),
            patch("opentree.runner.bot.Receiver", mock_receiver_cls),
        ):
            bot.start()

        # Receiver was constructed; check the dispatch_callback argument
        _, kwargs = mock_receiver_cls.call_args
        # It may be positional — handle both
        positional_args = mock_receiver_cls.call_args.args
        all_args = positional_args + tuple(kwargs.values())
        assert mock_dispatcher_instance.dispatch in all_args or kwargs.get("dispatch_callback") == mock_dispatcher_instance.dispatch


# ===========================================================================
# Signal handler tests
# ===========================================================================

class TestSignalHandler:
    def test_setup_signal_handlers_registers_sigterm_and_sigint(self, tmp_path):
        home = _make_home(tmp_path)
        bot = Bot(home)

        with patch("signal.signal") as mock_signal:
            bot._setup_signal_handlers()

        calls = {c.args[0] for c in mock_signal.call_args_list}
        assert signal.SIGTERM in calls
        assert signal.SIGINT in calls

    def test_handle_signal_sets_shutdown_event(self, tmp_path):
        home = _make_home(tmp_path)
        bot = Bot(home)
        assert not bot._shutdown_event.is_set()

        bot._handle_signal(signal.SIGTERM, None)

        assert bot._shutdown_event.is_set()

    def test_handle_signal_stops_receiver(self, tmp_path):
        home = _make_home(tmp_path)
        bot = Bot(home)
        mock_receiver = MagicMock()
        bot._receiver = mock_receiver

        bot._handle_signal(signal.SIGINT, None)

        mock_receiver.stop.assert_called_once()

    def test_handle_signal_no_receiver_does_not_raise(self, tmp_path):
        """_handle_signal must not raise when _receiver is None."""
        home = _make_home(tmp_path)
        bot = Bot(home)
        # _receiver is None by default
        bot._handle_signal(signal.SIGTERM, None)  # should not raise


# ===========================================================================
# _shutdown tests
# ===========================================================================

class TestShutdown:
    def _make_bot_with_components(self, tmp_path):
        home = _make_home(tmp_path)
        bot = Bot(home)

        mock_dispatcher = MagicMock()
        mock_task_queue = MagicMock()
        mock_task_queue.wait_for_drain.return_value = True
        mock_dispatcher.task_queue = mock_task_queue

        bot._dispatcher = mock_dispatcher
        return bot, mock_task_queue

    def test_shutdown_drains_tasks(self, tmp_path):
        bot, mock_task_queue = self._make_bot_with_components(tmp_path)

        bot._shutdown()

        mock_task_queue.wait_for_drain.assert_called_once()

    def test_shutdown_drain_uses_runner_config_timeout(self, tmp_path):
        """_shutdown passes drain_timeout from RunnerConfig to wait_for_drain."""
        bot, mock_task_queue = self._make_bot_with_components(tmp_path)

        # Write a runner.json with a custom drain_timeout
        runner_cfg = tmp_path / "config" / "runner.json"
        runner_cfg.write_text('{"drain_timeout": 45}', encoding="utf-8")

        bot._shutdown()

        call_kwargs = mock_task_queue.wait_for_drain.call_args
        timeout_passed = call_kwargs.kwargs.get("timeout") or call_kwargs.args[0]
        assert timeout_passed == 45

    def test_shutdown_removes_heartbeat_file(self, tmp_path):
        bot, _ = self._make_bot_with_components(tmp_path)

        # Create a heartbeat file to be removed
        heartbeat = tmp_path / "data" / "bot.heartbeat"
        heartbeat.parent.mkdir(parents=True, exist_ok=True)
        heartbeat.write_text("12345", encoding="utf-8")
        bot._heartbeat_path = heartbeat

        bot._shutdown()

        assert not heartbeat.exists()

    def test_shutdown_no_heartbeat_does_not_raise(self, tmp_path):
        """_shutdown must not raise when heartbeat file doesn't exist."""
        bot, _ = self._make_bot_with_components(tmp_path)
        bot._heartbeat_path = tmp_path / "no_such_file.heartbeat"

        bot._shutdown()  # should not raise

    def test_shutdown_no_dispatcher_does_not_raise(self, tmp_path):
        home = _make_home(tmp_path)
        bot = Bot(home)
        # _dispatcher is None
        bot._shutdown()  # should not raise


# ===========================================================================
# uptime_seconds / is_running tests
# ===========================================================================

class TestProperties:
    def test_uptime_seconds_when_not_started(self, tmp_path):
        home = _make_home(tmp_path)
        bot = Bot(home)
        # _start_time is 0.0 — uptime should be 0 or a very large number?
        # Per design: _start_time = 0.0 until start() is called.
        # We document that uptime is meaningless before start, but must not raise.
        result = bot.uptime_seconds
        assert isinstance(result, float)

    def test_uptime_seconds_after_start_time_set(self, tmp_path):
        home = _make_home(tmp_path)
        bot = Bot(home)
        bot._start_time = time.time() - 5.0

        uptime = bot.uptime_seconds
        assert uptime >= 4.9  # allow some tolerance

    def test_is_running_false_when_shutdown_not_set(self, tmp_path):
        home = _make_home(tmp_path)
        bot = Bot(home)
        # shutdown_event not set = running (from the outside perspective)
        # is_running tracks whether start() loop is active via _start_time > 0
        # Per design: is_running == True when _start_time > 0 and shutdown not set
        assert not bot.is_running  # before start()

    def test_is_running_true_after_start_time_set(self, tmp_path):
        home = _make_home(tmp_path)
        bot = Bot(home)
        bot._start_time = time.time()

        assert bot.is_running

    def test_is_running_false_after_shutdown_event_set(self, tmp_path):
        home = _make_home(tmp_path)
        bot = Bot(home)
        bot._start_time = time.time()
        bot._shutdown_event.set()

        assert not bot.is_running


# ===========================================================================
# CLI integration tests
# ===========================================================================

class TestExitCode:
    """Tests for the Bot exit code mechanism (restart vs shutdown)."""

    def test_default_exit_code_is_zero(self, tmp_path):
        """Bot's default exit code is 0 (clean exit)."""
        home = _make_home(tmp_path)
        bot = Bot(home)
        assert bot.exit_code == 0

    def test_exit_code_propagated_from_dispatcher(self, tmp_path):
        """When dispatcher sets exit_code=1, Bot.start() exits with that code."""
        home = _make_home(tmp_path)
        bot = Bot(home)

        mock_slack_api_instance = MagicMock()
        mock_slack_api_instance.auth_test.return_value = {"user_id": "UBOT1"}
        mock_slack_api_instance.bot_user_id = "UBOT1"

        mock_dispatcher_instance = MagicMock()
        mock_dispatcher_instance.task_queue = MagicMock()
        mock_dispatcher_instance.task_queue.wait_for_drain = MagicMock(return_value=True)
        mock_dispatcher_instance.exit_code = 1  # restart requested

        mock_receiver_instance = MagicMock()

        with (
            patch("opentree.runner.bot.SlackAPI", return_value=mock_slack_api_instance),
            patch("opentree.runner.bot.Dispatcher", return_value=mock_dispatcher_instance),
            patch("opentree.runner.bot.Receiver", return_value=mock_receiver_instance),
            pytest.raises(SystemExit) as exc_info,
        ):
            bot.start()

        assert exc_info.value.code == 1

    def test_clean_shutdown_exits_zero(self, tmp_path):
        """Normal shutdown (exit_code=0) does not call sys.exit."""
        home = _make_home(tmp_path)
        bot = Bot(home)

        mock_slack_api_instance = MagicMock()
        mock_slack_api_instance.auth_test.return_value = {"user_id": "UBOT1"}
        mock_slack_api_instance.bot_user_id = "UBOT1"

        mock_dispatcher_instance = MagicMock()
        mock_dispatcher_instance.task_queue = MagicMock()
        mock_dispatcher_instance.task_queue.wait_for_drain = MagicMock(return_value=True)
        mock_dispatcher_instance.exit_code = 0  # clean shutdown

        mock_receiver_instance = MagicMock()

        with (
            patch("opentree.runner.bot.SlackAPI", return_value=mock_slack_api_instance),
            patch("opentree.runner.bot.Dispatcher", return_value=mock_dispatcher_instance),
            patch("opentree.runner.bot.Receiver", return_value=mock_receiver_instance),
        ):
            # Should NOT raise SystemExit
            bot.start()


class TestCliIntegration:
    def test_cli_start_mode_slack_calls_bot_start(self, tmp_path):
        """opentree start --mode slack should instantiate Bot and call start()."""
        from typer.testing import CliRunner
        from opentree.cli.main import app

        mock_bot_instance = MagicMock()
        mock_bot_cls = MagicMock(return_value=mock_bot_instance)

        # Bot is imported lazily inside the function body, so we patch
        # it at the opentree.runner.bot module level which is what the
        # 'from opentree.runner.bot import Bot' resolves to.
        with (
            patch("opentree.cli.init._resolve_home", return_value=tmp_path),
            patch("opentree.runner.bot.Bot", mock_bot_cls),
        ):
            # Patch the lazy import inside start_command so the mock is used
            import opentree.runner.bot as bot_module
            original_bot_cls = bot_module.Bot
            bot_module.Bot = mock_bot_cls  # type: ignore[attr-defined]
            try:
                # Create minimal registry so the not-initialized check passes
                reg_path = tmp_path / "config" / "registry.json"
                reg_path.parent.mkdir(parents=True, exist_ok=True)
                reg_path.write_text('{"version": 1, "modules": []}', encoding="utf-8")

                runner = CliRunner()
                result = runner.invoke(app, ["start", "--mode", "slack"])
            finally:
                bot_module.Bot = original_bot_cls

        mock_bot_cls.assert_called_once_with(tmp_path)
        mock_bot_instance.start.assert_called_once()

    def _setup_interactive_fixtures(self, tmp_path: Path) -> None:
        """Create the minimal files needed for the interactive start path."""
        reg_path = tmp_path / "config" / "registry.json"
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        # Registry.load() needs version=1 and modules as a dict
        reg_path.write_text('{"version": 1, "modules": {}}', encoding="utf-8")

        user_cfg = tmp_path / "config" / "user.json"
        user_cfg.write_text(
            '{"bot_name": "Test", "team_name": "", "admin_channel": "", "admin_description": ""}',
            encoding="utf-8",
        )

    def test_cli_start_mode_interactive_calls_execvp(self, tmp_path):
        """opentree start --mode interactive should call os.execvp, not Bot."""
        from typer.testing import CliRunner
        from opentree.cli.main import app

        import opentree.runner.bot as bot_module

        mock_bot_cls = MagicMock()
        original_bot_cls = bot_module.Bot
        self._setup_interactive_fixtures(tmp_path)

        # Patch os.execvp at the location used by opentree.cli.init and
        # assemble_system_prompt to avoid needing real module files.
        with (
            patch("opentree.cli.init._resolve_home", return_value=tmp_path),
            patch("opentree.cli.init.os") as mock_os,
            patch("opentree.core.prompt.assemble_system_prompt", return_value="sys-prompt"),
        ):
            mock_os.execvp = MagicMock()
            mock_os.environ = {}
            bot_module.Bot = mock_bot_cls  # type: ignore[attr-defined]
            try:
                runner = CliRunner()
                runner.invoke(app, ["start", "--mode", "interactive"])
            finally:
                bot_module.Bot = original_bot_cls

        mock_bot_cls.assert_not_called()
        mock_os.execvp.assert_called_once()

    def test_cli_start_default_mode_is_interactive(self, tmp_path):
        """Default mode (no --mode flag) must use interactive path, not slack Bot."""
        from typer.testing import CliRunner
        from opentree.cli.main import app

        import opentree.runner.bot as bot_module

        mock_bot_cls = MagicMock()
        original_bot_cls = bot_module.Bot
        self._setup_interactive_fixtures(tmp_path)

        with (
            patch("opentree.cli.init._resolve_home", return_value=tmp_path),
            patch("opentree.cli.init.os") as mock_os,
            patch("opentree.core.prompt.assemble_system_prompt", return_value="sys-prompt"),
        ):
            mock_os.execvp = MagicMock()
            mock_os.environ = {}
            bot_module.Bot = mock_bot_cls  # type: ignore[attr-defined]
            try:
                runner = CliRunner()
                runner.invoke(app, ["start"])
            finally:
                bot_module.Bot = original_bot_cls

        mock_bot_cls.assert_not_called()


# ===========================================================================
# Health check integration tests
# ===========================================================================


class TestHealthCheck:
    """Tests for disk health monitoring integration in Bot."""

    def test_health_status_none_before_start(self, tmp_path):
        """health_status is None before start() is called."""
        home = _make_home(tmp_path)
        bot = Bot(home)
        assert bot.health_status is None

    def test_health_check_runs_on_start(self, tmp_path):
        """start() runs an initial health check, populating health_status."""
        home = _make_home(tmp_path)
        # Create data dir so health check has something to inspect
        (home / "data").mkdir(parents=True, exist_ok=True)
        bot = Bot(home)

        mock_slack_api_instance = MagicMock()
        mock_slack_api_instance.auth_test.return_value = {"user_id": "UBOT1"}
        mock_slack_api_instance.bot_user_id = "UBOT1"

        mock_dispatcher_instance = MagicMock()
        mock_dispatcher_instance.task_queue = MagicMock()
        mock_dispatcher_instance.task_queue.wait_for_drain = MagicMock(return_value=True)
        mock_dispatcher_instance.exit_code = 0

        mock_receiver_instance = MagicMock()

        with (
            patch("opentree.runner.bot.SlackAPI", return_value=mock_slack_api_instance),
            patch("opentree.runner.bot.Dispatcher", return_value=mock_dispatcher_instance),
            patch("opentree.runner.bot.Receiver", return_value=mock_receiver_instance),
        ):
            bot.start()

        # After start(), health_status should be populated
        assert bot.health_status is not None
        assert "free_mb" in bot.health_status
        assert "warning" in bot.health_status

    def test_shutdown_cancels_health_timer(self, tmp_path):
        """_shutdown cancels the pending health timer."""
        home = _make_home(tmp_path)
        bot = Bot(home)

        mock_timer = MagicMock()
        bot._health_timer = mock_timer

        mock_dispatcher = MagicMock()
        mock_task_queue = MagicMock()
        mock_task_queue.wait_for_drain.return_value = True
        mock_dispatcher.task_queue = mock_task_queue
        bot._dispatcher = mock_dispatcher

        bot._shutdown()

        mock_timer.cancel.assert_called_once()
