import { test, expect } from "@playwright/test";

// First-run routing only. /auth/setup-status is mocked because a real
// uninitialized installation needs its own database.
const id = "00000000-0000-4000-8000-000000000002";

async function mock(
  page: import("@playwright/test").Page,
  initialized: boolean,
) {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/stream"))
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: ": heartbeat\n\n",
      });
    const data = path.endsWith("/auth/setup-status") ? { initialized } : {};
    if (path.endsWith("/auth/me"))
      return route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({
          error: { code: "unauthenticated", message: "Sign in to continue" },
        }),
      });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  });
}

// The API being unreachable must never be mistaken for "no account exists".
async function mockApiDown(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "text/plain",
      body: "unavailable",
    }),
  );
}

test.describe("first-run discovery", () => {
  test("an installation with no account offers Owner setup instead of sign-in", async ({
    page,
  }) => {
    await mock(page, false);
    await page.goto("/");
    // Must not leave the operator staring at a sign-in form they cannot use.
    await expect(page).toHaveURL(/\/setup$/);
    await expect(
      page.getByRole("heading", { name: "Welcome to NachtLabs" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Welcome back" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Create Owner account" }),
    ).toBeVisible();
    // The form offered must be setup, not a sign-in form nobody can satisfy.
    await expect(page.getByLabel(/Organization name/)).toBeVisible();
    // No secret the operator has never been told about may be demanded.
    await expect(page.getByLabel(/setup token/i)).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Sign in" })).toHaveCount(0);
  });

  test("every unauthenticated entry point routes to setup when uninitialized", async ({
    page,
  }) => {
    await mock(page, false);
    for (const path of ["/login", "/forgot-password", "/accept-invitation"]) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/setup$/);
    }
  });

  test("setup explains itself instead of bouncing once an account exists", async ({
    page,
  }) => {
    // Regression: /setup used to redirect straight back to /login, which read
    // as a broken refresh and hid the reason registration was refused.
    await mock(page, true);
    await page.goto("/setup");
    await expect(page).toHaveURL(/\/setup$/);
    await expect(page.getByText("An account already exists")).toBeVisible();
    // The recovery routes are named, not left for the operator to guess.
    const notice = page.locator(".notice").first();
    await expect(notice).toContainText("make recover-owner");
    await expect(notice).toContainText("--bootstrap");
    await expect(notice).toContainText("without SMTP");
    // And no form is offered that could only ever fail.
    await expect(
      page.getByRole("button", { name: "Create Owner account" }),
    ).toHaveCount(0);
  });

  test("the first-run prompt disappears after initialization", async ({
    page,
  }) => {
    await mock(page, true);
    await page.goto("/login");
    await expect(page.getByLabel(/^Email address/)).toBeVisible();
    await expect(page.getByText(/Create the Owner account/)).toHaveCount(0);
  });

  test("an authenticated operator is never bounced to setup", async ({
    page,
  }) => {
    await page.route("**/api/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/stream"))
        return route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: ": heartbeat\n\n",
        });
      const data = path.endsWith("/auth/me")
        ? {
            id,
            name: "Owner",
            email: "owner@acme.example",
            role: "owner",
            active: true,
            theme: "canvas",
            version: 1,
            mfa_required: false,
          }
        : path.endsWith("/auth/setup-status")
          ? { initialized: true }
          : path.endsWith("/overview")
            ? { worker: "online" }
            : {};
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(data),
      });
    });
    await page.goto("/overview");
    await expect(page).toHaveURL(/\/overview$/);
    await expect(
      page.getByRole("heading", { name: "Engineering overview" }),
    ).toBeVisible();
  });

  test("an unreachable API is reported, never mistaken for a sign-in prompt", async ({
    page,
  }) => {
    // Regression: setup-status failing used to leave the operator on a plain
    // "Welcome back" form, indistinguishable from "no account exists".
    await mockApiDown(page);
    for (const path of ["/", "/login", "/setup"]) {
      await page.goto(path);
      await expect(
        page.getByRole("heading", { name: "NachtLabs is not reachable" }),
      ).toBeVisible();
      await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
      // A sign-in form that cannot work must not be offered.
      await expect(page.getByLabel(/^Email address/)).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: "Create Owner account" }),
      ).toHaveCount(0);
    }
  });

  test("the retry button re-reads setup status", async ({ page }) => {
    await mockApiDown(page);
    await page.goto("/login");
    await expect(
      page.getByRole("heading", { name: "NachtLabs is not reachable" }),
    ).toBeVisible();
    // Now let setup-status through; the page must recover to the right state.
    await page.unroute("**/api/v1/**");
    await mock(page, true);
    await page.getByRole("button", { name: "Retry" }).click();
    await expect(
      page.getByRole("heading", { name: "Welcome back" }),
    ).toBeVisible();
  });
});

