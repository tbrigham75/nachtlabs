import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError, type LlmReadiness, type User } from "@nachtlabs/api-client";

/*
  Focused checks on the setup wizard. The behaviour that matters is that it
  never claims more than is true: a saved connection is not a working one, a
  blocked step says why instead of offering a dead button, and a lapsed
  confirmation returns the operator to where they were rather than stranding
  them.
*/

const { write, api } = vi.hoisted(() => ({ write: vi.fn(), api: vi.fn() }));

vi.mock("@nachtlabs/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@nachtlabs/api-client")>();
  return { ...actual, write, api };
});
vi.mock("next/link", () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));

const { LlmSetupScreen } = await import("../src/features/llm-setup");

const owner: User = {
  id: "00000000-0000-4000-8000-000000000002",
  email: "owner@acme.example",
  name: "Tom",
  role: "owner",
  active: true,
  theme: "midnight",
  mfa_enabled: false,
  version: 1,
};

function readiness(over: Partial<LlmReadiness> = {}): LlmReadiness {
  return {
    provider_network_enabled: true,
    connection: null,
    connection_count: 0,
    discovery: { state: "not_run", models: [], checked_at: null },
    implementation_profile: null,
    verifier_profile: null,
    planning_profile: null,
    agent: null,
    distinct_models: false,
    execution_available: false,
    complete: false,
    ...over,
  };
}

function renderWizard(ready: LlmReadiness, user: User = owner) {
  api.mockImplementation(async (path: string) => {
    if (path === "/llm-readiness") return ready;
    if (path === "/integrations") return [];
    return {};
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LlmSetupScreen user={user} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  write.mockReset();
  api.mockReset();
});

describe("llm setup wizard", () => {
  it("is refused to non-admins", async () => {
    renderWizard(readiness(), { ...owner, role: "viewer" });
    await waitFor(() =>
      expect(
        screen.getByText(/Owner or Admin access is required/),
      ).toBeInTheDocument(),
    );
  });

  it("opens on the first step that still needs work", async () => {
    // Not on the confirmation step: a sign-in already opened a ten-minute
    // window, so demanding a password just to look would be wrong.
    renderWizard(readiness());
    await waitFor(() =>
      expect(screen.getByText("Model endpoint")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Save endpoint" })).toBeEnabled();
  });

  it("resumes at discovery once an endpoint is saved", async () => {
    renderWizard(
      readiness({
        connection: {
          id: "c1",
          name: "Local Ollama",
          active: true,
          version: 1,
          loopback_pinned: false,
        },
        connection_count: 1,
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Request connection check" }),
      ).toBeInTheDocument(),
    );
  });

  it("resumes at the summary once everything is configured", async () => {
    renderWizard(
      readiness({
        connection: {
          id: "c1",
          name: "Local Ollama",
          active: true,
          version: 1,
          loopback_pinned: false,
        },
        discovery: {
          state: "succeeded",
          models: [{ name: "qwen3-coder:30b", digest: null }],
          checked_at: "2026-01-01T00:00:00Z",
        },
        implementation_profile: { id: "p1", model: "qwen3-coder:30b" },
        verifier_profile: { id: "p2", model: "qwen3:8b" },
        agent: {
          id: "a1",
          name: "Hermes",
          provider: "hermes",
          executable: "/usr/local/bin/hermes",
        },
        distinct_models: true,
        complete: true,
      }),
    );
    await waitFor(() =>
      expect(screen.getByText("Where this stands")).toBeInTheDocument(),
    );
    // The four states must stay separate even when complete.
    expect(screen.getByText("Unverified")).toBeInTheDocument();
    expect(
      screen.getByText("Requires operator qualification"),
    ).toBeInTheDocument();
    // And it must never imply execution is possible.
    expect(screen.queryByText("Execution enabled")).toBeNull();
  });

  it("blocks the connection check by name when the switch is off", async () => {
    renderWizard(
      readiness({
        provider_network_enabled: false,
        connection: {
          id: "c1",
          name: "Local Ollama",
          active: true,
          version: 1,
          loopback_pinned: false,
        },
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByText(/Blocked by installation policy/),
      ).toBeInTheDocument(),
    );
    // No dead button: offering one that cannot work is worse than saying why.
    expect(
      screen.queryByRole("button", { name: "Request connection check" }),
    ).toBeNull();
    expect(
      screen.getAllByText(/NACHTLABS_INTEGRATION_NETWORK_ENABLED/).length,
    ).toBeGreaterThan(0);
  });

  it("warns that loopback cannot serve agent execution", async () => {
    renderWizard(
      readiness({
        connection: {
          id: "c1",
          name: "Local Ollama",
          active: true,
          version: 1,
          loopback_pinned: true,
        },
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByText(/pinned to a loopback address/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/executor_network_policy/)).toBeInTheDocument();
  });

  it("sends a well-formed Ollama connection", async () => {
    write.mockResolvedValue({ id: "c1" });
    renderWizard(readiness());
    await waitFor(() =>
      expect(screen.getByLabelText(/Connection name/)).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText(/Connection name/), {
      target: { value: "Home Ollama" },
    });
    fireEvent.submit(
      screen.getByRole("button", { name: "Save endpoint" }).closest("form")!,
    );
    await waitFor(() => expect(write).toHaveBeenCalled());
    expect(write).toHaveBeenCalledWith("/integrations", {
      name: "Home Ollama",
      provider: "ollama",
      base_url: "http://127.0.0.1:11434",
      pinned_addresses: ["127.0.0.1"],
      allow_private: true,
      allow_http: true,
      timeout_seconds: 15,
      active: true,
      expected_version: 0,
    });
  });

  it("returns to confirmation when the write window has lapsed", async () => {
    // Regression guard: a bare 403 mid-flow used to dead-end the wizard with
    // the form contents lost and no route forward.
    write.mockRejectedValue(
      new ApiError(
        403,
        "reauth_required",
        "Confirm your password in Security settings and retry",
      ),
    );
    renderWizard(readiness());
    await waitFor(() =>
      expect(screen.getByLabelText(/Connection name/)).toBeInTheDocument(),
    );
    fireEvent.submit(
      screen.getByRole("button", { name: "Save endpoint" }).closest("form")!,
    );
    await waitFor(() =>
      expect(screen.getByLabelText(/Current password/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/confirmation expired/)).toBeInTheDocument();
  });

  it("offers distinct models for implementation and verification", async () => {
    write.mockResolvedValue({});
    renderWizard(
      readiness({
        connection: {
          id: "c1",
          name: "Local Ollama",
          active: true,
          version: 1,
          loopback_pinned: false,
        },
        discovery: {
          state: "succeeded",
          models: [
            { name: "qwen3-coder:30b", digest: null },
            { name: "qwen3:8b", digest: null },
          ],
          checked_at: "2026-01-01T00:00:00Z",
        },
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Create implementation profile" }),
      ).toBeInTheDocument(),
    );
    // Neither profile exists yet, so the wizard must not let the operator on.
    expect(
      screen.getByRole("button", { name: "Continue to coding agent" }),
    ).toBeDisabled();
  });
});
