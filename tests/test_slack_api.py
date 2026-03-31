"""Tests for SlackAPI — Slack Web API wrapper for OpenTree bot runner.

TDD order:
1. test_check_slack_sdk_missing
2. test_check_slack_sdk_present
3. test_init_calls_check
4. test_auth_test
5. test_bot_user_id_after_auth
6. test_bot_user_id_before_auth
7. test_send_message_without_thread
8. test_send_message_with_thread
9. test_send_message_api_error
10. test_update_message_text_only
11. test_update_message_blocks_only
12. test_update_message_both
13. test_get_thread_replies
14. test_get_thread_replies_empty
15. test_get_user_display_name_first_call
16. test_get_user_display_name_cache
17. test_get_user_display_name_api_error
18. test_get_channel_name_first_call
19. test_get_channel_name_cache
20. test_get_channel_name_api_error
21. test_get_team_info
22. test_upload_file
23. test_add_reaction_success
24. test_add_reaction_failure
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers — create a fully mocked WebClient instance used across tests
# ---------------------------------------------------------------------------

def _make_mock_webclient() -> MagicMock:
    """Return a MagicMock configured to act like a slack_sdk.WebClient."""
    client = MagicMock()
    return client


# ---------------------------------------------------------------------------
# Fixture: patch slack_sdk at the module level so SlackAPI can always import
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def mock_slack_sdk():
    """Inject a fake slack_sdk module so tests run without the real package."""
    fake_sdk = MagicMock()
    fake_webclient_cls = MagicMock()
    fake_sdk.WebClient = fake_webclient_cls

    with patch.dict(sys.modules, {"slack_sdk": fake_sdk}):
        yield fake_sdk, fake_webclient_cls


@pytest.fixture()
def api(mock_slack_sdk):
    """Return a SlackAPI instance backed by a mock WebClient."""
    _, fake_webclient_cls = mock_slack_sdk
    mock_client = _make_mock_webclient()
    fake_webclient_cls.return_value = mock_client

    # Import *after* patching so the module sees the fake sdk
    from opentree.runner.slack_api import SlackAPI

    instance = SlackAPI(bot_token="xoxb-fake-token")
    instance._client = mock_client  # expose for test assertions
    return instance


# ---------------------------------------------------------------------------
# 0. test_extract_data helper
# ---------------------------------------------------------------------------

class TestExtractData:
    """_extract_data() robustly extracts a dict from various response types."""

    def test_plain_dict_returns_dict(self, mock_slack_sdk):
        from opentree.runner.slack_api import _extract_data

        d = {"ok": True, "user_id": "U123"}
        assert _extract_data(d) == d

    def test_object_with_data_property_returning_dict(self, mock_slack_sdk):
        from opentree.runner.slack_api import _extract_data

        class FakeResponse:
            @property
            def data(self):
                return {"ok": True, "team": "T1"}

        result = _extract_data(FakeResponse())
        assert result == {"ok": True, "team": "T1"}

    def test_object_with_data_property_returning_non_dict_returns_empty(self, mock_slack_sdk):
        """If .data returns a non-dict (e.g. a string), return empty dict safely."""
        from opentree.runner.slack_api import _extract_data

        class WeirdResponse:
            @property
            def data(self):
                return "not-a-dict"

        result = _extract_data(WeirdResponse())
        assert result == {}

    def test_object_without_data_returns_empty(self, mock_slack_sdk):
        """Object with no .data attribute returns empty dict."""
        from opentree.runner.slack_api import _extract_data

        class NoData:
            pass

        result = _extract_data(NoData())
        assert result == {}

    def test_object_that_fails_dict_returns_empty(self, mock_slack_sdk):
        """Object with no .data and no dict() support returns {}."""
        from opentree.runner.slack_api import _extract_data

        class Opaque:
            pass

        result = _extract_data(Opaque())
        assert result == {}

    def test_empty_dict_returns_empty_dict(self, mock_slack_sdk):
        from opentree.runner.slack_api import _extract_data

        assert _extract_data({}) == {}

    def test_slack_response_like_object(self, mock_slack_sdk):
        """Simulate a real SlackResponse that has .data returning a dict."""
        from opentree.runner.slack_api import _extract_data

        class SlackResponseMock:
            def __init__(self, payload: dict):
                self._payload = payload

            @property
            def data(self) -> dict:
                return self._payload

            def __getitem__(self, key):
                return self._payload[key]

            def __iter__(self):
                return iter(self._payload)

        resp = SlackResponseMock({"ok": True, "user_id": "UBOT", "team_id": "T99"})
        result = _extract_data(resp)
        assert result == {"ok": True, "user_id": "UBOT", "team_id": "T99"}


# ---------------------------------------------------------------------------
# 1. test_check_slack_sdk_missing
# ---------------------------------------------------------------------------

class TestCheckSlackSdkMissing:
    """_check_slack_sdk raises ImportError with a helpful message when slack_sdk absent."""

    def test_raises_import_error_with_message(self):
        # Ensure slack_sdk is NOT in sys.modules
        with patch.dict(sys.modules, {"slack_sdk": None}):
            # Need a fresh import; reload trick or import inside patch
            import importlib
            import opentree.runner.slack_api as mod
            importlib.reload(mod)

            with pytest.raises(ImportError, match="pip install opentree\\[slack\\]"):
                mod._check_slack_sdk()

    def test_slack_api_constructor_raises_when_sdk_missing(self):
        with patch.dict(sys.modules, {"slack_sdk": None}):
            import importlib
            import opentree.runner.slack_api as mod
            importlib.reload(mod)

            with pytest.raises(ImportError):
                mod.SlackAPI(bot_token="xoxb-fake")


# ---------------------------------------------------------------------------
# 2. test_check_slack_sdk_present
# ---------------------------------------------------------------------------

class TestCheckSlackSdkPresent:
    """_check_slack_sdk does not raise when slack_sdk is importable."""

    def test_does_not_raise(self, mock_slack_sdk):
        from opentree.runner.slack_api import _check_slack_sdk
        # Should complete without raising
        _check_slack_sdk()


# ---------------------------------------------------------------------------
# 3. test_init_calls_check
# ---------------------------------------------------------------------------

class TestInit:
    """SlackAPI.__init__ sets up _client, _user_cache, _channel_cache, _bot_user_id."""

    def test_webclient_created_with_token(self, mock_slack_sdk):
        _, fake_webclient_cls = mock_slack_sdk
        from opentree.runner.slack_api import SlackAPI

        SlackAPI(bot_token="xoxb-test-999")

        fake_webclient_cls.assert_called_once_with(token="xoxb-test-999")

    def test_caches_start_empty(self, mock_slack_sdk):
        _, fake_webclient_cls = mock_slack_sdk
        fake_webclient_cls.return_value = MagicMock()
        from opentree.runner.slack_api import SlackAPI

        instance = SlackAPI(bot_token="xoxb-x")

        assert instance._user_cache == {}
        assert instance._channel_cache == {}

    def test_bot_user_id_starts_empty(self, mock_slack_sdk):
        _, fake_webclient_cls = mock_slack_sdk
        fake_webclient_cls.return_value = MagicMock()
        from opentree.runner.slack_api import SlackAPI

        instance = SlackAPI(bot_token="xoxb-x")

        assert instance._bot_user_id == ""


# ---------------------------------------------------------------------------
# 4. test_auth_test
# ---------------------------------------------------------------------------

class TestAuthTest:
    """auth_test() calls WebClient.auth_test() and returns the response dict."""

    def test_returns_api_response(self, api):
        api._client.auth_test.return_value = {
            "ok": True,
            "user_id": "U12345",
            "team": "MyTeam",
            "team_id": "T99999",
        }

        result = api.auth_test()

        assert result["ok"] is True
        assert result["user_id"] == "U12345"
        api._client.auth_test.assert_called_once()

    def test_sets_bot_user_id(self, api):
        api._client.auth_test.return_value = {"ok": True, "user_id": "UBOT001"}

        api.auth_test()

        assert api._bot_user_id == "UBOT001"

    def test_auth_test_error_returns_empty_dict(self, api):
        api._client.auth_test.side_effect = Exception("network error")

        result = api.auth_test()

        assert result == {}


# ---------------------------------------------------------------------------
# 5 & 6. test_bot_user_id_after_auth / test_bot_user_id_before_auth
# ---------------------------------------------------------------------------

class TestBotUserId:
    """bot_user_id property reflects _bot_user_id field."""

    def test_returns_empty_string_before_auth(self, api):
        assert api.bot_user_id == ""

    def test_returns_id_after_auth(self, api):
        api._client.auth_test.return_value = {"ok": True, "user_id": "UABC"}
        api.auth_test()

        assert api.bot_user_id == "UABC"


# ---------------------------------------------------------------------------
# 7 & 8. test_send_message_*
# ---------------------------------------------------------------------------

class TestSendMessage:
    """send_message() posts to chat.postMessage via WebClient."""

    def test_sends_without_thread(self, api):
        api._client.chat_postMessage.return_value = {
            "ok": True,
            "ts": "1234567890.000001",
            "channel": "C001",
        }

        result = api.send_message(channel="C001", text="Hello")

        api._client.chat_postMessage.assert_called_once_with(
            channel="C001",
            text="Hello",
        )
        assert result["ts"] == "1234567890.000001"

    def test_sends_with_thread(self, api):
        api._client.chat_postMessage.return_value = {
            "ok": True,
            "ts": "1234567890.000002",
        }

        api.send_message(channel="C001", text="Reply", thread_ts="1234567890.000001")

        api._client.chat_postMessage.assert_called_once_with(
            channel="C001",
            text="Reply",
            thread_ts="1234567890.000001",
        )

    def test_empty_thread_ts_omitted(self, api):
        """thread_ts='' should not be included in the API call kwargs."""
        api._client.chat_postMessage.return_value = {"ok": True, "ts": "111.000"}

        api.send_message(channel="C001", text="Hi", thread_ts="")

        call_kwargs = api._client.chat_postMessage.call_args.kwargs
        assert "thread_ts" not in call_kwargs


# ---------------------------------------------------------------------------
# 9. test_send_message_api_error
# ---------------------------------------------------------------------------

class TestSendMessageApiError:
    """send_message() logs error and doesn't raise on API exception."""

    def test_returns_empty_dict_on_exception(self, api):
        api._client.chat_postMessage.side_effect = Exception("timeout")

        result = api.send_message(channel="C001", text="Hi")

        assert result == {}

    def test_does_not_raise(self, api):
        api._client.chat_postMessage.side_effect = RuntimeError("connection reset")

        # Must not raise
        api.send_message(channel="C001", text="Hi")


