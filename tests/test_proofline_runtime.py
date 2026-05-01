from __future__ import annotations

import subprocess
import sys
import unittest


class ProoflineRuntimeEntrypointTests(unittest.TestCase):
    def test_module_entrypoint_delegates_to_local_runtime_cli(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "modules.proofline_runtime", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: proofline", result.stdout)
        self.assertIn("Control the local Proofline runtime.", result.stdout)
        self.assertIn("Run the local Proofline API", result.stdout)
        self.assertIn("Manage runtime-managed Proofline secrets", result.stdout)
        self.assertIn("status", result.stdout)


if __name__ == "__main__":
    unittest.main()
