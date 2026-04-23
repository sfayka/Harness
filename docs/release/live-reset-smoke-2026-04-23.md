# Live Reset Smoke Proof: 2026-04-23

This proof records the gated end-to-end reset verifier smoke against real Linear and GitHub dry-run targets.

Command:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 HARNESS_RESET_POLL_SECONDS=0 python3 -m unittest tests.test_reset_live_smoke -v
```

Result:

```text
Ran 1 test in 25.970s

OK
```

## Environment

- Linear project: `HARNESS-DRYRUN`
- GitHub repository: `sfayka/HARNESS-DRYRUN`
- Base branch: `main`
- Local generated store: `.harness-live-reset-smoke/`

The local generated store is ignored because the durable proof is the live Linear/GitHub artifact set below.

## Scenario Evidence

| Scenario | Expected verifier outcome | Harness result | Linear artifact | GitHub artifact | Branch | Commit |
| --- | --- | --- | --- | --- | --- | --- |
| Happy path | `verified_done` and Linear `Done` | `verified` | [`KNO-237`](https://linear.app/knoxanalytics/issue/KNO-237/harness-live-smoke-happy-path-20260423t201821z) | [`PR #55`](https://github.com/sfayka/HARNESS-DRYRUN/pull/55) | `codex/live-reset-happy-path-20260423t201822z` | `d6bafe2a6c737e57c22ec5843215caa505067f0d` |
| Missing pull request proof | `retryable_invalid_proof` and Linear `In Progress` | `retrying` | [`KNO-238`](https://linear.app/knoxanalytics/issue/KNO-238/harness-live-smoke-missing-pull-request-20260423t201830z) | [`PR #56`](https://github.com/sfayka/HARNESS-DRYRUN/pull/56) | `codex/live-reset-missing-pr-20260423t201830z` | `86b7804eb171156e46832ebcf59054a7e88ee17b` |
| Wrong commit SHA after retry budget | `needs_review` and Linear `In Review` | `needs_review` | [`KNO-239`](https://linear.app/knoxanalytics/issue/KNO-239/harness-live-smoke-wrong-sha-review-20260423t201837z) | [`PR #57`](https://github.com/sfayka/HARNESS-DRYRUN/pull/57) | `codex/live-reset-wrong-sha-review-20260423t201838z` | `91b9412b0f297fbdb93777ff3a20c25e8f23dd28` |

## Contract Evidence

The local contract store recorded:

- `live-reset-happy-20260423t201825z`: `latest_verdict=verified_done`, `harness_status=verified`, `latest_reason=github proof verified`
- `live-reset-missing-pr-20260423t201833z`: `latest_verdict=retryable_invalid_proof`, `harness_status=retrying`, `latest_reason=pull request does not exist in the expected repository`
- `live-reset-wrong-sha-review-20260423t201840z`: `latest_verdict=needs_review`, `harness_status=needs_review`, `latest_reason=commit sha does not exist in the expected repository`

This is the release gate that proves Harness does not accept worker completion claims on trust when live GitHub and Linear facts disagree.
