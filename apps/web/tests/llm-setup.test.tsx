import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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

function renderWizard(
  ready: LlmReadiness,
  user: User = owner,
  preflight: { allow_http_private?: boolean } = {},
) {
  api.mockImplementation(async (path: string) => {
    if (path === "/llm-readiness") return structuredClone(ready);
    if (path === "/integrations") return [];
    if (path === "/auth/preflight")
      return { allow_http_private: false, ...preflight };
    if (path.endsWith("/probes")) return [];
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

const cleartext = {
  id: "c1",
  name: "LAN Ollama",
  active: true,
  version: 1,
  loopback_pinned: false,
  cleartext_endpoint: true,
};

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

  it("explains the pinned address in plain terms, and says which machine it is", async () => {
    // The second address box is the least self-explanatory thing on this screen:
    // the origin above already names a host, so asking for the address again
    // looks like a mistake. The cost of NOT explaining it is an operator who
    // types their own machine's address, or a hostname, and gets a refusal they
    // cannot read. So the explanation is pinned by this test.
    renderWizard(readiness());
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save endpoint" }),
      ).toBeEnabled(),
    );
    const summary = screen.getByText(/What is .Pinned server IP/);
    expect(summary).toBeInTheDocument();
    const explainer = summary.closest("details")!;
    // It must actually open, not just exist: a hidden explanation is no
    // explanation.
    explainer.open = true;
    const text = explainer.textContent ?? "";
    // The phone-book analogy is the whole reason this is understandable.
    expect(text).toMatch(/phone book/i);
    // The security reason, in the words an operator would use.
    expect(text).toMatch(/secret/i);
    // And the practical disambiguation, which is the part people get wrong.
    expect(text).toMatch(/model server/i);
    expect(text).toMatch(/not this machine/i);
    // A name is refused here, so say so before they try it.
    expect(text).toMatch(/not type a name|needs looking up/i);
  });

  it("warns permanently about a cleartext endpoint that is not loopback", async () => {
    // The one thing the interface must not do is quietly accept a shape whose
    // cost is invisible after the fact. Both directions of the exposure are
    // named, because a request-only warning would miss the more serious half:
    // the reply becomes the recorded plan for a governed run.
    renderWizard(readiness({ connection: cleartext, connection_count: 1 }));
    await waitFor(() =>
      expect(
        screen.getByText("This endpoint is unprotected."),
      ).toBeInTheDocument(),
    );
    const notice = screen
      .getByText("This endpoint is unprotected.")
      .closest("p")!;
    expect(notice.textContent).toMatch(/in the clear/i);
    expect(notice.textContent).toMatch(/recorded plan/);
    // A proxy is the arrangement that keeps the traffic off the wire, so it is
    // the useful half of the advice.
    expect(notice.textContent).toMatch(/proxy/i);
  });

  it("does not warn about a loopback cleartext endpoint", async () => {
    // Loopback traffic never crosses a network, so the same warning would be
    // noise on the most common configuration there is.
    renderWizard(
      readiness({
        connection: {
          ...cleartext,
          loopback_pinned: true,
          cleartext_endpoint: false,
        },
        connection_count: 1,
      }),
    );
    // The notice lives in the screen rather than in the connection form, so it
    // is shown on whichever step is open. Wait for the step this fixture lands
    // on and then check the notice is absent from it.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Request connection check" }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("This endpoint is unprotected.")).toBeNull();
  });

  it("does not claim a certificate is required for a cleartext origin", async () => {
    // The transport builds no TLS context at all for cleartext, so telling an
    // operator about CA bundles for http:// asserts something false about the
    // most common local configuration there is.
    renderWizard(readiness());
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save endpoint" }),
      ).toBeEnabled(),
    );
    const origin = screen.getByLabelText(/Model endpoint origin/);
    fireEvent.change(origin, {
      target: { value: "http://192.168.7.20:11434" },
    });
    expect(
      screen.queryByText(/Two things to know before an https endpoint/),
    ).toBeNull();
  });

  it("still explains the certificate requirement for an https origin", async () => {
    // Scoping the notice must not lose it where it is true.
    renderWizard(readiness());
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save endpoint" }),
      ).toBeEnabled(),
    );
    const origin = screen.getByLabelText(/Model endpoint origin/);
    fireEvent.change(origin, {
      target: { value: "https://192.168.7.20:11434" },
    });
    await waitFor(() =>
      expect(
        screen.getByText(/Two things to know before an https endpoint/),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/NACHTLABS_INTEGRATION_CA_FILE/),
    ).toBeInTheDocument();
  });

  it("says nothing about certificates for a saved cleartext connection", async () => {
    // The saved connection is authoritative once there is one.
    renderWizard(readiness({ connection: cleartext, connection_count: 1 }));
    await waitFor(() =>
      expect(
        screen.getByText("This endpoint is unprotected."),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/Two things to know before an https endpoint/),
    ).toBeNull();
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
          cleartext_endpoint: false,
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
          cleartext_endpoint: false,
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
          cleartext_endpoint: false,
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
          cleartext_endpoint: false,
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
    expect(screen.getByText(/last change was not/)).toBeVisible();
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
          cleartext_endpoint: false,
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

describe("setup transitions", () => {
  const endpoint = {
    id: "c1",
    name: "Ollama",
    active: true,
    version: 1,
    loopback_pinned: true,
    cleartext_endpoint: false,
  };
  const discovered: LlmReadiness["discovery"] = {
    state: "succeeded",
    models: [
      { name: "coder", digest: null },
      { name: "reviewer", digest: null },
    ],
    checked_at: "2026-09-28T12:00:00Z",
  };

  it("allows every tab on an empty installation without claiming completion", async () => {
    renderWizard(readiness());
    await screen.findByRole("button", { name: "Save endpoint" });
    for (const title of [
      "Confirm identity",
      "Model endpoint",
      "Connection check",
      "Model profiles",
      "Coding agent",
      "Summary",
    ]) {
      fireEvent.click(
        screen.getByRole("button", {
          name: new RegExp(`^[1-6]\\. ${title}$`),
        }),
      );
    }
    expect(screen.getByText(/Configuration is incomplete/)).toBeVisible();
    expect(screen.queryByText(/Configuration is complete/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "4. Model profiles" }));
    expect(
      screen.getByText("Create an active model endpoint first."),
    ).toBeVisible();
  });

  it("completes endpoint, discovery, profiles and agent without reloading", async () => {
    const ready = readiness();
    renderWizard(ready);
    write.mockImplementation(
      async (path: string, body: Record<string, unknown>) => {
        if (path === "/integrations") {
          ready.connection = endpoint;
          ready.connection_count = 1;
          return { id: "c1" };
        }
        if (path.endsWith("/probes")) {
          ready.discovery = { state: "pending", models: [], checked_at: null };
          return { id: "probe1" };
        }
        if (path === "/model-profiles") {
          const profile = { id: String(body.role), model: String(body.model) };
          if (body.role === "implementation")
            ready.implementation_profile = profile;
          else ready.verifier_profile = profile;
          ready.distinct_models =
            !!ready.implementation_profile &&
            !!ready.verifier_profile &&
            ready.implementation_profile.model !== ready.verifier_profile.model;
          return profile;
        }
        if (path === "/agents") {
          ready.agent = {
            id: "agent1",
            name: "Hermes",
            provider: "hermes",
            executable: "/usr/local/bin/hermes",
          };
          ready.complete = true;
          return ready.agent;
        }
        throw new Error(`Unexpected write: ${path}`);
      },
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Save endpoint" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Continue to connection check" }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Continue to connection check" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Request connection check" }),
    );
    await screen.findByText("Queued");
    ready.discovery = discovered;
    fireEvent.click(
      await screen.findByRole(
        "button",
        { name: "Continue to model profiles" },
        { timeout: 6500 },
      ),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Create implementation profile",
      }),
    );
    await screen.findByText(/Already configured as/);
    const verifier = screen
      .getByRole("button", { name: "Create verifier profile" })
      .closest("form")!;
    fireEvent.change(within(verifier).getByLabelText(/^Model/), {
      target: { value: "reviewer" },
    });
    fireEvent.submit(verifier);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Continue to coding agent" }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Continue to coding agent" }),
    );
    fireEvent.change(
      await screen.findByLabelText(/Expected installed version/),
      { target: { value: "1.2.3" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Show the summary" }),
    );
    expect(await screen.findByText(/Configuration is complete/)).toBeVisible();
    expect(screen.getByText("Requires operator qualification")).toBeVisible();
  }, 12000);

  it("refuses a duplicate verifier model before writing it", async () => {
    renderWizard(
      readiness({
        connection: endpoint,
        discovery: discovered,
        implementation_profile: { id: "p1", model: "coder" },
      }),
    );
    const button = await screen.findByRole("button", {
      name: "Create verifier profile",
    });
    const form = button.closest("form")!;
    fireEvent.change(within(form).getByLabelText(/^Model/), {
      target: { value: "coder" },
    });
    fireEvent.submit(form);
    expect(
      await screen.findByText(
        "Choose different models for implementation and verification.",
      ),
    ).toBeVisible();
    expect(write).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Continue to coding agent" }),
    ).toBeDisabled();
  });

  it("preserves the interrupted draft through two confirmation expiries", async () => {
    renderWizard(readiness());
    write.mockImplementation(async (path: string) => {
      if (path === "/auth/reauthenticate") return {};
      throw new ApiError(403, "reauth_required", "Confirm identity");
    });
    fireEvent.change(await screen.findByLabelText(/Connection name/), {
      target: { value: "My draft endpoint" },
    });
    for (let attempt = 0; attempt < 2; attempt += 1) {
      fireEvent.click(screen.getByRole("button", { name: "Save endpoint" }));
      fireEvent.change(await screen.findByLabelText(/Current password/), {
        target: { value: "my-password" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm identity" }));
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: "Save endpoint" }),
        ).toBeVisible(),
      );
      expect(screen.getByLabelText(/Connection name/)).toHaveValue(
        "My draft endpoint",
      );
      expect(screen.queryByText(/last change was not/)).toBeNull();
    }
    expect(
      write.mock.calls.filter(([path]) => path === "/auth/reauthenticate"),
    ).toHaveLength(2);
  });
});