# ---------------------------------------------------------------------------
# 10-12. test_update_message_*
# ---------------------------------------------------------------------------

class TestUpdateMessage:
    """update_message() calls chat_update with various combinations."""

    def test_text_only(self, api):
        api._client.chat_update.return_value = {"ok": True, "ts": "111.001"}

        result = api.update_message(channel="C001", ts="111.001", text="Updated")

        api._client.chat_update.assert_called_once_with(
            channel="C001",
            ts="111.001",
            text="Updated",
        )
        assert result["ok"] is True

    def test_blocks_only(self, api):
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "block"}}]
        api._client.chat_update.return_value = {"ok": True, "ts": "111.002"}

        api.update_message(channel="C001", ts="111.002", blocks=blocks)

        call_kwargs = api._client.chat_update.call_args.kwargs
        assert call_kwargs["blocks"] == blocks

    def test_text_and_blocks(self, api):
        blocks = [{"type": "divider"}]
        api._client.chat_update.return_value = {"ok": True}

        api.update_message(channel="C001", ts="111.003", text="fallback", blocks=blocks)

        call_kwargs = api._client.chat_update.call_args.kwargs
        assert call_kwargs["text"] == "fallback"
        assert call_kwargs["blocks"] == blocks

    def test_api_error_returns_empty_dict(self, api):
        api._client.chat_update.side_effect = Exception("api_error")

        result = api.update_message(channel="C001", ts="111.004", text="x")

        assert result == {}


