"""Offline checks for autorun.py's decision logic: python -m unittest agent.test_autorun.

Mocks Gmail (_latest_message_id) and the backend call (_accepted_workflow_keys)
so this needs no live credentials or running backend — it only verifies the
watch-and-trigger logic itself: accepted+has-a-trigger-query -> new message ->
exactly one auto run, never a duplicate for the same message, never a run for
something not accepted or with no trigger registered.
"""
import unittest
from unittest.mock import AsyncMock, patch

from agent import autorun, runner


class AutoRunTickTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Isolate the on-disk watermark file per test.
        self._watermark_patch = patch.object(autorun, "WATERMARK_FILE", self._tmp_watermark_path())
        self._watermark_patch.start()
        self.addCleanup(self._watermark_patch.stop)

    def _tmp_watermark_path(self):
        import tempfile
        from pathlib import Path

        return Path(tempfile.mkdtemp()) / "watermarks.json"

    async def test_new_message_starts_exactly_one_auto_run(self):
        with patch.object(autorun, "_accepted_workflow_keys", AsyncMock(return_value={"gmail_to_sheet": "sug-1"})), \
             patch.object(autorun, "_latest_message_id", return_value="msg-123"), \
             patch.object(runner, "is_run_active", return_value=False), \
             patch.object(runner, "start_run") as start_run:
            await autorun._tick()
        start_run.assert_called_once_with("gmail_to_sheet", "sug-1", triggered_by="auto")

    async def test_same_message_does_not_retrigger(self):
        with patch.object(autorun, "_accepted_workflow_keys", AsyncMock(return_value={"gmail_to_sheet": "sug-1"})), \
             patch.object(autorun, "_latest_message_id", return_value="msg-123"), \
             patch.object(runner, "is_run_active", return_value=False), \
             patch.object(runner, "start_run") as start_run:
            await autorun._tick()
            await autorun._tick()
        start_run.assert_called_once()  # second tick saw the same message id and skipped it

    async def test_no_trigger_query_registered_never_runs(self):
        with patch.object(autorun, "_accepted_workflow_keys", AsyncMock(return_value={"book_tennis_court": "sug-2"})), \
             patch.object(runner, "start_run") as start_run:
            await autorun._tick()
        start_run.assert_not_called()

    async def test_run_already_in_progress_skips_this_tick(self):
        with patch.object(autorun, "_accepted_workflow_keys", AsyncMock(return_value={"gmail_to_sheet": "sug-1"})), \
             patch.object(autorun, "_latest_message_id", return_value="msg-123"), \
             patch.object(runner, "is_run_active", return_value=True), \
             patch.object(runner, "start_run") as start_run:
            await autorun._tick()
        start_run.assert_not_called()

    async def test_backend_unreachable_does_not_raise(self):
        with patch.object(autorun, "_accepted_workflow_keys", AsyncMock(return_value={})), \
             patch.object(runner, "start_run") as start_run:
            await autorun._tick()  # must not raise
        start_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
