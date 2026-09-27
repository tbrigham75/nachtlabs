import { test, expect } from "@playwright/test";

/*
  The origin diagnosis in a real browser. Reaching the application on a second
  address is the whole point of the permitted set, and the failure mode when it
  is not permitted is silent and confusing, so both are pinned here.
*/

const id = "00000000-0000-4000-8000-000000000002";

async function mock(
  page: import("@playwright/test").Page,
  allowed: string[],
  secure = true,
) {
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
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id,
          name: "Tom",
          email: "owner@acme.example",
          role: "owner",
          active: true,
          theme: "canvas",
          version: 1,
          mfa_enabled: false,
          mfa_required: false,
        }),
      });
    if (path.endsWith("/auth/preflight"))
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          // A same-origin GET sends no Origin header, so this is what a healthy
          // installation genuinely reports from inside the browser.
          origin: null,
          expected: allowed[0] ?? "",
          allowed,
          origin_accepted: false,
          secure_cookies: secure,
          setup_token_required: false,
          initialized: true,
          hint: null,
        }),
      });
    if (path.endsWith("/auth/setup-status"))
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ initialized: true }),
      });
    // These screens fetch lists and read fields off their payload, so a bare {}
    // from the catch-all below would crash them into the route error boundary
    // and take the shell, and with it the banner, off the page.
    if (path.endsWith("/projects") || path.endsWith("/integrations"))
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    if (path.endsWith("/organization"))
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          name: "Home",
          require_admin_mfa: false,
          version: 1,
        }),
      });
    if (path.endsWith("/llm-readiness"))
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          provider_network_enabled: false,
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
        }),
      });
    if (path.endsWith("/overview"))
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ worker: "online" }),
      });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    });
  });
}

test.describe("permitted origins", () => {
  test("a permitted second address shows no warning at all", async ({
    page,
  }) => {
    // The regression that matters most. preflight reports origin_accepted false
    // here because a same-origin GET carries no Origin header, so a banner
    // driven by that field would appear for a completely healthy installation.
    await mock(page, ["http://127.0.0.1:3000", "https://nacht.lan"]);
    await page.goto("/overview");
    await expect(
      page.getByRole("heading", { name: "Engineering overview" }),
    ).toBeVisible();
    await expect(page.getByText(/cannot save anything/)).toHaveCount(0);
    await expect(page.getByText(/cannot be marked Secure/)).toHaveCount(0);
  });

  test("an address that is not permitted is named, with the fix", async ({
    page,
  }) => {
    await mock(page, ["https://nacht.lan"]);
    await page.goto("/overview");
    const banner = page.locator("p.notice.error");
    await expect(banner).toBeVisible();
    // The address in the browser, the addresses that work, and the setting.
    await expect(banner).toContainText("127.0.0.1");
    await expect(banner).toContainText("https://nacht.lan");
    await expect(banner).toContainText("NACHTLABS_ALLOWED_ORIGINS");
  });

  test("a cleartext cookie is called out only when it is a live concern", async ({
    page,
  }) => {
    await mock(page, ["http://localhost:3000"], false);
    await page.goto("/overview");
    await expect(page.getByText(/cannot be marked Secure/)).toBeVisible();
  });

  test("the warning is not offered when every origin is HTTPS", async ({
    page,
  }) => {
    await mock(page, ["https://nacht.lan"], true);
    await page.goto("/overview");
    await expect(page.locator("p.notice.error")).toHaveCount(0);
  });

  test("the banner applies to any screen, not only the wizard", async ({
    page,
  }) => {
    // The failure is not specific to one screen, so the diagnosis is not either.
    await mock(page, ["https://nacht.lan"]);
    for (const path of [
      "/overview",
      "/llm-setup",
      "/integrations",
      "/settings",
    ]) {
      await page.goto(path);
      await expect(page.getByText(/cannot save anything/)).toBeVisible();
    }
  });

  test("an operator can still read the interface while blocked", async ({
    page,
  }) => {
    // Nothing was lost, so nothing should be withheld: the page renders and
    // navigation still works.
    await mock(page, ["https://nacht.lan"]);
    await page.goto("/overview");
    await expect(
      page.getByRole("heading", { name: "Engineering overview" }),
    ).toBeVisible();
    await page.getByRole("link", { name: "Projects" }).first().click();
    await expect(page).toHaveURL(/\/projects/);
  });
});