# ---------------------------------------------------------------------------
# 13 & 14. test_get_thread_replies*
# ---------------------------------------------------------------------------

class TestGetThreadReplies:
    """get_thread_replies() fetches all replies via conversations_replies."""

    def test_returns_messages_list(self, api):
        api._client.conversations_replies.return_value = {
            "ok": True,
            "messages": [
                {"ts": "111.001", "text": "first"},
                {"ts": "111.002", "text": "second"},
            ],
        }

        result = api.get_thread_replies(channel="C001", thread_ts="111.001")

        assert len(result) == 2
        assert result[0]["text"] == "first"
        api._client.conversations_replies.assert_called_once_with(
            channel="C001",
            ts="111.001",
            limit=100,
        )

    def test_returns_empty_list_on_error(self, api):
        api._client.conversations_replies.side_effect = Exception("not_in_channel")

        result = api.get_thread_replies(channel="C001", thread_ts="111.001")

        assert result == []

    def test_custom_limit(self, api):
        api._client.conversations_replies.return_value = {"ok": True, "messages": []}

        api.get_thread_replies(channel="C001", thread_ts="111.001", limit=50)

        api._client.conversations_replies.assert_called_once_with(
            channel="C001",
            ts="111.001",
            limit=50,
        )


# ---------------------------------------------------------------------------
# 15-17. test_get_user_display_name*
# ---------------------------------------------------------------------------

