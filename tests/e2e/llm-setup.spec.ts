import { test, expect } from "@playwright/test";

/*
  The setup wizard in a real browser. /llm-readiness and the writes it performs
  are mocked, because a genuinely uninitialized installation needs its own
  database. What is being checked is the routing, the honesty of the blocked
  states, and that a lapsed confirmation returns the operator to where they
  were instead of stranding them.
*/

const id = "00000000-0000-4000-8000-000000000002";

const owner = {
  id,
  email: "owner@acme.example",
  name: "Tom",
  role: "owner",
  active: true,
  theme: "canvas",
  version: 1,
  mfa_enabled: false,
  mfa_required: false,
};

const empty = {
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
};

type Readiness = typeof empty;

async function mock(
  page: import("@playwright/test").Page,
  readiness: Partial<Readiness> = {},
  options: { refuseWrite?: boolean; allowHttpPrivate?: boolean } = {},
) {
  const posted: { path: string; body: unknown }[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
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
        body: JSON.stringify(owner),
      });
    // The wizard reads the cleartext permission from here rather than assuming
    // it, so a test has to be able to state both answers.
    if (path.endsWith("/auth/preflight"))
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          allow_http_private: options.allowHttpPrivate === true,
        }),
      });
    if (path.endsWith("/llm-readiness"))
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...empty, ...readiness }),
      });
    if (path.endsWith("/integrations") && route.request().method() === "GET")
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    // The probe history is a list; answering {} would be a malformed payload,
    // not a discovery result.
    if (path.endsWith("/probes"))
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    if (route.request().method() !== "GET") {
      posted.push({
        path: path.replace("/api/v1", ""),
        body: route.request().postData(),
      });
      if (options.refuseWrite)
        return route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({
            error: {
              code: "reauth_required",
              message: "Confirm your password in Security settings and retry",
            },
          }),
        });
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id, version: 1 }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    });
  });
  return posted;
}

test.describe("llm setup wizard", () => {
  test("an owner reaches it from the profile menu", async ({ page }) => {
    await mock(page);
    await page.goto("/overview");
    await page.locator(".user-menu summary").click();
    await expect(
      page.getByRole("link", { name: "LLM setup wizard" }),
    ).toHaveCount(1);
    await page.getByRole("link", { name: "LLM setup wizard" }).click();
    await expect(page).toHaveURL(/\/llm-setup$/);
  });

  test("a non-admin is not offered the wizard", async ({ page }) => {
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
          body: JSON.stringify({ ...owner, role: "viewer" }),
        });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({}),
      });
    });
    await page.goto("/overview");
    await page.locator(".user-menu summary").click();
    await expect(
      page.getByRole("link", { name: "LLM setup wizard" }),
    ).toHaveCount(0);
    await page.goto("/llm-setup");
    await expect(
      page.getByText(/Owner or Admin access is required/),
    ).toBeVisible();
  });

  test("a fresh installation starts on the endpoint step, not a password prompt", async ({
    page,
  }) => {
    // A sign-in already opened a ten-minute write window, so demanding a
    // password before the operator may even look would be wrong.
    await mock(page);
    await page.goto("/llm-setup");
    await expect(
      page.getByRole("heading", { name: "Model endpoint" }),
    ).toBeVisible();
    await expect(page.getByLabel(/Connection name/)).toBeVisible();
    await expect(page.getByLabel(/Current password/)).toHaveCount(0);
  });

  test("overview prompts without redirecting away", async ({ page }) => {
    await mock(page);
    const seen: string[] = [];
    page.on("framenavigated", (f) => {
      if (f === page.mainFrame()) seen.push(new URL(f.url()).pathname);
    });
    await page.goto("/overview");
    await expect(
      page.getByRole("heading", { name: "Finish setting up your LLM" }),
    ).toBeVisible();
    await page.waitForTimeout(500);
    // The app elsewhere refuses to move an operator out from under a click.
    expect(seen.filter((p) => p === "/llm-setup")).toEqual([]);
  });

  test("the overview prompt disappears once configured", async ({ page }) => {
    await mock(page, {
      complete: true,
      connection: {
        id: "c1",
        name: "Ollama",
        active: true,
        version: 1,
        loopback_pinned: false,
        cleartext_endpoint: false,
      },
      distinct_models: true,
      implementation_profile: { id: "p1", model: "a" },
      verifier_profile: { id: "p2", model: "b" },
      agent: {
        id: "a1",
        name: "Hermes",
        provider: "hermes",
        executable: "/usr/local/bin/hermes",
      },
    });
    await page.goto("/overview");
    await expect(
      page.getByRole("heading", { name: "Finish setting up your LLM" }),
    ).toHaveCount(0);
    await expect(page.getByText("Model and agent configuration")).toBeVisible();
  });

  test("a blocked check names the switch instead of offering a dead button", async ({
    page,
  }) => {
    await mock(page, {
      provider_network_enabled: false,
      connection: {
        id: "c1",
        name: "Ollama",
        active: true,
        version: 1,
        loopback_pinned: false,
        cleartext_endpoint: false,
      },
    });
    await page.goto("/llm-setup");
    await expect(
      page.getByText(/Blocked by installation policy/),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Request connection check" }),
    ).toHaveCount(0);
    await expect(
      page.getByText(/NACHTLABS_INTEGRATION_NETWORK_ENABLED/).first(),
    ).toBeVisible();
  });

  test("a loopback endpoint is flagged as unusable for agent execution", async ({
    page,
  }) => {
    await mock(page, {
      connection: {
        id: "c1",
        name: "Ollama",
        active: true,
        version: 1,
        loopback_pinned: true,
        cleartext_endpoint: false,
      },
    });
    await page.goto("/llm-setup");
    await expect(page.getByText(/pinned to a loopback address/)).toBeVisible();
    await expect(page.getByText(/executor_network_policy/)).toBeVisible();
  });

  test("a completed chain still refuses to claim execution", async ({
    page,
  }) => {
    await mock(page, {
      complete: true,
      connection: {
        id: "c1",
        name: "Ollama",
        active: true,
        version: 1,
        loopback_pinned: false,
        cleartext_endpoint: false,
      },
      discovery: {
        state: "succeeded",
        models: [{ name: "m", digest: null }],
        checked_at: "2026-01-01T00:00:00Z",
      },
      implementation_profile: { id: "p1", model: "a" },
      verifier_profile: { id: "p2", model: "b" },
      agent: {
        id: "a1",
        name: "Hermes",
        provider: "hermes",
        executable: "/usr/local/bin/hermes",
      },
      distinct_models: true,
    });
    await page.goto("/llm-setup");
    await expect(
      page.getByRole("heading", { name: "Where this stands" }),
    ).toBeVisible();
    await expect(page.getByText("Unverified")).toBeVisible();
    await expect(
      page.getByText("Requires operator qualification"),
    ).toBeVisible();
  });

  test("a lapsed confirmation returns to the confirmation step", async ({
    page,
  }) => {
    // Regression guard: this used to leave a bare 403 with no route forward.
    await mock(page, {}, { refuseWrite: true });
    await page.goto("/llm-setup");
    await page.getByLabel(/Connection name/).fill("Home Ollama");
    await page.getByRole("button", { name: "Save endpoint" }).click();
    await expect(page.getByLabel(/Current password/)).toBeVisible();
    await expect(page.getByText(/confirmation expired/)).toBeVisible();
    await expect(page).toHaveURL(/\/llm-setup$/);
  });
});

