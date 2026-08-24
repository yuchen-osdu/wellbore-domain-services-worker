from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RUNNER_PATH = Path(__file__).parents[1] / "run_containerized_worker.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("run_containerized_worker", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the worker acceptance runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunContainerizedWorkerTest(unittest.TestCase):
    def test_main_runs_both_suites_and_combines_results(self):
        runner = load_runner()
        environment = {
            "INTEGRATION_TESTER_ACCESS_TOKEN": "token",
            "TEST_REPO_ROOT": "/tmp/repository",
            "TEST_RESULTS_DIR": "/tmp/test-reports",
            "WDMS_WORKER_CHECK_CERT": "true",
            "WDMS_WORKER_HOST": "https://example.test/api/wdms-worker",
        }

        with (
            mock.patch.dict(os.environ, environment, clear=True),
            mock.patch.object(runner.os, "chdir") as chdir,
            mock.patch.object(runner.Path, "mkdir") as mkdir,
            mock.patch.object(
                runner.subprocess,
                "run",
                side_effect=[
                    SimpleNamespace(returncode=7),
                    SimpleNamespace(returncode=0),
                ],
            ) as run,
            self.assertRaises(SystemExit) as exit_error,
        ):
            runner.main()

        self.assertEqual(exit_error.exception.code, 7)
        chdir.assert_called_once_with(Path("/tmp/repository").resolve())
        mkdir.assert_called_once_with(parents=True, exist_ok=True)
        self.assertEqual(run.call_count, 2)
        self.assertIn("./tests/service", run.call_args_list[0].args[0])
        security_command = run.call_args_list[1].args[0]
        self.assertIn("./tests/security/test_authorization.py", security_command)
        self.assertIn("https://example.test/api/wdms-worker", security_command)

    def test_main_requires_remote_security_environment_after_local_suite(self):
        runner = load_runner()
        environment = {
            "TEST_REPO_ROOT": "/tmp/repository",
            "TEST_RESULTS_DIR": "/tmp/test-reports",
        }

        with (
            mock.patch.dict(os.environ, environment, clear=True),
            mock.patch.object(runner.os, "chdir"),
            mock.patch.object(runner.Path, "mkdir"),
            mock.patch.object(
                runner.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0),
            ) as run,
            self.assertRaises(SystemExit) as exit_error,
        ):
            runner.main()

        self.assertEqual(exit_error.exception.code, 2)
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