class TestGetUserDisplayName:
    """get_user_display_name() fetches display_name and caches the result."""

    def test_first_call_hits_api(self, api):
        api._client.users_info.return_value = {
            "ok": True,
            "user": {
                "profile": {"display_name": "Alice"},
            },
        }

        name = api.get_user_display_name("U001")

        assert name == "Alice"
        api._client.users_info.assert_called_once_with(user="U001")

    def test_second_call_uses_cache(self, api):
        api._client.users_info.return_value = {
            "ok": True,
            "user": {"profile": {"display_name": "Bob"}},
        }

        api.get_user_display_name("U002")
        api.get_user_display_name("U002")

        # API should only be called once
        assert api._client.users_info.call_count == 1

    def test_returns_empty_string_on_api_error(self, api):
        api._client.users_info.side_effect = Exception("user_not_found")

        name = api.get_user_display_name("U999")

        assert name == ""

    def test_returns_empty_string_when_profile_missing(self, api):
        api._client.users_info.return_value = {
            "ok": True,
            "user": {},
        }

        name = api.get_user_display_name("U003")

        assert name == ""

    def test_different_users_cached_independently(self, api):
        def users_info_side_effect(user):
            return {
                "ok": True,
                "user": {"profile": {"display_name": user + "_name"}},
            }

        api._client.users_info.side_effect = users_info_side_effect

        name_a = api.get_user_display_name("UA")
        name_b = api.get_user_display_name("UB")
        # Second calls — from cache
        name_a2 = api.get_user_display_name("UA")
        name_b2 = api.get_user_display_name("UB")

        assert name_a == "UA_name"
        assert name_b == "UB_name"
        assert name_a == name_a2
        assert name_b == name_b2
        # Each user was fetched once
        assert api._client.users_info.call_count == 2


# ---------------------------------------------------------------------------
# 18-20. test_get_channel_name*
# ---------------------------------------------------------------------------

class TestGetChannelName:
    """get_channel_name() fetches the channel name and caches the result."""

    def test_first_call_hits_api(self, api):
        api._client.conversations_info.return_value = {
            "ok": True,
            "channel": {"name": "general"},
        }

        name = api.get_channel_name("C001")

        assert name == "general"
        api._client.conversations_info.assert_called_once_with(channel="C001")

    def test_second_call_uses_cache(self, api):
        api._client.conversations_info.return_value = {
            "ok": True,
            "channel": {"name": "random"},
        }

        api.get_channel_name("C002")
        api.get_channel_name("C002")

        assert api._client.conversations_info.call_count == 1

    def test_returns_empty_string_on_api_error(self, api):
        api._client.conversations_info.side_effect = Exception("channel_not_found")

        name = api.get_channel_name("C999")

        assert name == ""


