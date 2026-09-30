/**
 * How to read a run's state.
 *
 * The important one is approval. Every plan requires a human to approve it: the
 * API stores approvals against a user row, the project carries a database
 * constraint that cannot be disabled, and the executor re-checks the approver is
 * still an active owner, admin or operator before it will run anything. An agent
 * therefore cannot clear this state, and a tool that reports it as an error or a
 * failure will be read by a model as something to retry. It is a wait, and it
 * will be a long one.
 */

export const TERMINAL_STATES = new Set([
  "completed",
  "cancelled",
  "rejected",
  "dry_run_complete",
]);

/** States a run sits in until a person intervenes. Not failures. */
export const HUMAN_WAIT_STATES = new Set([
  "awaiting_approval",
  "awaiting_manual",
  "blocked",
  "human_review",
  "delivery_uncertain",
]);

export type RunOutcome = "terminal" | "human_wait" | "in_progress" | "failed";

export interface RunView {
  id?: string;
  state: string;
  stage?: string | null;
  error_code?: string | null;
  [key: string]: unknown;
}

export function classify(state: string): RunOutcome {
  if (TERMINAL_STATES.has(state)) return "terminal";
  if (HUMAN_WAIT_STATES.has(state)) return "human_wait";
  if (state === "failed" || state === "error") return "failed";
  return "in_progress";
}

/** A sentence explaining a wait, so the model is not left to infer it. */
export function waitingExplanation(run: RunView): string | undefined {
  switch (run.state) {
    case "awaiting_approval":
      return (
        "A person must approve this run's plan before it can execute. That is " +
        "required by the system and cannot be done through this server. Wait, and " +
        "do not resubmit: the same work request will wait again."
      );
    case "awaiting_manual":
      return "A person has to complete a manual step. Do not resubmit; the run is still live.";
    case "blocked":
      return (
        "The run is blocked and an operator has been emailed. It will not " +
        "progress on its own. Resubmitting will produce the same block."
      );
    case "human_review":
      return "The run finished and is waiting for a person to review it. It will not progress on its own.";
    case "delivery_uncertain":
      return (
        "The work may or may not have been delivered. A person has to check " +
        "before anything is retried, because retrying could duplicate the change."
      );
    default:
      return undefined;
  }
}

/** True when a further poll could still change the answer. */
export function isSettled(run: RunView): boolean {
  const outcome = classify(run.state);
  return (
    outcome === "terminal" || outcome === "human_wait" || outcome === "failed"
  );
}
