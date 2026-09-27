import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError, type LlmReadiness, type User } from "@nachtlabs/api-client";

/*
  The origin diagnosis. The failure it exists to prevent is an operator filling
  in a whole form, pressing save, and being told only "Request origin is not
  permitted" with nothing about what to change.

  The comparison is made in the browser against the address actually in use.
  preflight's own origin_accepted cannot be used: a same-origin GET carries no
  Origin header, so it reads false on a perfectly healthy installation. The
  banner-must-be-absent case below is what pins that.
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
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/overview",
}));

const { Shell } = await import("../src/components/shell");
const { originNotPermitted } = await import("../src/components/screen");
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

/** The address the test browser is on, matching jsdom's default location. */
const HERE = "http://localhost:3000";

function renderShell(origin: {
  here: string | null;
  permitted: string[];
  mismatch: boolean;
  secure: boolean;
}) {
  // Shell reads the worker heartbeat through react-query, so it needs a client.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <Shell user={owner} origin={origin}>
        <p>page body</p>
      </Shell>
    </QueryClientProvider>,
  );
}

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

beforeEach(() => {
  write.mockReset();
  api.mockReset();
  // The shell reads the worker heartbeat on mount; an undefined query result is
  // an error in react-query, so give it something.
  api.mockResolvedValue({ worker: "online" });
});

describe("origin detection", () => {
  // The comparison itself, separated from the banner, because driving the
  // banner by a prop would let a broken comparison pass every rendering test.
  it("flags an address the server does not answer on", () => {
    expect(
      originNotPermitted(
        "http://192.168.1.5:3000",
        ["http://localhost:3000", "https://nacht.lan"],
        false,
      ),
    ).toBe(true);
  });

  it("stays silent for a permitted address", () => {
    expect(
      originNotPermitted("https://nacht.lan", ["https://nacht.lan"], false),
    ).toBe(false);
  });

  it("stays silent while the permitted set is unknown", () => {
    expect(originNotPermitted("https://nacht.lan", [], false)).toBe(false);
  });

  it("stays silent when preflight could not be read", () => {
    // A failed preflight is handled by the unreachable screen; claiming a
    // mismatch here would compound one fault with another.
    expect(
      originNotPermitted("https://nacht.lan", ["http://localhost:3000"], true),
    ).toBe(false);
  });

  it("stays silent on the server, where the address is unknown", () => {
    expect(originNotPermitted(null, ["http://localhost:3000"], false)).toBe(
      false,
    );
  });

  it("compares the whole origin, so a different port is a different address", () => {
    // Ports are not part of the site for SameSite purposes, which is exactly
    // why the Origin check has to include them.
    expect(
      originNotPermitted(
        "http://localhost:3001",
        ["http://localhost:3000"],
        false,
      ),
    ).toBe(true);
    expect(
      originNotPermitted(
        "https://localhost:3000",
        ["http://localhost:3000"],
        false,
      ),
    ).toBe(true);
  });

  it("does not accept a prefix or a suffix of a permitted origin", () => {
    // Membership is exact; a substring rule would let an attacker's lookalike
    // host satisfy the check.
    expect(
      originNotPermitted(
        "https://nacht.lan.evil.invalid",
        ["https://nacht.lan"],
        false,
      ),
    ).toBe(true);
    expect(
      originNotPermitted("https://xnacht.lan", ["https://nacht.lan"], false),
    ).toBe(true);
  });
});

