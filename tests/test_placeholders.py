import contextlib
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from ptmanager import ptmanager as cli
from ptmanager.modules.daemon import daemon as daemon_module
from ptmanager.modules.daemon.task_store import TaskStore
from ptmanager.modules.placeholders import expand_command


class PlaceholderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = cli.Config(self.temp.name)
        self.settings = {
            "mail": {"server": "imap.seznam.cz", "login": "tester", "password": "pa ss$();"},
            "www": {"url": "https://www.tester.com/colaborator"}, "interface": "eth1",
        }

    def invoke(self, *arguments):
        with patch.object(cli, "Config", return_value=self.config), \
                patch.object(sys, "argv", ["ptmanager", *arguments]), \
                patch.object(cli.ptprinthelper, "print_banner"), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            cli.main()
        return output.getvalue()

    def test_fixed_switches_overwrite_only_requested_settings(self):
        self.config.set_satid("original")
        output = self.invoke("--set-mail", "imap.seznam.cz", "tester", "pa ss$();",
                             "--set-www", self.settings["www"]["url"], "--set-interface", "eth1")
        self.assertEqual(self.config.get_placeholders(), self.settings)
        self.assertNotIn("pa ss$();", output)
        self.invoke("--set-interface", "eth2")
        self.assertEqual(self.config.get_placeholders(), {**self.settings, "interface": "eth2"})
        self.assertEqual(self.config.get_satid(), "original")
        self.assertEqual(Path(self.temp.name, "config.json").stat().st_mode & 0o777, 0o600)

    def test_init_preserves_settings_and_resets_projects(self):
        self.config.set_placeholders(self.settings)
        self.config.set_satid("original")
        self.config.add_project({"AS-ID": "project"})
        config_module = importlib.import_module(self.config.__class__.__module__)
        with patch.object(config_module, "prompt_confirmation", return_value=True):
            self.invoke("--init")
        self.assertEqual(self.config.get_placeholders(), self.settings)
        self.assertEqual(self.config.get_projects(), [])
        self.assertNotEqual(self.config.get_satid(), "original")

    def test_stale_project_config_preserves_new_settings(self):
        other = cli.Config(self.temp.name)
        other.set_placeholders(self.settings)
        self.config.add_project({"AS-ID": "project"})
        self.assertEqual(self.config.get_placeholders(), self.settings)

    def make_daemon(self):
        daemon = daemon_module.Daemon.__new__(daemon_module.Daemon)
        daemon.config = self.config
        daemon.task_store = TaskStore(str(Path(self.temp.name, "tasks.json")))
        daemon.free_threads = []
        return daemon

    def test_expanded_arguments_reach_actual_process_and_use_current_settings(self):
        daemon = self.make_daemon()
        other = cli.Config(self.temp.name)
        other.set_placeholders(self.settings)
        script = 'import json,sys; print(json.dumps({"status":"finished","results":{"argv":sys.argv[1:]}}))'
        script_path = Path(self.temp.name, "echo_args.py")
        script_path.write_text(script)
        task = {"guid": "task", "command": " ".join([
            sys.executable, str(script_path), "[[mail]]", "[[www]]", "[[interface]]",
        ])}
        original = task["command"]
        daemon.process_task(task, 0)
        record, = daemon.task_store.load_tasks()
        self.assertEqual(record["status"], "finished")
        self.assertEqual(record["results"]["argv"], [
            "--testmail-server", "imap.seznam.cz", "--testmail-login", "tester",
            "--testmail-password", "pa ss$();", "--testwww-url", self.settings["www"]["url"],
            "--interface", "eth1",
        ])
        self.assertEqual(task["command"], original)
        self.assertEqual(daemon.free_threads, [0])

    def test_missing_and_unknown_placeholders_report_error_and_release_worker(self):
        for token in ("[[mail]]", "[[unknown]]"):
            with self.subTest(token=token):
                daemon = self.make_daemon()
                daemon.task_store.save_tasks([])
                with patch.object(daemon_module.subprocess, "Popen") as start:
                    daemon.process_task({"guid": "task", "command": "ptfoo " + token}, 0)
                start.assert_not_called()
                record, = daemon.task_store.load_tasks()
                self.assertEqual(record["status"], "error")
                self.assertTrue(record["message"])
                self.assertEqual(daemon.free_threads, [0])

    def test_missing_required_values_send_error_and_configuration_command_to_as(self):
        cases = (
            ("mail", {}, "mail.server", "ptmanager --set-mail <server> <login> <password>"),
            ("mail", {"mail": {"server": "server", "login": "login"}}, "mail.password",
             "ptmanager --set-mail <server> <login> <password>"),
            ("www", {}, "www.url", "ptmanager --set-www <url>"),
            ("www", {"www": {"url": " "}}, "www.url", "ptmanager --set-www <url>"),
            ("interface", {}, "interface", "ptmanager --set-interface <name>"),
            ("interface", {"interface": ""}, "interface", "ptmanager --set-interface <name>"),
        )
        for name, settings, missing_setting, command in cases:
            with self.subTest(name=name, settings=settings):
                daemon = self.make_daemon()
                daemon.task_store.save_tasks([])
                daemon.satid = "test-satid"
                daemon.send_to_api = Mock(return_value=Mock(status_code=200))
                with patch.object(self.config, "get_placeholders", return_value=settings):
                    with patch.object(daemon_module.subprocess, "Popen") as start:
                        daemon.process_task({"guid": "missing-value", "command": f"ptfoo [[{name}]]"}, 0)

                start.assert_not_called()
                self.assertEqual(daemon.free_threads, [0])
                with contextlib.redirect_stdout(io.StringIO()):
                    daemon.send_results_to_server("https://as.invalid/")
                daemon.send_to_api.assert_called_once()
                call = daemon.send_to_api.call_args.kwargs
                self.assertEqual(call["end_point"], "result")
                self.assertEqual(call["data"], {
                    "guid": "missing-value", "satid": "test-satid", "status": "error", "results": {},
                    "message": f"SAT nemá nakonfigurovány vyžadované hodnoty ({missing_setting}). "
                               f"Pro konfiguraci použij na SAT příkaz: {command}",
                })
                self.assertEqual(daemon.task_store.load_tasks(), [])

    def test_missing_value_does_not_expose_configured_mail_password(self):
        secret = "not-for-the-error-message"
        self.config.set_placeholders({"mail": {"server": "server", "login": "tester", "password": secret}})
        daemon = self.make_daemon()
        with patch.object(self.config, "get_placeholders", return_value={"mail": {"password": secret}}):
            daemon.process_task({"guid": "task", "command": "ptfoo [[mail]]"}, 0)
        record, = daemon.task_store.load_tasks()
        self.assertEqual(record["status"], "error")
        self.assertNotIn(secret, record["message"])
        self.assertIn("ptmanager --set-mail", record["message"])

    def test_original_argument_parsing_is_preserved(self):
        for command in (r"ptfoo --regex \d+", "ptfoo --label O'Reilly", 'ptfoo --label "two words"'):
            with self.subTest(command=command):
                self.assertEqual(expand_command(command, {}), command.split())
                self.assertEqual(expand_command(command + " [[interface]]", {"interface": "eth1"}),
                                 command.split() + ["--interface", "eth1"])

    def test_invalid_cli_input_does_not_change_config(self):
        before = Path(self.temp.name, "config.json").read_bytes()
        for arguments in (("--set-mail", "server", "login"), ("--set-interface", ""),
                          ("--set-www", "https://example.com", "--init")):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit):
                self.invoke(*arguments)
            self.assertEqual(Path(self.temp.name, "config.json").read_bytes(), before)

    def test_launch_failure_records_error_and_releases_worker(self):
        daemon = self.make_daemon()
        with patch.object(daemon_module.subprocess, "Popen", side_effect=FileNotFoundError("secret")):
            daemon.process_task({"guid": "task", "command": "missing-tool"}, 0)
        record, = daemon.task_store.load_tasks()
        self.assertEqual(record["status"], "error")
        self.assertIsNone(record["pid"])
        self.assertNotIn("secret", record["message"])
        self.assertEqual(daemon.free_threads, [0])

    def test_non_object_json_records_error_and_releases_worker(self):
        for output in ("[]", "null"):
            with self.subTest(output=output):
                daemon = self.make_daemon()
                daemon.task_store.save_tasks([])
                script_path = Path(self.temp.name, "result.py")
                script_path.write_text(f"print({output!r})")
                command = " ".join([sys.executable, str(script_path)])
                daemon.process_task({"guid": "task", "command": command}, 0)
                record, = daemon.task_store.load_tasks()
                self.assertEqual(record["status"], "error")
                self.assertIsNone(record["pid"])
                self.assertEqual(daemon.free_threads, [0])
