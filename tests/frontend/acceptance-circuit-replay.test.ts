import assert from "node:assert/strict";
import test from "node:test";
import {
  acceptanceCircuitScenarios,
  mapTimelineToAcceptanceEvents,
} from "@/lib/acceptance-circuit-replay";

test("maps canonical demo fixtures into Acceptance Circuit scenarios", () => {
  assert.equal(acceptanceCircuitScenarios.length, 4);

  const accepted = acceptanceCircuitScenarios.find((scenario) => scenario.id === "accepted");
  assert.ok(accepted);
  assert.equal(accepted.outcome, "accepted");
  assert.equal(accepted.modeLabel, "Sample replay: canonical fixture");
  assert.ok(accepted.events.some((event) => event.vocabulary === "policy.accepted"));
  assert.ok(accepted.events.some((event) => event.vocabulary === "evidence.validated"));
  assert.ok(accepted.events.some((event) => event.vocabulary === "reconciliation.passed"));
});

test("keeps insufficient evidence and review gates out of accepted completion", () => {
  const insufficient = acceptanceCircuitScenarios.find(
    (scenario) => scenario.id === "insufficient-evidence",
  );
  const review = acceptanceCircuitScenarios.find((scenario) => scenario.id === "manual-review");

  assert.ok(insufficient);
  assert.equal(insufficient.outcome, "insufficient evidence");
  assert.ok(insufficient.events.some((event) => event.vocabulary === "policy.blocked"));

  assert.ok(review);
  assert.equal(review.outcome, "review required");
  assert.ok(review.events.some((event) => event.vocabulary === "review.requested"));
  assert.ok(review.events.some((event) => event.nodeId === "review"));
});

test("maps reconciliation mismatch into a blocked policy event", () => {
  const mismatch = acceptanceCircuitScenarios.find(
    (scenario) => scenario.id === "tracker-mismatch",
  );

  assert.ok(mismatch);
  assert.equal(mismatch.outcome, "blocked");
  assert.ok(mismatch.events.some((event) => event.vocabulary === "reconciliation.mismatch"));
  assert.ok(mismatch.events.some((event) => event.vocabulary === "policy.blocked"));
});

test("adds a terminal policy event when timeline has no evaluation event", () => {
  const events = mapTimelineToAcceptanceEvents(
    [
      {
        event_id: "task-1:created",
        event_type: "task_created",
        source: "openclaw",
        summary: "Task created",
      },
    ],
    {
      task_id: "task-1",
      verification_summary: {
        accepted_completion: true,
      },
    },
  );

  assert.ok(events.some((event) => event.vocabulary === "policy.accepted"));
});