describe("origin diagnosis banner", () => {
  it("says nothing when the address in use is permitted", () => {
    // The regression that matters most: a comparison built on preflight's
    // origin_accepted would show this on a healthy installation, because a
    // same-origin GET reports origin null and accepted false.
    renderShell({
      here: HERE,
      permitted: ["http://localhost:3000", "https://nacht.lan"],
      mismatch: false,
      secure: true,
    });
    expect(screen.queryByText(/cannot save anything/)).toBeNull();
  });

  it("says nothing while the permitted set is not yet known", () => {
    // Before preflight answers there is nothing to compare against, and a banner
    // that guessed would be worse than silence.
    renderShell({
      here: HERE,
      permitted: [],
      mismatch: false,
      secure: true,
    });
    expect(screen.queryByText(/cannot save anything/)).toBeNull();
  });

  it("names the address in use and every permitted origin when refused", () => {
    renderShell({
      here: "http://192.168.1.5:3000",
      permitted: ["http://localhost:3000", "https://nacht.lan"],
      mismatch: true,
      secure: true,
    });
    const banner = screen.getByRole("alert");
    expect(banner.textContent).toContain("http://192.168.1.5:3000");
    expect(banner.textContent).toContain("http://localhost:3000");
    expect(banner.textContent).toContain("https://nacht.lan");
    // And it must name the thing to change, not just the symptom.
    expect(banner.textContent).toContain("NACHTLABS_ALLOWED_ORIGINS");
  });

  it("warns about a cleartext cookie only when one is actually in play", () => {
    const { unmount } = renderShell({
      here: "http://192.168.1.5:3000",
      permitted: ["http://localhost:3000"],
      mismatch: true,
      secure: false,
    });
    expect(screen.getByText(/cannot be marked Secure/)).toBeInTheDocument();
    unmount();

    renderShell({
      here: "http://192.168.1.5:3000",
      permitted: ["https://nacht.lan"],
      mismatch: true,
      secure: true,
    });
    expect(screen.queryByText(/cannot be marked Secure/)).toBeNull();
  });
});

describe("wizard refusal message", () => {
  function renderWizard(ready: LlmReadiness) {
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
        <LlmSetupScreen user={owner} />
      </QueryClientProvider>,
    );
  }

  const message = "Request origin is not permitted";

  it("explains an origin refusal reported as csrf", async () => {
    // This is the code the wizard's own writes return, because they go through
    // the authenticated CSRF guard. Matching on "origin" alone would never fire
    // and the operator would get the bare API message.
    write.mockRejectedValue(new ApiError(403, "csrf", message));
    renderWizard(readiness());
    await waitFor(() =>
      expect(screen.getByLabelText(/Connection name/)).toBeInTheDocument(),
    );
    fireEvent.submit(
      screen.getByRole("button", { name: "Save endpoint" }).closest("form")!,
    );
    await waitFor(() =>
      expect(screen.getByText(/NACHTLABS_ALLOWED_ORIGINS/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/nothing was saved/)).toBeInTheDocument();
  });

  it("explains the same refusal reported as origin", async () => {
    write.mockRejectedValue(new ApiError(403, "origin", message));
    renderWizard(readiness());
    await waitFor(() =>
      expect(screen.getByLabelText(/Connection name/)).toBeInTheDocument(),
    );
    fireEvent.submit(
      screen.getByRole("button", { name: "Save endpoint" }).closest("form")!,
    );
    await waitFor(() =>
      expect(screen.getByText(/NACHTLABS_ALLOWED_ORIGINS/)).toBeInTheDocument(),
    );
  });

  it("does not hijack an unrelated csrf failure", async () => {
    // The CSRF guard reuses the "csrf" code for the token check, so matching on
    // the code alone would replace a stale-token message with the wrong advice.
    write.mockRejectedValue(
      new ApiError(403, "csrf", "Refresh this page before retrying"),
    );
    renderWizard(readiness());
    await waitFor(() =>
      expect(screen.getByLabelText(/Connection name/)).toBeInTheDocument(),
    );
    fireEvent.submit(
      screen.getByRole("button", { name: "Save endpoint" }).closest("form")!,
    );
    await waitFor(() =>
      expect(
        screen.getByText(/Refresh this page before retrying/),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/NACHTLABS_ALLOWED_ORIGINS/)).toBeNull();
  });
});
