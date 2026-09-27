import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@nachtlabs/api-client";

/*
  Focused checks on the setup-token field. The e2e suite proves the routing, but
  it needs a browser and a running installation; this proves the form itself,
  which is where the token logic lives.
*/

const { write, api, replace } = vi.hoisted(() => ({
  write: vi.fn(),
  api: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("@nachtlabs/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@nachtlabs/api-client")>();
  return { ...actual, write, api };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("next/link", () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));

const { AuthScreen } = await import("../src/features/auth");

const owner = {
  id: "00000000-0000-4000-8000-000000000002",
  email: "owner@acme.example",
  name: "Owner",
  role: "owner",
  active: true,
  theme: "midnight",
  mfa_enabled: false,
  version: 1,
};

function renderSetup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AuthScreen
        path="/setup"
        initialized={false}
        checkingSetup={false}
        setupUnreachable={false}
        retrySetup={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

function preflight(setup_token_required: boolean) {
  api.mockResolvedValue({
    origin: "http://localhost:3000",
    expected: "http://localhost:3000",
    origin_accepted: true,
    setup_token_required,
    initialized: false,
    hint: null,
  });
}

function fillRequired(password = "correct-horse-battery") {
  fireEvent.change(screen.getByLabelText(/Email address/), {
    target: { value: "owner@acme.example" },
  });
  fireEvent.change(screen.getByLabelText(/^Password/), {
    target: { value: password },
  });
  fireEvent.change(screen.getByLabelText(/^Confirm password/), {
    target: { value: password },
  });
}

function submit() {
  fireEvent.submit(
    screen
      .getByRole("button", { name: "Create Owner account" })
      .closest("form")!,
  );
}

beforeEach(() => {
  write.mockReset();
  api.mockReset();
  replace.mockReset();
});

describe("setup token", () => {
  it("asks for no token when the installation does not require one", async () => {
    preflight(false);
    renderSetup();
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(screen.queryByLabelText(/setup token/i)).toBeNull();
  });

  it("asks for the token when preflight reports it is required", async () => {
    preflight(true);
    renderSetup();
    await waitFor(() =>
      expect(screen.getByLabelText(/setup token/i)).toBeInTheDocument(),
    );
  });

  it("stays silent when preflight cannot be read", async () => {
    // An unreachable answer must never demand a secret the operator may not
    // have, or hide the form they came for.
    api.mockRejectedValue(new ApiError(503, "database_unavailable", "down"));
    renderSetup();
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(screen.queryByLabelText(/setup token/i)).toBeNull();
    expect(screen.getByLabelText(/Email address/)).toBeInTheDocument();
  });

  it("sends the token and never the password confirmation", async () => {
    preflight(true);
    write.mockResolvedValue(owner);
    renderSetup();
    await waitFor(() =>
      expect(screen.getByLabelText(/setup token/i)).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText(/setup token/i), {
      target: { value: "one-time-setup-token" },
    });
    fillRequired();
    submit();
    await waitFor(() => expect(write).toHaveBeenCalled());
    // The API forbids unknown fields, so the confirmation must be stripped.
    expect(write).toHaveBeenCalledWith("/auth/setup", {
      organization: "NachtLabs",
      name: "Owner",
      email: "owner@acme.example",
      password: "correct-horse-battery",
      bootstrap_token: "one-time-setup-token",
    });
  });

  it("omits the token entirely on a default installation", async () => {
    preflight(false);
    write.mockResolvedValue(owner);
    renderSetup();
    await waitFor(() => expect(api).toHaveBeenCalled());
    fillRequired();
    submit();
    await waitFor(() => expect(write).toHaveBeenCalled());
    expect(write.mock.calls[0][1]).not.toHaveProperty("bootstrap_token");
  });

  it("reveals the field on a refusal and keeps what was typed", async () => {
    // Regression guard: a wrong or missing preflight flag used to leave the
    // operator with a bare 403, no field, and no way forward.
    preflight(false);
    write.mockRejectedValue(
      new ApiError(403, "invalid_setup_token", "Invalid setup token"),
    );
    renderSetup();
    await waitFor(() => expect(api).toHaveBeenCalled());
    fillRequired();
    submit();
    await waitFor(() =>
      expect(screen.getByLabelText(/setup token/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "requires the one-time setup token",
    );
    // Revealing the field must not discard the account being created.
    expect(screen.getByLabelText(/Email address/)).toHaveValue(
      "owner@acme.example",
    );
    expect(screen.getByLabelText(/^Password/)).toHaveValue(
      "correct-horse-battery",
    );
    // And the retry now succeeds, so the operator is not stuck.
    write.mockResolvedValue(owner);
    fireEvent.change(screen.getByLabelText(/setup token/i), {
      target: { value: "one-time-setup-token" },
    });
    submit();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/overview"));
  });

  it("still reports an unrelated failure as itself", async () => {
    // The 403 fallback must not swallow setup_closed or an origin refusal.
    preflight(false);
    write.mockRejectedValue(
      new ApiError(409, "setup_closed", "Setup is already complete"),
    );
    renderSetup();
    await waitFor(() => expect(api).toHaveBeenCalled());
    fillRequired();
    submit();
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "Setup is already complete",
      ),
    );
    expect(screen.queryByLabelText(/setup token/i)).toBeNull();
  });
});
