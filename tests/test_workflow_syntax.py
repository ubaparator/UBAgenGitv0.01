import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
HEREDOC_START = re.compile(r"^\s*python3\b.*<<'PY'\s*$")


class WorkflowSyntaxTests(unittest.TestCase):
    def test_all_workflow_yaml_parses(self):
        workflow_dir = ROOT / ".github" / "workflows"
        for path in sorted(workflow_dir.glob("*.yml")):
            with self.subTest(workflow=path.name):
                parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(parsed, dict)

    def test_embedded_python_heredocs_compile(self):
        workflow_dir = ROOT / ".github" / "workflows"
        checked = 0
        for path in sorted(workflow_dir.glob("*.yml")):
            parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
            for job_name, job in (parsed.get("jobs") or {}).items():
                for index, step in enumerate(job.get("steps") or []):
                    run = step.get("run")
                    if not isinstance(run, str):
                        continue
                    lines = run.splitlines()
                    i = 0
                    while i < len(lines):
                        if not HEREDOC_START.match(lines[i]):
                            i += 1
                            continue
                        start = i + 1
                        end = start
                        while end < len(lines) and lines[end].strip() != "PY":
                            end += 1
                        self.assertLess(end, len(lines), f"Unclosed Python heredoc in {path.name}/{job_name}/step {index + 1}")
                        source = "\n".join(lines[start:end]) + "\n"
                        compile(source, f"{path.name}:{job_name}:step-{index + 1}", "exec")
                        checked += 1
                        i = end + 1
        self.assertGreater(checked, 0, "No embedded Python heredocs were validated")

    def test_shell_run_blocks_parse(self):
        import shutil
        import subprocess

        if not shutil.which("bash"):
            self.skipTest("bash is not installed")
        workflow_dir = ROOT / ".github" / "workflows"
        for path in sorted(workflow_dir.glob("*.yml")):
            parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
            for job_name, job in (parsed.get("jobs") or {}).items():
                for index, step in enumerate(job.get("steps") or []):
                    run = step.get("run")
                    if not isinstance(run, str):
                        continue
                    result = subprocess.run(
                        ["bash", "-n"], input=run, text=True, capture_output=True
                    )
                    self.assertEqual(
                        result.returncode, 0,
                        f"Invalid shell in {path.name}/{job_name}/step {index + 1}: {result.stderr}",
                    )


if __name__ == "__main__":
    unittest.main()