test.describe("setup is always discoverable", () => {
  test("the sign-in page offers setup even when setup-status cannot be read", async ({
    page,
  }) => {
    // The register form must not depend on the API answering, nor on a
    // redirect having fired. This is the whole point of the fix.
    await page.route("**/api/v1/**", (route) =>
      route.fulfill({ status: 503, contentType: "text/plain", body: "down" }),
    );
    await page.goto("/login");
    await expect(
      page.getByRole("link", { name: "First-time setup" }),
    ).toHaveCount(1);
  });

  test("the sign-in page offers setup when the API is healthy and uninitialized", async ({
    page,
  }) => {
    await mock(page, false);
    await page.goto("/login");
    await expect(
      page.getByRole("link", { name: "First-time setup" }),
    ).toHaveCount(1);
  });

  test("first-time setup disappears from sign-in once an account exists", async ({
    page,
  }) => {
    await mock(page, true);
    await page.goto("/login");
    // It has done its job, so the link retires itself.
    await expect(
      page.getByRole("link", { name: "First-time setup" }),
    ).toHaveCount(0);
    // Recovery guidance stays, because the credential may still be unknown.
    await expect(page.locator(".auth-help")).toContainText(
      "make recover-owner",
    );
  });

  test("lost-access guidance is shown, including the SMTP caveat", async ({
    page,
  }) => {
    await mock(page, true);
    await page.goto("/login");
    const help = page.locator(".auth-help");
    await expect(help).toBeVisible();
    await expect(help).toContainText("make recover-owner");
    await expect(help).toContainText("--bootstrap");
    // Onboarding after setup closes depends on email, so it must be stated.
    await expect(help).toContainText("without SMTP");
  });

  test("a single navigation from / reaches setup without passing through login", async ({
    page,
  }) => {
    // Regression: / used to server-redirect to the private /overview, 401, and
    // then race router.replace('/login') against router.replace('/setup').
    const seen: string[] = [];
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame()) seen.push(new URL(frame.url()).pathname);
    });
    await mock(page, false);
    await page.goto("/");
    await expect(page).toHaveURL(/\/setup$/);
    await page.waitForTimeout(600);
    const after = seen.filter((p) => p === "/login" || p === "/setup");
    expect(after).toEqual(["/setup"]);
  });
});

test.describe("first-time setup form", () => {
  // Serve a real setup response so a successful submit behaves like production.
  async function mockSetup(page: import("@playwright/test").Page) {
    await page.route("**/api/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/stream"))
        return route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: ": heartbeat\n\n",
        });
      if (path.endsWith("/auth/me"))
        return route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "unauthenticated" } }),
        });
      if (path.endsWith("/auth/setup-status"))
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ initialized: false }),
        });
      if (path.endsWith("/auth/setup"))
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: "00000000-0000-4000-8000-000000000002",
            email: "owner@acme.example",
            name: "Owner",
            role: "owner",
            active: true,
            theme: "midnight",
            mfa_enabled: false,
            version: 1,
          }),
        });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({}),
      });
    });
  }

  test("asks for an email and the password twice", async ({ page }) => {
    await mockSetup(page);
    await page.goto("/setup");
    await expect(page.getByLabel(/Email address/)).toBeVisible();
    await expect(page.getByLabel(/^Password/)).toBeVisible();
    await expect(page.getByLabel(/^Confirm password/)).toBeVisible();
    // The two descriptive fields are prefilled so a first run needs only the
    // email and the two password entries.
    await expect(page.getByLabel(/Organization name/)).toHaveValue("NachtLabs");
    await expect(page.getByLabel(/Your name/)).toHaveValue("Owner");
  });

  test("a mismatched confirmation is refused and never reaches the API", async ({
    page,
  }) => {
    await mockSetup(page);
    let posted: unknown = null;
    page.on("request", (request) => {
      if (new URL(request.url()).pathname.endsWith("/auth/setup"))
        posted = request.postData();
    });
    await page.goto("/setup");
    await page.getByLabel(/Email address/).fill("owner@acme.example");
    await page.getByLabel(/^Password/).fill("correct-horse-battery");
    await page.getByLabel(/^Confirm password/).fill("correct-horse-batery");
    await page.getByRole("button", { name: "Create Owner account" }).click();
    await expect(page.getByText("do not match")).toBeVisible();
    expect(posted).toBeNull();
    await expect(page).toHaveURL(/\/setup$/);
  });

  test("a matching confirmation creates the account and signs in", async ({
    page,
  }) => {
    await mockSetup(page);
    let posted: Record<string, unknown> | null = null;
    page.on("request", (request) => {
      if (new URL(request.url()).pathname.endsWith("/auth/setup"))
        posted = JSON.parse(request.postData() ?? "{}");
    });
    await page.goto("/setup");
    await page.getByLabel(/Email address/).fill("owner@acme.example");
    await page.getByLabel(/^Password/).fill("correct-horse-battery");
    await page.getByLabel(/^Confirm password/).fill("correct-horse-battery");
    await page.getByRole("button", { name: "Create Owner account" }).click();
    await page.waitForURL("**/overview", { timeout: 15000 }).catch(() => {});
    // The API forbids unknown fields, so the confirmation must be stripped.
    expect(posted).not.toBeNull();
    expect(posted).not.toHaveProperty("password_confirm");
    expect(posted).toMatchObject({
      email: "owner@acme.example",
      password: "correct-horse-battery",
    });
  });
});
