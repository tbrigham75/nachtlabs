/**
 * The tools this server exposes.
 *
 * Deliberately read-and-submit only. Creating a Project, a Mission or a Journey,
 * changing the execution policy and approving a plan are all gated on a human
 * browser session, and that is the point: the credential this server holds can
 * drive work inside a project someone configured, and cannot rewrite the rules
 * that govern it. Offering a tool for something the key cannot do would only
 * produce a confusing 403.
 */

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/server";
import type { NachtLabs } from "./nachtlabs.js";
import { isSettled, waitingExplanation, type RunView } from "./state.js";

function json(value: unknown): { content: { type: "text"; text: string }[] } {
  return { content: [{ type: "text", text: JSON.stringify(value, null, 2) }] };
}

function extractId(payload: unknown): string | undefined {
  const run = (payload as { run?: { id?: string } } | undefined)?.run;
  return run?.id;
}

const priority = z
  .enum(["low", "normal", "high", "urgent"])
  .optional()
  .describe("Defaults to normal.");

export function registerTools(server: McpServer, client: NachtLabs): void {
  server.registerTool(
    "submit_work",
    {
      title: "Submit work to a project",
      description:
        "Create a work request against an existing branch and start a run. Requires an " +
        "approved Mission and approved, enabled baseline Journeys on the project; if those " +
        "are missing the API refuses with mission_required or baseline_required and a person " +
        "has to resolve it. Supply acceptance_criteria, since they become part of the governed record.",
      inputSchema: z.object({
        project_id: z.string().describe("The project to submit to."),
        title: z.string().min(3).max(200),
        description: z
          .string()
          .min(10)
          .max(12000)
          .describe("What to build and why."),
        acceptance_criteria: z
          .array(z.string())
          .min(1)
          .max(30)
          .describe(
            "How to tell it is done. These become part of the recorded plan.",
          ),
        target_ref: z
          .string()
          .optional()
          .describe("Branch to build on. Defaults to main."),
        priority,
        labels: z.array(z.string()).optional(),
        links: z.array(z.string()).optional(),
        dry_run: z
          .boolean()
          .optional()
          .describe(
            "Plan only, no execution. Useful before committing to a shape.",
          ),
      }),
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
      },
    },
    async (args) => {
      client.assertProjectAllowed(args.project_id);
      const payload = await client.submitWork({ ...args });
      const runId = extractId(payload);
      return json({
        run_id: runId,
        ...(runId
          ? {}
          : {
              note: "The API returned no run id; check the work request directly.",
            }),
        work_request: (payload as { work_request?: unknown }).work_request,
        run: (payload as { run?: unknown }).run,
        next: "Call get_run, or wait_for_run to block until it settles.",
      });
    },
  );

  server.registerTool(
    "get_run",
    {
      title: "Read a run",
      description: "Current state, stage and error code for one run.",
      inputSchema: z.object({ run_id: z.string() }),
      annotations: { readOnlyHint: true },
    },
    async ({ run_id }) => json(await client.getRun(run_id)),
  );

  server.registerTool(
    "wait_for_run",
    {
      title: "Wait for a run to settle",
      description:
        "Block until the run reaches a state a person has to act on, or finishes. Use " +
        "this instead of polling get_run in a loop: the polling and the rate-limit " +
        "handling are done here. It returns as soon as the run needs a person, which " +
        "for awaiting_approval may be immediately, and that is the expected outcome " +
        "rather than a failure.",
      inputSchema: z.object({
        run_id: z.string(),
        timeout_ms: z
          .number()
          .int()
          .positive()
          .optional()
          .describe(
            "Give up after this long and report where the run is. Defaults to 15 minutes.",
          ),
      }),
      annotations: { readOnlyHint: true },
    },
    async ({ run_id, timeout_ms }) => {
      const budget = Math.min(timeout_ms ?? client.maxWaitMs, client.maxWaitMs);
      const deadline = Date.now() + budget;
      let last: RunView | undefined;
      for (;;) {
        last = await client.getRun(run_id);
        if (isSettled(last)) break;
        if (Date.now() + client.pollIntervalMs >= deadline) {
          return json({
            run: last,
            settled: false,
            note: `Still not settled after ${Math.round(budget / 1000)}s. It was progressing; call again to keep waiting.`,
          });
        }
        await client.wait(client.pollIntervalMs);
      }
      const explanation = waitingExplanation(last);
      return json({
        run: last,
        settled: true,
        ...(explanation ? { requires_a_person: explanation } : {}),
      });
    },
  );

  server.registerTool(
    "run_events",
    {
      title: "Read a run's events",
      description:
        "Cursor-paginated event feed for a run. Pass the `latest` from the previous " +
        "call as `after` to get only what is new.",
      inputSchema: z.object({
        run_id: z.string(),
        after: z
          .number()
          .int()
          .min(0)
          .optional()
          .describe("Event sequence to resume after."),
      }),
      annotations: { readOnlyHint: true },
    },
    async ({ run_id, after }) =>
      json(await client.runEvents(run_id, after ?? 0)),
  );

  server.registerTool(
    "list_projects",
    {
      title: "List projects the key can see",
      description:
        "Projects visible to this credential. A project that exists but is not listed " +
        "is not bound to this key.",
      inputSchema: z.object({}),
      annotations: { readOnlyHint: true },
    },
    async () => json(await client.listProjects()),
  );

  server.registerTool(
    "list_runs",
    {
      title: "List a project's runs",
      description: "Recent runs for a project, newest first.",
      inputSchema: z.object({
        project_id: z.string(),
        limit: z.number().int().min(1).max(100).optional(),
      }),
      annotations: { readOnlyHint: true },
    },
    async ({ project_id, limit }) => {
      client.assertProjectAllowed(project_id);
      return json(await client.listRuns(project_id, limit));
    },
  );

  server.registerTool(
    "get_installation_status",
    {
      title: "Check the installation's status",
      description:
        "Whether the worker is alive, and whether execution is available at all. " +
        "Execution requires an independently qualified Linux executor, which the API " +
        "does not infer from configuration, so a run submitted here may stop at blocked " +
        "even when this reports the worker online.",
      inputSchema: z.object({}),
      annotations: { readOnlyHint: true },
    },
    async () => json(await client.overview()),
  );
}
