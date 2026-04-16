from __future__ import annotations

import io
import unittest
from unittest.mock import patch
from urllib import error

from modules.reset.github_verifier import GitHubRestResetClient


def _http_error(code: int) -> error.HTTPError:
    return error.HTTPError(
        url="https://api.github.com/repos/sfayka/HARNESS-DRYRUN/commits/deadbeef",
        code=code,
        msg=f"HTTP {code}",
        hdrs=None,
        fp=io.BytesIO(b"{}"),
    )


class GitHubRestResetClientTests(unittest.TestCase):
    @patch("modules.reset.github_verifier.request.urlopen")
    def test_commit_exists_treats_http_422_as_missing_commit(self, mocked_urlopen) -> None:
        mocked_urlopen.side_effect = _http_error(422)

        client = GitHubRestResetClient(token="github-test-token")

        self.assertFalse(client.commit_exists("sfayka", "HARNESS-DRYRUN", "0" * 40))


if __name__ == "__main__":
    unittest.main()
