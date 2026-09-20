"""Offline integration checks: python -m unittest agent.workflows.test_email_to_calendar."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock

from agent import runner
from agent.workflows import email_to_calendar as workflow

BODY = """Start: 2026-09-21T14:00:00-04:00
End: 2026-09-21T14:45:00-04:00
Attendees: Alice <alice@example.com>, bob@example.com
"""


class CalendarWorkflowTests(unittest.TestCase):
    def test_extract(self):
        event = workflow.extract_meeting(BODY, "Project sync")
        self.assertEqual(event["summary"], "Project sync")
        self.assertEqual(len(event["attendees"]), 2)
        self.assertEqual(event["end"]["dateTime"], "2026-09-21T14:45:00-04:00")

    def test_named_zone_and_duration(self):
        event = workflow.extract_meeting("Date: September 21, 2026\nTime: 2:00 PM\n"
            "Timezone: America/New_York\nDuration: 45 minutes\nAttendees: a@example.com")
        self.assertEqual(event["start"]["dateTime"], "2026-09-21T14:00:00-04:00")
        self.assertEqual(event["end"]["dateTime"], "2026-09-21T18:45:00+00:00")

    def test_reject_ambiguous_or_invalid_fields(self):
        for body in (BODY.replace("-04:00", ""), BODY.replace("14:45", "13:45"),
                     BODY.replace("bob@example.com", "Bob"), "Let's meet tomorrow",
                     BODY + "Start: 2026-09-22T14:00:00-04:00",
                     "Start: 2026-11-01T01:30:00\nTimezone: America/New_York\n"
                     "Duration: 30 minutes\nAttendees: a@example.com"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                workflow.extract_meeting(body)

    def run_workflow(self, decision="approve", body=BODY, fail=False):
        msg = SimpleNamespace(body=body, snippet="", subject="Sync", id="message-1")
        with patch.object(workflow, "read_gmail", return_value=msg), patch.object(
            workflow, "create_event", return_value={"id": "event-1", "htmlLink": "https://calendar.google.com/event"}
        ) as create:
            if fail:
                create.side_effect = RuntimeError("Calendar unavailable")
            run_id = runner.start_run(workflow.WORKFLOW_KEY, "suggestion-1")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                run = runner.get_run(run_id)
                if run.status != "running":
                    break
                threading.Event().wait(.005)
            if run.status == "needs_approval":
                create.assert_not_called()
                runner.approve_run(run_id, decision)
            runner._RUNS[run_id].thread.join(timeout=3)
            self.assertFalse(runner._RUNS[run_id].thread.is_alive())
            return runner.get_run(run_id), create.call_count

    def test_runner_success_and_registration(self):
        original = runner.WORKFLOWS["gmail_to_sheet"]
        workflow.register()
        self.assertIs(runner.WORKFLOWS["gmail_to_sheet"], original)
        run, calls = self.run_workflow()
        self.assertEqual(calls, 1)
        self.assertEqual(run.status, "done")
        self.assertEqual(run.workflowKey, "email_to_calendar")
        self.assertTrue(all(step.state == "done" for step in run.steps))
        self.assertEqual(run.result["eventId"], "event-1")
        self.assertIn("runId", run.model_dump())

    def test_cancel_and_errors(self):
        for kwargs, label, calls in (({"decision": "cancel"}, "Creating event", 0),
                                    ({"body": "No meeting"}, "Extracting meeting details", 0),
                                    ({"fail": True}, "Creating event", 1)):
            with self.subTest(kwargs=kwargs):
                run, count = self.run_workflow(**kwargs)
                self.assertEqual(run.status, "error")
                self.assertTrue(run.error)
                self.assertEqual(count, calls)
                self.assertEqual(next(s.state for s in run.steps if s.label == label), "error")

    def test_calendar_api_payload(self):
        service = Mock()
        event = workflow.extract_meeting(BODY)
        with patch.object(workflow, "build", return_value=service), patch.object(workflow, "get_credentials"):
            workflow.create_event(event)
        service.events.return_value.insert.assert_called_once_with(
            calendarId=workflow.config.CALENDAR_ID, body=event, sendUpdates="all")

    def test_asgi_entrypoint(self):
        from agent.server import app
        self.assertIs(workflow.app, app)


if __name__ == "__main__":
    unittest.main()
