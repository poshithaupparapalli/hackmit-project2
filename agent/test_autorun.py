"""Offline checks for autorun.py's decision logic: python -m unittest agent.test_autorun.

Mocks Gmail (_latest_message_id) and the backend call (_accepted_workflows)
so this needs no live credentials or running backend. Covers both runMode
paths: "auto" -> exactly one runner.start_run call per new message, never a
duplicate for the same message; "ask" -> exactly one pending.PendingTrigger
instead, never a run, and never a second prompt while the first is
unanswered. Also: never a run/prompt for something not accepted or with no
trigger registered.
"""
import unittest
from unittest.mock import AsyncMock, patch

from agent import autorun, pending, runner


def _accepted(workflow_key: str, suggestion_id: str = "sug-1", title: str = "Test suggestion", run_mode: str = "auto") -> dict:
    return {workflow_key: {"suggestionId": suggestion_id, "title": title, "runMode": run_mode}}


class AutoRunTickTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Isolate the on-disk watermark file and the in-memory pending store per test.
        self._watermark_patch = patch.object(autorun, "WATERMARK_FILE", self._tmp_watermark_path())
        self._watermark_patch.start()
        self.addCleanup(self._watermark_patch.stop)
        self._pending_patch = patch.dict(pending._PENDING, clear=True)
        self._pending_patch.start()
        self.addCleanup(self._pending_patch.stop)

    def _tmp_watermark_path(self):
        import tempfile
        from pathlib import Path

        return Path(tempfile.mkdtemp()) / "watermarks.json"

    async def test_new_message_starts_exactly_one_auto_run(self):
        with patch.object(autorun, "_accepted_workflows", AsyncMock(return_value=_accepted("gmail_to_sheet", run_mode="auto"))), \
             patch.object(autorun, "_latest_message_id", return_value="msg-123"), \
             patch.object(runner, "is_run_active", return_value=False), \
             patch.object(runner, "start_run") as start_run:
            await autorun._tick()
        start_run.assert_called_once_with("gmail_to_sheet", "sug-1", triggered_by="auto")
        self.assertEqual(pending.list_pending(), [])

    async def test_same_message_does_not_retrigger(self):
        with patch.object(autorun, "_accepted_workflows", AsyncMock(return_value=_accepted("gmail_to_sheet", run_mode="auto"))), \
             patch.object(autorun, "_latest_message_id", return_value="msg-123"), \
             patch.object(runner, "is_run_active", return_value=False), \
             patch.object(runner, "start_run") as start_run:
            await autorun._tick()
            await autorun._tick()
        start_run.assert_called_once()  # second tick saw the same message id and skipped it

    async def test_no_trigger_query_registered_never_runs(self):
        with patch.object(autorun, "_accepted_workflows", AsyncMock(return_value=_accepted("book_tennis_court"))), \
             patch.object(runner, "start_run") as start_run:
            await autorun._tick()
        start_run.assert_not_called()
        self.assertEqual(pending.list_pending(), [])

    async def test_run_already_in_progress_skips_this_tick(self):
        with patch.object(autorun, "_accepted_workflows", AsyncMock(return_value=_accepted("gmail_to_sheet", run_mode="auto"))), \
             patch.object(autorun, "_latest_message_id", return_value="msg-123"), \
             patch.object(runner, "is_run_active", return_value=True), \
             patch.object(runner, "start_run") as start_run:
            await autorun._tick()
        start_run.assert_not_called()

    async def test_backend_unreachable_does_not_raise(self):
        with patch.object(autorun, "_accepted_workflows", AsyncMock(return_value={})), \
             patch.object(runner, "start_run") as start_run:
            await autorun._tick()  # must not raise
        start_run.assert_not_called()

    async def test_ask_mode_creates_pending_trigger_not_a_run(self):
        with patch.object(autorun, "_accepted_workflows", AsyncMock(return_value=_accepted("gmail_to_sheet", title="Log receipts", run_mode="ask"))), \
             patch.object(autorun, "_latest_message_id", return_value="msg-123"), \
             patch.object(runner, "is_run_active", return_value=False), \
             patch.object(runner, "start_run") as start_run:
            await autorun._tick()
        start_run.assert_not_called()
        prompts = pending.list_pending()
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0].workflowKey, "gmail_to_sheet")
        self.assertEqual(prompts[0].suggestionId, "sug-1")

    async def test_ask_mode_does_not_duplicate_pending_trigger(self):
        with patch.object(autorun, "_accepted_workflows", AsyncMock(return_value=_accepted("gmail_to_sheet", run_mode="ask"))), \
             patch.object(autorun, "_latest_message_id", return_value="msg-123"), \
             patch.object(runner, "is_run_active", return_value=False):
            await autorun._tick()
            await autorun._tick()  # still unanswered — must not add a second prompt
        self.assertEqual(len(pending.list_pending()), 1)


class PendingTriggerStoreTests(unittest.TestCase):
    def setUp(self):
        self._pending_patch = patch.dict(pending._PENDING, clear=True)
        self._pending_patch.start()
        self.addCleanup(self._pending_patch.stop)

    def test_resolve_removes_and_returns(self):
        created = pending.create("gmail_to_sheet", "sug-1", title="Run?", description="desc")
        self.assertTrue(pending.has_pending_for("gmail_to_sheet"))
        resolved = pending.resolve(created.id)
        self.assertEqual(resolved.id, created.id)
        self.assertFalse(pending.has_pending_for("gmail_to_sheet"))
        self.assertIsNone(pending.resolve(created.id))  # already resolved


if __name__ == "__main__":
    unittest.main()