# ---------------------------------------------------------------------------
# 21. test_get_team_info
# ---------------------------------------------------------------------------

class TestGetTeamInfo:
    """get_team_info() calls WebClient.team_info() and returns the dict."""

    def test_returns_team_dict(self, api):
        api._client.team_info.return_value = {
            "ok": True,
            "team": {"id": "T001", "name": "Acme Corp"},
        }

        result = api.get_team_info()

        assert result["team"]["name"] == "Acme Corp"
        api._client.team_info.assert_called_once()

    def test_returns_empty_dict_on_error(self, api):
        api._client.team_info.side_effect = Exception("not_authed")

        result = api.get_team_info()

        assert result == {}


# ---------------------------------------------------------------------------
# 22. test_upload_file
# ---------------------------------------------------------------------------

class TestUploadFile:
    """upload_file() calls files_upload_v2 with correct parameters."""

    def test_basic_upload(self, api, tmp_path):
        target = tmp_path / "report.html"
        target.write_text("<html></html>")
        api._client.files_upload_v2.return_value = {"ok": True, "file": {"id": "F001"}}

        result = api.upload_file(channel="C001", file_path=str(target))

        api._client.files_upload_v2.assert_called_once()
        call_kwargs = api._client.files_upload_v2.call_args.kwargs
        assert call_kwargs["channel"] == "C001"
        assert "report.html" in call_kwargs.get("title", str(target))
        assert result["ok"] is True

    def test_upload_with_thread_and_comment(self, api, tmp_path):
        target = tmp_path / "data.csv"
        target.write_text("a,b,c")
        api._client.files_upload_v2.return_value = {"ok": True}

        api.upload_file(
            channel="C001",
            file_path=str(target),
            thread_ts="111.001",
            title="My Data",
            comment="Here you go",
        )

        call_kwargs = api._client.files_upload_v2.call_args.kwargs
        assert call_kwargs.get("thread_ts") == "111.001"
        assert call_kwargs.get("title") == "My Data"
        assert call_kwargs.get("initial_comment") == "Here you go"

    def test_returns_empty_dict_on_error(self, api, tmp_path):
        target = tmp_path / "x.txt"
        target.write_text("x")
        api._client.files_upload_v2.side_effect = Exception("upload_failed")

        result = api.upload_file(channel="C001", file_path=str(target))

        assert result == {}

    def test_returns_empty_dict_for_missing_file(self, api, tmp_path):
        missing = str(tmp_path / "nonexistent.txt")

        result = api.upload_file(channel="C001", file_path=missing)

        assert result == {}
        api._client.files_upload_v2.assert_not_called()


# ---------------------------------------------------------------------------
# 23-24. test_add_reaction_*
# ---------------------------------------------------------------------------

class TestAddReaction:
    """add_reaction() adds an emoji reaction; swallows errors and returns bool."""

    def test_success_returns_true(self, api):
        api._client.reactions_add.return_value = {"ok": True}

        result = api.add_reaction(channel="C001", ts="111.001", emoji="thumbsup")

        assert result is True
        api._client.reactions_add.assert_called_once_with(
            channel="C001",
            timestamp="111.001",
            name="thumbsup",
        )

    def test_api_error_returns_false(self, api):
        api._client.reactions_add.side_effect = Exception("already_reacted")

        result = api.add_reaction(channel="C001", ts="111.001", emoji="thumbsup")

        assert result is False

    def test_does_not_raise_on_error(self, api):
        api._client.reactions_add.side_effect = RuntimeError("network error")

        # Must not propagate
        result = api.add_reaction(channel="C001", ts="111.001", emoji="white_check_mark")

        assert result is False
