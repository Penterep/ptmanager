import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ptmanager.modules.daemon import daemon as daemon_module
from ptmanager.modules.daemon.task_store import TaskStore


def response(status_code, body=None, headers=None):
    mock = Mock(status_code=status_code, headers=headers or {}, text=json.dumps(body) if body is not None else "")
    if body is None:
        mock.json.side_effect = ValueError("no json")
    else:
        mock.json.return_value = body
    return mock


class ResultDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.daemon = daemon_module.Daemon.__new__(daemon_module.Daemon)
        self.daemon.satid = "test-satid"
        self.daemon.task_store = TaskStore(str(Path(self.temp.name, "tasks.json")))
        self.undelivered = TaskStore(str(Path(self.temp.name, daemon_module.UNDELIVERED_RESULTS_FILE)))
        self.task = {"guid": "task", "pid": None, "timeStamp": 1, "status": "finished", "results": {"nodes": [1]}, "message": ""}

    def deliver(self, *responses, now=1000.0):
        self.daemon.task_store.save_tasks([self.task])
        self.daemon.send_to_api = Mock(side_effect=list(responses))
        with patch.object(daemon_module.time, "time", return_value=now), contextlib.redirect_stdout(io.StringIO()):
            self.daemon.send_results_to_server("https://as.invalid/")
        return [call.kwargs["data"] for call in self.daemon.send_to_api.call_args_list]

    def test_delivered_result_is_removed(self):
        sent = self.deliver(response(200, {"success": True}))

        self.assertEqual(sent, [{"guid": "task", "status": "finished", "results": {"nodes": [1]}, "message": "", "satid": "test-satid"}])
        self.assertEqual(self.daemon.task_store.load_tasks(), [])
        self.assertEqual(self.undelivered.load_tasks(), [])

    def test_unreachable_platform_schedules_a_retry_with_backoff(self):
        self.deliver(None, now=1000.0)

        stored, = self.daemon.task_store.load_tasks()
        self.assertEqual(stored["delivery_attempts"], 1)
        self.assertEqual(stored["next_delivery_at"], 1000.0 + daemon_module.BASE_RETRY_DELAY)
        self.assertEqual(self.daemon.task_store.pop_finished_tasks(1001.0), [])
        self.assertEqual(len(self.daemon.task_store.pop_finished_tasks(1000.0 + daemon_module.BASE_RETRY_DELAY)), 1)

    def test_server_errors_and_temporary_refusals_are_retried_without_degrading(self):
        for status_code in (500, 502, 503, 504, 429, 401, 403):
            with self.subTest(status_code=status_code):
                sent = self.deliver(response(status_code, {"message": "busy"}))

                self.assertEqual(len(sent), 1)
                stored, = self.daemon.task_store.load_tasks()
                self.assertEqual(stored["status"], "finished")
                self.assertEqual(stored["results"], {"nodes": [1]})
                self.assertEqual(self.undelivered.load_tasks(), [])

    def test_retry_after_header_sets_the_delay(self):
        self.deliver(response(503, {"message": "busy"}, {"Retry-After": "42"}), now=1000.0)

        stored, = self.daemon.task_store.load_tasks()
        self.assertEqual(stored["next_delivery_at"], 1042.0)

    def test_backoff_doubles_and_is_capped(self):
        self.assertEqual(daemon_module.retry_delay(1, None), 5)
        self.assertEqual(daemon_module.retry_delay(2, None), 10)
        self.assertEqual(daemon_module.retry_delay(4, None), 40)
        self.assertEqual(daemon_module.retry_delay(20, None), daemon_module.MAX_RETRY_DELAY)
        self.assertEqual(daemon_module.retry_delay(1, response(503, None, {"Retry-After": "999999"})), daemon_module.MAX_RETRY_AFTER)
        self.assertEqual(daemon_module.retry_delay(3, response(503, None, {"Retry-After": "soon"})), 20)

    def test_retry_bookkeeping_is_not_sent_to_the_platform(self):
        self.task.update({"delivery_attempts": 3, "next_delivery_at": 0})

        sent, = self.deliver(response(200, {"success": True}))

        self.assertNotIn("delivery_attempts", sent)
        self.assertNotIn("next_delivery_at", sent)

    def test_result_is_set_aside_after_the_last_attempt(self):
        self.task.update({"delivery_attempts": daemon_module.MAX_DELIVERY_ATTEMPTS - 1, "next_delivery_at": 0})

        self.deliver(response(503, {"message": "busy"}))

        self.assertEqual(self.daemon.task_store.load_tasks(), [])
        undelivered, = self.undelivered.load_tasks()
        self.assertEqual(undelivered["guid"], "task")
        self.assertEqual(undelivered["rejected_status_code"], 503)

    def test_results_for_finished_or_unknown_tests_are_not_retried(self):
        for status_code in (409, 404):
            with self.subTest(status_code=status_code):
                self.undelivered.save_tasks([])
                sent = self.deliver(response(status_code, {"message": "Test is not running"}))

                self.assertEqual(len(sent), 1)
                self.assertEqual(self.daemon.task_store.load_tasks(), [])
                undelivered, = self.undelivered.load_tasks()
                self.assertEqual(undelivered["rejected_status_code"], status_code)
                self.assertEqual(undelivered["rejected_reason"], "Test is not running")

    def test_rejected_payload_is_reported_as_failed_once(self):
        invalid = response(422, {"message": "The given data was invalid.", "errors": {"results.nodes.0.key": ["must be a valid UUID."]}})

        sent = self.deliver(invalid, response(200, {"success": True}))

        self.assertEqual(len(sent), 2)
        degraded = sent[1]
        self.assertEqual(degraded["status"], "failed")
        self.assertIsNone(degraded["results"])
        self.assertEqual(degraded["data"], {"nodes": [1]})
        self.assertIn("422", degraded["message"])
        self.assertIn("results.nodes.0.key: must be a valid UUID.", degraded["message"])
        self.assertNotIn("degraded", degraded)
        self.assertEqual(self.daemon.task_store.load_tasks(), [])
        original, = self.undelivered.load_tasks()
        self.assertEqual(original["status"], "finished")
        self.assertEqual(original["results"], {"nodes": [1]})

    def test_oversized_payload_is_reported_without_its_results(self):
        sent = self.deliver(response(413, {"message": "Too many nodes."}), response(200, {"success": True}))

        self.assertIsNone(sent[1]["data"])
        self.assertIn("Too many nodes.", sent[1]["message"])

    def test_rejected_failure_report_does_not_loop(self):
        sent = self.deliver(response(422, {"message": "invalid"}), response(422, {"message": "invalid"}))

        self.assertEqual(len(sent), 2)
        self.assertEqual(self.daemon.task_store.load_tasks(), [])
        self.assertEqual(len(self.undelivered.load_tasks()), 2)

    def test_failure_report_is_retried_when_the_platform_is_unavailable(self):
        self.deliver(response(422, {"message": "invalid"}), response(503, {"message": "busy"}))

        stored, = self.daemon.task_store.load_tasks()
        self.assertEqual(stored["status"], "failed")
        self.assertTrue(stored["degraded"])

        stored["next_delivery_at"] = 0
        self.daemon.task_store.save_tasks([stored])
        self.daemon.send_to_api = Mock(side_effect=[response(422, {"message": "invalid"})])
        with contextlib.redirect_stdout(io.StringIO()):
            self.daemon.send_results_to_server("https://as.invalid/")

        self.assertEqual(self.daemon.send_to_api.call_count, 1)
        self.assertNotIn("degraded", self.daemon.send_to_api.call_args.kwargs["data"])
        self.assertEqual(self.daemon.task_store.load_tasks(), [])

    def test_running_tasks_are_never_sent(self):
        self.task["status"] = "running"

        sent = self.deliver()

        self.assertEqual(sent, [])
        self.assertEqual(len(self.daemon.task_store.load_tasks()), 1)

    def test_requests_use_a_timeout(self):
        self.daemon.target = "https://as.invalid/"
        self.daemon.no_ssl_verify = True
        self.daemon.proxies = {}
        with patch.object(daemon_module.requests, "post", return_value=response(200, {})) as post, \
                contextlib.redirect_stdout(io.StringIO()):
            self.daemon.send_to_api("result", {"guid": "task"})

        self.assertEqual(post.call_args.kwargs["timeout"], daemon_module.REQUEST_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