test.describe("connecting a remote model endpoint", () => {
  // The operator's own report: a LAN Ollama submitted as plain HTTP came back as
  // "Check the indicated fields", which names no field and says nothing about
  // what to change. The API cannot report why, so the form has to.
  async function mockProvider(page: import("@playwright/test").Page) {
    await page.route("**/api/v1/integrations", async (route) => {
      if (route.request().method() === "GET")
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: "[]",
        });
      // Whatever the form sends, the server answers exactly as it does in
      // production: one opaque refusal, or a created connection.
      const body = JSON.parse(route.request().postData() ?? "{}");
      const accepted = String(body.base_url ?? "").startsWith("https://");
      return accepted
        ? route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify({ id: "c1", version: 1 }),
          })
        : route.fulfill({
            status: 422,
            contentType: "application/json",
            body: JSON.stringify({
              error: {
                code: "validation",
                message: "Check the indicated fields",
                fields: ["body"],
              },
            }),
          });
    });
  }

  test("a plain-HTTP LAN endpoint is explained instead of refused opaquely", async ({
    page,
  }) => {
    await mock(page, {});
    await mockProvider(page);
    await page.goto("/llm-setup");
    await page.getByLabel(/Connection name/).fill("LAN Ollama");
    await page
      .getByLabel(/Model endpoint origin/)
      .fill("http://192.168.1.50:11434");
    await page.getByLabel(/Pinned server IP/).fill("192.168.1.50");
    await page.getByRole("button", { name: "Save endpoint" }).click();
    // Names the field's rule, the offending address, and the way out.
    const error = page.locator("p.error");
    await expect(error).toContainText(
      /Plain HTTP is only accepted for a loopback/,
    );
    await expect(error).toContainText("https://");
    await expect(error).toContainText("192.168.1.50");
    // And explicitly not the generic message it replaced.
    await expect(error).not.toContainText("Check the indicated fields");
  });

  test("nothing is sent to the API for a shape the server would refuse", async ({
    page,
  }) => {
    // Caught before the round trip, so no account or connection is at risk and no
    // meaningless request is made.
    await mock(page, {});
    await mockProvider(page);
    let posted = 0;
    page.on("request", (r) => {
      if (
        new URL(r.url()).pathname.endsWith("/auth/integrations") ||
        new URL(r.url()).pathname.endsWith("/integrations")
      )
        if (r.method() !== "GET") posted += 1;
    });
    await page.goto("/llm-setup");
    await page
      .getByLabel(/Model endpoint origin/)
      .fill("http://192.168.1.50:11434");
    await page.getByLabel(/Pinned server IP/).fill("192.168.1.50");
    await page.getByRole("button", { name: "Save endpoint" }).click();
    await expect(page.locator("p.error")).toBeVisible();
    await page.waitForTimeout(600);
    expect(posted).toBe(0);
  });

  test("the same endpoint over https is accepted on the first try", async ({
    page,
  }) => {
    // The shape the API accepts, which is the whole point: a working
    // configuration must not look impossible.
    await mock(page, {});
    await mockProvider(page);
    await page.goto("/llm-setup");
    await page.getByLabel(/Connection name/).fill("LAN Ollama");
    await page.getByLabel(/Model endpoint origin/).fill("https://192.168.1.50");
    await page.getByLabel(/Pinned server IP/).fill("192.168.1.50");
    await page.getByRole("button", { name: "Save endpoint" }).click();
    await expect(page.getByText(/Endpoint saved/)).toBeVisible({
      timeout: 15000,
    });
  });

  test("a missing private permission is named rather than swallowed", async ({
    page,
  }) => {
    await mock(page, {});
    await mockProvider(page);
    await page.goto("/llm-setup");
    await page.getByLabel(/Model endpoint origin/).fill("https://192.168.1.50");
    await page.getByLabel(/Pinned server IP/).fill("192.168.1.50");
    // Default is Yes, so turn it off to exercise the rule.
    await page
      .getByLabel(/Permit this private or loopback/)
      .selectOption("false");
    await page.getByRole("button", { name: "Save endpoint" }).click();
    await expect(page.locator("p.error")).toContainText(
      /Permit this private or loopback/,
    );
  });

  test("the origin help states the cleartext rule before anything is typed", async ({
    page,
  }) => {
    // The rule used to live only in a different field's help text, which is how
    // an operator ends up composing a shape that cannot work.
    await mock(page, {});
    await page.goto("/llm-setup");
    const help = page.locator(".field", { hasText: "Model endpoint origin" });
    await expect(help).toContainText(/https:\/\//);
    await expect(help).toContainText(/loopback/);
    // And the operator's own network is now a named case, not an omission.
    await expect(help).toContainText(/ALLOW_HTTP_PRIVATE/);
  });

  test("cleartext to a private address is refused by default and named", async ({
    page,
  }) => {
    // The permissions the form does offer, set, and the installation has not
    // permitted cleartext. This is the shape an operator is most likely to
    // reach for, so the message has to name the switch rather than the fact
    // that the address is not loopback.
    await mock(page, {});
    await mockProvider(page);
    await page.goto("/llm-setup");
    await page
      .getByLabel(/Model endpoint origin/)
      .fill("http://192.168.1.50:11434");
    await page.getByLabel(/Pinned server IP/).fill("192.168.1.50");
    await page.getByLabel(/Permit this private or loopback address/).check();
    await page.getByLabel(/Permit HTTP for this loopback endpoint/).check();
    await page.getByRole("button", { name: "Save endpoint" }).click();
    const error = page.locator("p.error");
    await expect(error).toContainText(
      /does not permit cleartext to a private address/,
    );
    await expect(error).toContainText(
      "NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE",
    );
    await expect(error).toContainText("https://");
  });

  test("the same endpoint is accepted once the installation permits cleartext", async ({
    page,
  }) => {
    // The shape that used to be impossible. It has to work end to end, or the
    // refusal above is the whole story and the setting does nothing.
    await mock(page, {}, { allowHttpPrivate: true });
    await mockProvider(page);
    await page.goto("/llm-setup");
    await page
      .getByLabel(/Model endpoint origin/)
      .fill("http://192.168.1.50:11434");
    await page.getByLabel(/Pinned server IP/).fill("192.168.1.50");
    await page.getByLabel(/Permit this private or loopback address/).check();
    await page.getByLabel(/Permit HTTP for this loopback endpoint/).check();
    await page.getByRole("button", { name: "Save endpoint" }).click();
    await expect(page.locator("p.error")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Request connection check" }),
    ).toBeVisible();
  });

  test("cleartext to a public address is refused even when the switch is on", async ({
    page,
  }) => {
    // The switch reaches the operator's own network and no further, and the
    // client has to agree with the server about that or it waves past a shape
    // the API will reject at save time.
    await mock(page, {}, { allowHttpPrivate: true });
    await mockProvider(page);
    let posted = 0;
    page.on("request", (r) => {
      if (
        r.method() !== "GET" &&
        new URL(r.url()).pathname.endsWith("/integrations")
      )
        posted += 1;
    });
    await page.goto("/llm-setup");
    await page.getByLabel(/Model endpoint origin/).fill("http://93.184.216.34");
    await page.getByLabel(/Pinned server IP/).fill("93.184.216.34");
    await page.getByLabel(/Permit HTTP for this loopback endpoint/).check();
    await page.getByRole("button", { name: "Save endpoint" }).click();
    await expect(page.locator("p.error")).toContainText(/never permitted/);
    await page.waitForTimeout(600);
    expect(posted).toBe(0);
  });
});
