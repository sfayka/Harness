from __future__ import annotations

import unittest
from unittest.mock import patch

from modules import reset_live_smoke


class ResetLiveSmokeCredentialTests(unittest.TestCase):
    def test_live_smoke_loads_runtime_managed_secrets_before_clients(self) -> None:
        with patch(
            "modules.reset_live_smoke.load_runtime_managed_secrets_into_environment"
        ) as load_secrets:
            reset_live_smoke._prepare_live_smoke_environment()

        load_secrets.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
