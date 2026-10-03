"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  CircleDashed,
  Lock,
  Server,
  Terminal,
  TriangleAlert,
} from "lucide-react";
import {
  api,
  ApiError,
  write,
  type LlmReadiness,
  type SetupPreflight,
  type User,
} from "@nachtlabs/api-client";
import {
  Action,
  Badge,
  ErrorNotice,
  Form,
  FormInterruption,
  Heading,
  Loading,
  type Field,
} from "@/components/ui";
import {
  derivePin,
  originName,
  isGlobalIp,
  isLoopbackIp,
  parseIp,
  NEVER_PERMITTED,
} from "./endpoint-address";
import type { Connection, Probe } from "./integration-types";

/*
  Guided setup for the model/agent chain, in the order the API enforces:
  connection -> discovery -> implementation and verifier profiles -> agent.

  Two rules shape this screen. First, configuration is not capability: a saved
  connection is not a working one, a successful discovery is not a compatibility
  proof, and execution stays unavailable because it depends on a root-owned
  qualification the API cannot observe. Nothing here may imply otherwise.

  Second, this wizard cannot do two things an operator needs. It cannot enable
  provider network access, which is an installation switch in /etc/nachtlabs, and
  it cannot qualify the executor, which needs root on the host. Where a step is
  blocked by one of those, the wizard names the exact host-console action instead
  of offering a button that cannot work.
*/

type Step =
  | "confirm"
  | "connection"
  | "discovery"
  | "profiles"
  | "agent"
  | "execution"
  | "done";

const steps: { id: Step; title: string }[] = [
  { id: "confirm", title: "Confirm identity" },
  { id: "connection", title: "Model endpoint" },
  { id: "discovery", title: "Connection check" },
  { id: "profiles", title: "Model profiles" },
  { id: "agent", title: "Coding agent" },
  { id: "execution", title: "Execution on the host" },
  { id: "done", title: "Summary" },
];

// The origin the form starts on, and the value the pin derives from before the
// operator types anything. Named so the form default and the derivation seed are
// the same string rather than two literals that can drift apart.
const DEFAULT_ORIGIN = "http://127.0.0.1:11434";

const booleans = [
  { value: "false", label: "No" },
  { value: "true", label: "Yes" },
];

/** The first step that still needs work, so the wizard always resumes rather
 * than restarting an operator who has already configured half of it. */
function firstIncompleteStep(ready: LlmReadiness): Step {
  if (ready.complete) return "done";
  if (!ready.connection?.active) return "connection";
  if (ready.discovery.state !== "succeeded") return "discovery";
  if (
    !ready.implementation_profile ||
    !ready.verifier_profile ||
    !ready.distinct_models
  )
    return "profiles";
  if (!ready.agent) return "agent";
  return "done";
}

export function LlmSetupScreen({ user }: { user: User }) {
  const admin = ["owner", "admin"].includes(user.role);
  const client = useQueryClient();
  const [step, setStep] = useState<Step | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [expired, setExpired] = useState(false);
  const [resumeStep, setResumeStep] = useState<Step | null>(null);
  // The origin as typed, so a notice outside the endpoint form can tell an
  // https entry from a cleartext one before anything has been saved.
  const [draftBaseUrl, setDraftBaseUrl] = useState("");
  const ready = useQuery({
    queryKey: ["llm-readiness"],
    queryFn: () => api<LlmReadiness>("/llm-readiness"),
    enabled: admin,
    refetchInterval: (query) =>
      step === "discovery" ||
      ["pending", "running"].includes(query.state.data?.discovery.state ?? "")
        ? 5000
        : false,
  });
  const connections = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api<Connection[]>("/integrations"),
    enabled: admin,
  });
  // Shared cache key with the sign-in screen's own preflight query, so the two
  // dedupe into one request. Only used here for the cleartext permission.
  const preflight = useQuery({
    queryKey: ["auth-preflight"],
    queryFn: () => api<SetupPreflight>("/auth/preflight"),
    staleTime: 30_000,
    retry: 1,
  });
  const allowPrivateHttp = preflight.data?.allow_http_private === true;
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["llm-readiness"] });
    await client.invalidateQueries({ queryKey: ["integrations"] });
    await client.invalidateQueries({ queryKey: ["model-profiles"] });
    await client.invalidateQueries({ queryKey: ["agents"] });
  };
  if (!admin)
    return (
      <ErrorNotice error={new Error("Owner or Admin access is required")} />
    );
  if (ready.isPending) return <Loading />;
  if (ready.error && !ready.data) return <ErrorNotice error={ready.error} />;

  const state = ready.data!;
  const active = step ?? firstIncompleteStep(state);
  const index = steps.findIndex((s) => s.id === active);
  const setStepAnd = async (next: Step) => {
    await refresh();
    setStep(next);
  };
  /*
    A sign-in already opens a ten-minute write window, so demanding a password
    before the operator may even look at the wizard would be wrong. But the
    window can lapse mid-flow, and a bare 403 there would dead-end the wizard
    with the form contents lost and no route forward. Every write goes through
    this instead: on expiry it moves to the confirmation step, which then
    resumes at the interrupted step with its draft still mounted.
  */
  const guard = async <T,>(action: () => Promise<T>): Promise<T> => {
    // Pin the current step before invalidation changes the derived readiness.
    setStep(active);
    try {
      return await action();
    } catch (error) {
      /*
        Matched on the message, not the code. The identical refusal is reported
        as "origin" on the pre-authentication routes and as "csrf" on the
        authenticated ones, and this wizard's writes go through the latter, so a
        code check for "origin" alone would never fire here. "csrf" on its own
        is ambiguous, since the CSRF token check reuses it, so both parts have
        to match.
      */
      if (
        error instanceof ApiError &&
        (error.code === "origin" || error.code === "csrf") &&
        /origin is not permitted/i.test(error.message)
      ) {
        const here =
          typeof window === "undefined"
            ? "this address"
            : window.location.origin;
        throw new Error(
          `${here} is not an origin this installation accepts, so nothing was ` +
            `saved. An operator must add it to NACHTLABS_ALLOWED_ORIGINS and ` +
            `restart the API, then reload this page.`,
        );
      }
      if (error instanceof ApiError && error.code === "reauth_required") {
        setResumeStep(active);
        setConfirmed(false);
        setStep("confirm");
        setExpired(true);
        throw new FormInterruption(
          "Your ten-minute confirmation expired. Confirm your identity to carry on; this step will still be waiting.",
        );
      }
      throw error;
    }
  };

  return (
    <>
      <Heading
        title="LLM setup wizard"
        note="Connect a model endpoint, prove it answers, and bind a coding agent to it. Steps follow the order the API enforces."
      />
      <nav className="tabs" aria-label="Setup progress">
        {steps.map((s, i) => (
          <button
            key={s.id}
            className={s.id === active ? "active" : ""}
            onClick={() => setStep(s.id)}
            aria-current={s.id === active ? "step" : undefined}
          >
            {i + 1}. {s.title}
          </button>
        ))}
      </nav>
      {!state.provider_network_enabled && (
        <p className="notice warning" role="status">
          <strong>
            <TriangleAlert size={15} /> Provider checks are disabled by
            installation policy.
          </strong>{" "}
          Setting a connection and a model profile still works and is stored
          normally, but nothing can be discovered and no model can be called
          until an operator sets{" "}
          <code>NACHTLABS_INTEGRATION_NETWORK_ENABLED=true</code> in the
          deployment and restarts the API and the worker. In the container
          install that is{" "}
          <code>
            NACHTLABS_REWRITE_CONFIG=true docker compose run --rm init
          </code>
          , then <code>docker compose restart api worker</code>. The interface
          deliberately cannot enable this itself. Step 3 will stay blocked until
          then.
        </p>
      )}
      {/*
        A certificate is only ever consulted for an https origin: the transport
        builds no TLS context at all for cleartext. This notice therefore said
        something false on the most common local configuration there is, so it is
        scoped to the scheme that actually has a certificate. The saved connection
        is authoritative when there is one; before that, the typed origin decides,
        and nothing is claimed until an https:// has actually been entered.
      */}
      {(state.connection === null
        ? draftBaseUrl.trim().toLowerCase().startsWith("https://")
        : !state.connection.cleartext_endpoint) && (
        <p className="notice" role="status">
          <strong>
            Two things to know before an https endpoint can answer.
          </strong>{" "}
          Its certificate must be one this installation trusts; if you use your
          own certificate authority, point{" "}
          <code>NACHTLABS_INTEGRATION_CA_FILE</code> at the CA bundle in the
          deployment configuration, because the discovery check and the planning
          call each build their own connection and setting it in only one of the
          two services is not enough. In the container install that is{" "}
          <code>
            NACHTLABS_REWRITE_CONFIG=true docker compose run --rm init
          </code>
          , then <code>docker compose restart api worker</code>. Separately,
          agents do not run against a private address until the root execution
          catalog lists it with <code>allow_private_network</code>, which
          re-opens the executor qualification.
        </p>
      )}
      {state.connection?.cleartext_endpoint && (
        <p className="notice warning" role="status">
          <strong>This endpoint is unprotected.</strong> It is cleartext, and it
          is not a loopback address, so this is the case that needs the an
          explicit decision rather than a default. Two things follow, and
          neither is visible in the interface afterwards:
          <br />
          <br />
          The work request, Mission, Journeys, allowed paths and validation
          commands and repository metadata are sent to this address{" "}
          <em>in the clear</em>, so anything on the network path can read them.
          <br />
          <br />
          The reply from the model is parsed as the plan and becomes the
          recorded plan for a governed run. With HTTPS, forging that needs the
          certificate key of the server. Here it needs only network position,
          and the pinned address is the only thing standing between a run and
          the network. A reverse proxy in front of a loopback Ollama keeps the
          traffic off the wire while still working, and is the stronger
          arrangement if the network is shared.
        </p>
      )}
      {state.connection?.loopback_pinned && (
        <p className="notice warning" role="status">
          <strong>
            <TriangleAlert size={15} /> This endpoint is pinned to a loopback
            address.
          </strong>{" "}
          That is permitted for control-plane discovery and planning. It
          <em>cannot</em> serve agent execution: the root execution catalog
          refuses loopback, metadata and link-local destinations, so an agent
          will fail with <code>executor_network_policy</code> until the model is
          exposed on a dedicated approved address.
        </p>
      )}
      {expired && (
        <p className="notice warning" role="status">
          Your ten-minute confirmation expired, so the last change was not
          saved. Confirm your identity and the wizard will return to the step it
          was on.
        </p>
      )}
      <ErrorNotice error={connections.error} />
      <ErrorNotice error={ready.error} />
      {active === "confirm" && (
        <ConfirmStep
          confirmed={confirmed}
          onConfirmed={async () => {
            setConfirmed(true);
            setExpired(false);
            await setStepAnd(resumeStep ?? firstIncompleteStep(state));
            setResumeStep(null);
          }}
        />
      )}
      {/* Keep non-secret drafts mounted while identity is reconfirmed. */}
      {(active === "connection" || resumeStep === "connection") && (
        <div hidden={active !== "connection"}>
          <ConnectionStep
            existing={state.connection}
            allowPrivateHttp={allowPrivateHttp}
            onDraftBaseUrl={setDraftBaseUrl}
            guard={guard}
            onDone={() => setStepAnd("discovery")}
          />
        </div>
      )}
      {active === "discovery" && (
        <DiscoveryStep
          state={state}
          guard={guard}
          onDone={refresh}
          onContinue={() => setStepAnd("profiles")}
        />
      )}
      {(active === "profiles" || resumeStep === "profiles") && (
        <div hidden={active !== "profiles"}>
          <ProfilesStep
            state={state}
            guard={guard}
            onSaved={refresh}
            onDone={() => setStepAnd("agent")}
          />
        </div>
      )}
      {(active === "agent" || resumeStep === "agent") && (
        <div hidden={active !== "agent"}>
          <AgentStep
            state={state}
            guard={guard}
            onDone={() => setStepAnd("execution")}
          />
        </div>
      )}
      {active === "execution" && (
        <ExecutionStep onDone={() => setStepAnd("done")} />
      )}
      {active === "done" && <Summary state={state} step={index} />}
      <p className="notice">
        Later changes live in <Link href="/integrations">Integrations</Link> and{" "}
        <Link href="/agents-models">Agents &amp; models</Link>. This wizard only
        creates; it never edits or deletes an existing record.
      </p>
    </>
  );
}

function StepPanel({
  title,
  icon: Icon,
  note,
  children,
}: {
  title: string;
  icon: typeof Server;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>
          <Icon size={18} /> {title}
        </h2>
      </div>
      {note && <p>{note}</p>}
      {children}
    </section>
  );
}

function ConfirmStep({
  confirmed,
  onConfirmed,
}: {
  confirmed: boolean;
  onConfirmed: () => Promise<void>;
}) {
  return (
    <StepPanel
      title="Confirm your identity"
      icon={Lock}
      note="Every step below writes configuration, and each write requires a password confirmation from the last ten minutes. Confirming once here gives the whole flow that window; you will be asked again only if it expires."
    >
      {confirmed ? (
        <p className="notice success" role="status">
          Identity confirmed for ten minutes.
        </p>
      ) : (
        <Form
          fields={[
            {
              name: "password",
              label: "Current password",
              type: "password",
              required: true,
            },
            {
              name: "code",
              label: "Fresh MFA or recovery code",
              type: "password",
              help: "Required when MFA is enabled on your account.",
            },
          ]}
          label="Confirm identity"
          submit={async (v) => {
            await write("/auth/reauthenticate", {
              password: v.password,
              code: v.code || null,
            });
            await onConfirmed();
          }}
        />
      )}
    </StepPanel>
  );
}

/*
  Client-side mirror of the server's Endpoint.validate().
*/
export type EndpointInput = {
  baseUrl: string;
  pin: string;
  allowPrivate: boolean;
  allowHttp: boolean;
  /** Whether this installation permits cleartext to a private address. */
  allowPrivateHttp: boolean;
};

/**
 * Everything the server is certain to refuse, said in terms the operator can act
 * on.
 *
 * This only ever rejects. It never rewrites what was typed and never relaxes a
 * requirement, so the server stays the authority and nothing it would accept is
 * blocked here. Every rule is deterministic rather than a judgement call, so a
 * disagreement can only ever be a bug and not a difference of opinion.
 *
 * It exists because the API cannot tell the operator why. Pydantic's own reason
 * is suppressed on purpose, since it can echo submitted values, which left a LAN
 * endpoint refused as "Check the indicated fields" with fields: ["body"] and no
 * indication of anything.
 */
export function endpointProblems(input: EndpointInput): string[] {
  const problems: string[] = [];
  const raw = input.baseUrl.trim();
  if (!raw) return ["Enter the model endpoint origin."];
  if (!/^https?:\/\//i.test(raw)) {
    return ["The origin must start with http:// or https://."];
  }
  if (/[@]/.test(raw.split("://")[1] ?? "")) {
    problems.push("The origin must not contain credentials.");
  }
  if (/[?#]/.test(raw)) {
    problems.push("The origin must not contain a query or fragment.");
  }
  const afterScheme = raw.slice(raw.indexOf("://") + 3);
  const path = afterScheme.split(/[?#]/)[0].replace(/^[^/]*\/?/, "");
  if (path) {
    problems.push(
      "The origin must not include a path, only scheme, host and port.",
    );
  }

  const pin = parseIp(input.pin);
  if (!pin) {
    problems.push(
      "The pinned address must be one numeric address such as 127.0.0.1, resolved on the host console.",
    );
    // Nothing further can be classified without an address.
    return problems;
  }
  if (NEVER_PERMITTED.has(input.pin.trim())) {
    problems.push(
      "That address is a cloud metadata destination and is never permitted.",
    );
    return problems;
  }
  if (!isGlobalIp(pin) && !input.allowPrivate) {
    problems.push(
      'That address is not publicly routable, so turn on "Permit this private or loopback address".',
    );
  }

  const host = afterScheme.split(":")[0].replace(/\/+$/, "");
  const urlIsIp = parseIp(host);
  if (urlIsIp && host !== input.pin.trim()) {
    problems.push(
      `The origin names the address ${host}, but the pin is ${input.pin.trim()}. They must be the same address, or the origin should use a hostname.`,
    );
  }
  // Keyed on the scheme in the origin, not on the permission flag. Both of the
  // server's http rules test the scheme, so an https endpoint is fine with the
  // flag left on, and rejecting that would block a configuration the API
  // accepts. An earlier version of this file keyed on the flag instead and
  // refused exactly the default https shape the wizard offers.
  if (raw.slice(0, raw.indexOf("://")).toLowerCase() === "http") {
    if (!input.allowHttp) {
      problems.push(
        'Turn on "Permit HTTP for this loopback endpoint", or use https:// instead.',
      );
    }
    if (!isLoopbackIp(pin)) {
      if (isGlobalIp(pin)) {
        // The switch reaches the operator's own network and no further, so this
        // is refused whatever is enabled.
        problems.push(
          `Plain HTTP to a publicly routable address is never permitted, and this one is ${input.pin.trim()}. Use https:// for it.`,
        );
      } else if (!input.allowPrivateHttp) {
        problems.push(
          input.allowPrivate
            ? `This installation does not permit cleartext to a private address, and this one is ${input.pin.trim()}. Use https:// for it, or set NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE=true in the deployment configuration and restart the API and the worker.`
            : `Plain HTTP is only accepted for a loopback address, and this one is ${input.pin.trim()}. Use https:// for it.`,
        );
      }
    }
  }
  return problems;
}

/*
  Why there is a second address box at all.

  The transport connects to the pinned number and never looks a name up, so the
  destination cannot be changed after the operator has seen it and said yes. The
  field is unfashionable next to the origin, which already names a host, and the
  cost of that duplication is not obvious from the label. It is explained here in
  plain terms rather than in the field's help, which has to stay short enough to
  be read, and the mechanism is left to
  packages/core/src/nachtlabs/integrations/transport.py.
*/
function PinExplainer() {
  return (
    <details className="notice">
      <summary>What is this second address box for?</summary>
      <p>
        <strong>In short:</strong> the address above says <em>where to go</em>,
        and this one says <em>exactly which machine that is</em>.
      </p>
      <p>
        <strong>If you typed a number above, this box fills itself in</strong>{" "}
        and you do not need to touch it. The server would refuse a different
        answer anyway, so asking you to type it twice could only ever produce a
        copy. A number already is the machine, so there is nothing left to look
        up.
      </p>
      <p>
        <strong>
          If you typed a name above, this box is the one that matters.
        </strong>{" "}
        Think of a name in a phone book. If you call “Ollama”, somebody looks
        the name up in a book to find a number. The lookup happens again every
        single time, and anyone who can edit that book can quietly change which
        number you reach. A “pin” is a phone number written down once, so there
        is no lookup to tamper with. A name is also what a secure certificate
        can be issued for, which a number cannot easily be — so when you use a
        name, this box is where you say what the name means <em>today</em>.
      </p>
      <p>
        <strong>Which address is it, then?</strong> It is the model server’s,
        not this machine’s. If you typed <code>192.168.1.50</code> above, this
        fills in as <code>192.168.1.50</code> on its own. On the host console,{" "}
        <code>ip addr</code> shows the numbers.
      </p>
      <p>
        <strong>Why can I not type a name in this box?</strong> Because a name
        would need looking up, which is the thing being removed.
      </p>
    </details>
  );
}

function ConnectionStep({
  existing,
  allowPrivateHttp,
  onDraftBaseUrl,
  guard,
  onDone,
}: {
  existing: LlmReadiness["connection"];
  allowPrivateHttp: boolean;
  onDraftBaseUrl: (value: string) => void;
  guard: <T>(action: () => Promise<T>) => Promise<T>;
  onDone: () => void;
}) {
  const [created, setCreated] = useState<string | null>(null);
  // The origin as typed, so the pin can be derived from it. A number there
  // means the server refuses any pin that differs, so the field fills itself; a
  // name means the two do different jobs and the operator has to supply the
  // address. See derivePin.
  //
  // Seeded from the form's default rather than from `existing`: this screen
  // deliberately creates a new endpoint instead of editing one, so the saved
  // connection's origin is not what is being typed here, and readiness does not
  // carry a base_url to seed from in the first place.
  const [originDraft, setOriginDraft] = useState(DEFAULT_ORIGIN);
  const pinHost = derivePin(originDraft);
  const originHost = originName(originDraft);
  const fields: Field[] = [
    { name: "name", label: "Connection name", required: true, max: 120 },
    {
      name: "base_url",
      label: "Model endpoint origin",
      required: true,
      help: "Scheme, host and port only. https:// works for any address. Plain HTTP works for a loopback address such as http://127.0.0.1:11434, and for an address on your own network only when the operator has enabled NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE.",
    },
    {
      name: "address",
      // The label and the help both follow whether the origin is a number or a
      // name, because that is what decides what this box is for.
      //
      // derivePin is non-null exactly when the origin is a number: the value is
      // then derived and this is a readback of the origin, so it keeps the plain
      // "Pinned server IP" label and the help says where the value came from.
      // When the origin is a name there is nothing to derive, the operator is
      // genuinely pinning, and the label has to say what the number must be the
      // address of.
      label:
        pinHost !== null
          ? "Pinned server IP"
          : `The address ${originHost} means right now`,
      required: true,
      readOnly: pinHost !== null,
      help:
        pinHost !== null
          ? "Taken from the origin above. This is where the messages are sent — not an address on this machine."
          : "Write the number this name points to today. Nothing looks the name up, so nothing can change what it means later. A name behind a CDN needs this refreshed when the address changes.",
    },
    {
      name: "allow_private",
      label: "Permit this private or loopback address",
      options: booleans,
    },
    {
      name: "allow_http",
      label: "Permit HTTP for this loopback endpoint",
      options: booleans,
      help: "Required for any cleartext endpoint. A publicly routable address still requires HTTPS even when cleartext to your own network is enabled, and a cloud metadata destination is always rejected.",
    },
    {
      name: "timeout_seconds",
      label: "Per-request timeout (1-30 seconds)",
      type: "number",
      required: true,
    },
  ];
  return (
    <StepPanel
      title="Model endpoint"
      icon={Server}
      note="Ollama is the only model provider this release supports. ChatGPT, Claude, Grok and Codex are not yet available; adding them is planned and this screen is where they will appear."
    >
      {existing && (
        <p className="notice">
          <strong>{existing.name}</strong> already exists
          {existing.active ? " and is active" : " but is disabled"}. Enable or
          replace it from <Link href="/integrations">Integrations</Link>. This
          wizard creates a new endpoint rather than editing an existing one, so
          a mistake here cannot silently change a running configuration.
        </p>
      )}
      <PinExplainer />
      <Form
        fields={fields}
        initial={{
          name: "Local Ollama",
          base_url: DEFAULT_ORIGIN,
          // Left empty on purpose: the value arrives through derivedValues while
          // the origin is a number, so seeding it here would only duplicate the
          // one source of truth, and would leave a number sitting in the field
          // if the origin were ever a name.
          address: "",
          allow_private: "true",
          allow_http: "true",
          timeout_seconds: "15",
        }}
        label="Save endpoint"
        // Only supplied while the origin names a number. Dropping the entry the
        // moment it stops being derivable is what releases the field: the
        // operator's own value is left alone rather than cleared, so switching
        // from a number to a name mid-edit does not wipe what they typed.
        derivedValues={pinHost === null ? undefined : { address: pinHost }}
        onFieldChange={(name, value) => {
          if (name === "base_url") {
            setOriginDraft(value);
            onDraftBaseUrl(value);
          }
        }}
        submit={async (v) => {
          // Checked here so the operator is told what is wrong and how to fix
          // it, rather than receiving a refusal the API cannot explain.
          const problems = endpointProblems({
            baseUrl: v.base_url,
            pin: v.address,
            allowPrivate: v.allow_private === "true",
            allowHttp: v.allow_http === "true",
            allowPrivateHttp,
          });
          if (problems.length > 0) throw new Error(problems[0]);
          const connection = await guard(() =>
            write<{ id: string }>("/integrations", {
              name: v.name,
              provider: "ollama",
              base_url: v.base_url,
              pinned_addresses: [v.address.trim()],
              allow_private: v.allow_private === "true",
              allow_http: v.allow_http === "true",
              timeout_seconds: Number(v.timeout_seconds),
              active: true,
              expected_version: 0,
            }),
          );
          setCreated(connection.id);
        }}
      />
      {created && (
        <p className="notice success" role="status">
          Endpoint saved. Ollama needs no token; if yours sits behind a proxy,
          add an optional bearer token from{" "}
          <Link href="/integrations">Integrations</Link>. Continue to the
          connection check.
        </p>
      )}
      <div className="actions">
        <button className="primary" disabled={!created} onClick={onDone}>
          Continue to connection check
        </button>
      </div>
    </StepPanel>
  );
}

function DiscoveryStep({
  state,
  guard,
  onDone,
  onContinue,
}: {
  state: LlmReadiness;
  guard: <T>(action: () => Promise<T>) => Promise<T>;
  onDone: () => Promise<void>;
  onContinue: () => Promise<void>;
}) {
  const client = useQueryClient();
  const probes = useQuery({
    queryKey: ["probes", state.connection?.id],
    queryFn: () => api<Probe[]>(`/integrations/${state.connection!.id}/probes`),
    enabled: !!state.connection,
    refetchInterval: 5000,
  });
  const connection = state.connection;
  const busy =
    probes.data?.some((p) => p.state === "pending" || p.state === "running") ??
    false;
  const labels: Record<string, string> = {
    not_run: "Not run",
    pending: "Queued",
    running: "Running",
    succeeded: "Succeeded",
    failed: "Failed",
    stale: "Configuration changed since the last check",
    expired: "Older than 24 hours",
  };
  return (
    <StepPanel
      title="Connection check"
      icon={CircleDashed}
      note="A read-only discovery against /api/version and /api/tags. It contacts the model endpoint and changes nothing. The result is what tells you which model identifiers actually exist."
    >
      {!connection ? (
        <p className="notice error">Create a model endpoint first.</p>
      ) : !state.provider_network_enabled ? (
        <div className="notice warning">
          <p>
            <strong>Blocked by installation policy.</strong> This check sends
            provider traffic, and{" "}
            <code>NACHTLABS_INTEGRATION_NETWORK_ENABLED</code> is false. An
            operator must set it in the deployment configuration, then restart
            the API and the worker. In the container install:{" "}
            <code>
              NACHTLABS_REWRITE_CONFIG=true docker compose run --rm init
            </code>
            , then <code>docker compose restart api worker</code>. Keep the Git
            switch false.
          </p>
          <p>
            The interface cannot enable this, and will not pretend the endpoint
            works while it is off.
          </p>
        </div>
      ) : (
        <Action
          action={async () => {
            await guard(async () => {
              const fresh = await client.fetchQuery({
                queryKey: ["llm-readiness"],
                queryFn: () => api<LlmReadiness>("/llm-readiness"),
              });
              await write(`/integrations/${connection.id}/probes`, {
                expected_version:
                  fresh.connection?.version ?? connection.version,
                page: 1,
              });
              await client.invalidateQueries({
                queryKey: ["probes", connection.id],
              });
            });
            await onDone();
          }}
        >
          Request connection check
        </Action>
      )}
      <ul className="checklist">
        <li>
          Current state
          <Badge good={state.discovery.state === "succeeded"}>
            {labels[state.discovery.state] ?? state.discovery.state}
          </Badge>
        </li>
        <li>
          Models discovered
          <span>{state.discovery.models.length}</span>
        </li>
      </ul>
      {busy && <p className="notice">Awaiting the worker result…</p>}
      <ErrorNotice error={probes.error} />
      {probes.data?.map((p) => (
        <section className="history-item" key={p.id}>
          <div className="panel-head">
            <strong>{new Date(p.created_at).toLocaleString()}</strong>
            <Badge>{p.state}</Badge>
          </div>
          <p>
            {p.error_code ??
              (p.state === "succeeded"
                ? "Discovery completed. Compatibility and execution remain unverified."
                : "Awaiting worker result")}
          </p>
          {p.result.provider_version && (
            <p>Reported provider version: {p.result.provider_version}</p>
          )}
        </section>
      ))}
      {state.discovery.state === "succeeded" &&
        state.discovery.models.length > 0 && (
          <p>
            <strong>Available models.</strong> You need at least two different
            ones: implementation and verification must not share a model.
          </p>
        )}
      {state.discovery.state === "succeeded" && (
        <Action action={onContinue}>Continue to model profiles</Action>
      )}
    </StepPanel>
  );
}

function ProfilesStep({
  state,
  guard,
  onDone,
  onSaved,
}: {
  state: LlmReadiness;
  guard: <T>(action: () => Promise<T>) => Promise<T>;
  onDone: () => void;
  onSaved: () => Promise<void>;
}) {
  const [saved, setSaved] = useState<string[]>([]);
  const connection = state.connection;
  if (!connection?.active)
    return (
      <p className="notice error">Create an active model endpoint first.</p>
    );
  const known = state.discovery.models.map((m) => m.name);
  const makeModels = (role: string, current: string) => {
    const options = known.length
      ? known.map((m) => ({ value: m, label: m }))
      : [{ value: current, label: current }];
    return {
      connection_id: connection.id,
      role,
      model: options[0]?.value ?? "",
      options,
    };
  };
  const implementation = state.implementation_profile;
  const verifier = state.verifier_profile;
  return (
    <StepPanel
      title="Model profiles"
      icon={CircleDashed}
      note="A profile binds a role to one exact model identifier and a temperature. Implementation and verification are separate roles and, by default, must not resolve to the same model, so that a verifier is not simply the implementer agreeing with itself."
    >
      {state.discovery.state !== "succeeded" && (
        <p className="notice warning">
          No current discovery is available, so there is no verified list to
          choose from. Run the connection check first; you can still enter an
          exact identifier by hand, but nothing will confirm it exists.
        </p>
      )}
      {(["implementation", "verifier"] as const).map((role) => {
        const existing = role === "implementation" ? implementation : verifier;
        const other = role === "implementation" ? verifier : implementation;
        const spec = makeModels(role, existing?.model ?? "");
        return (
          <div key={role}>
            <h3>
              {role === "implementation" ? "Implementation" : "Verification"}{" "}
              profile
            </h3>
            {existing ? (
              <p className="notice">
                Already configured as <code>{existing.model}</code>. Edit it
                from <Link href="/agents-models">Agents &amp; models</Link>.
              </p>
            ) : (
              <Form
                fields={[
                  {
                    name: "name",
                    label: "Profile name",
                    required: true,
                    max: 120,
                  },
                  {
                    name: "model",
                    label: "Model",
                    required: true,
                    // Only offer a picker when a discovery actually produced
                    // models. With none, a select would hold a single empty
                    // option and the operator could not type the identifier the
                    // help text tells them to enter.
                    ...(known.length ? { options: spec.options } : {}),
                    help: known.length
                      ? "From the current discovery."
                      : "No discovery is current, so enter the exact identifier reported by your model server, for example qwen3-coder:30b.",
                  },
                  {
                    name: "temperature",
                    label: "Temperature (0-2)",
                    type: "number",
                    required: true,
                  },
                ]}
                initial={{
                  name:
                    role === "implementation"
                      ? "Implementation"
                      : "Verification",
                  model:
                    spec.options.find((o) => o.value !== other?.model)?.value ??
                    spec.options[0]?.value ??
                    "",
                  temperature: role === "implementation" ? "0.2" : "0",
                }}
                label={`Create ${role} profile`}
                submit={async (v) => {
                  if (v.model === other?.model)
                    throw new Error(
                      "Choose different models for implementation and verification.",
                    );
                  await guard(() =>
                    write("/model-profiles", {
                      name: v.name,
                      connection_id: spec.connection_id,
                      model: v.model,
                      role,
                      temperature: Number(v.temperature),
                      active: true,
                      expected_version: 0,
                    }),
                  );
                  setSaved((s) => [...s, role]);
                  await onSaved();
                }}
              />
            )}
          </div>
        );
      })}
      <div className="actions">
        <button
          className="primary"
          disabled={
            implementation === null ||
            verifier === null ||
            !state.distinct_models
          }
          onClick={onDone}
        >
          Continue to coding agent
        </button>
      </div>
      {implementation && verifier && !state.distinct_models && (
        <p className="notice warning">
          Choose different implementation and verification models in Agents
          &amp; models.
        </p>
      )}
      {(implementation === null || verifier === null) && (
        <p className="notice">
          Both profiles are required. The button stays disabled until each one
          exists.
          {saved.length > 0 && " Saved so far: " + saved.join(", ") + "."}
        </p>
      )}
    </StepPanel>
  );
}

function AgentStep({
  state,
  guard,
  onDone,
}: {
  state: LlmReadiness;
  guard: <T>(action: () => Promise<T>) => Promise<T>;
  onDone: () => Promise<void>;
}) {
  const [saved, setSaved] = useState(false);
  const implementation = state.implementation_profile;
  if (!implementation)
    return <p className="notice error">Create profiles first.</p>;
  if (state.agent)
    return (
      <StepPanel title="Coding agent" icon={Terminal}>
        <p className="notice">
          <strong>{state.agent.name}</strong> ({state.agent.provider}) is
          already bound at <code>{state.agent.executable}</code>. Edit it from{" "}
          <Link href="/agents-models">Agents &amp; models</Link>.
        </p>
        <Action action={onDone}>Show the summary</Action>
      </StepPanel>
    );
  return (
    <StepPanel
      title="Coding agent"
      icon={Terminal}
      note="An agent is a root-owned executable on this host that NachtLabs invokes inside an isolated sandbox. This screen records its path and the version you expect; it never installs, runs or verifies the binary, and a stored version is not a tested version."
    >
      <Form
        fields={[
          { name: "name", label: "Agent name", required: true, max: 120 },
          {
            name: "provider",
            label: "Agent",
            options: [
              { value: "hermes", label: "Hermes" },
              { value: "opencode", label: "OpenCode" },
            ],
            help: "Codex is not yet available as an agent in this release.",
          },
          {
            name: "executable",
            label: "Absolute Linux executable path",
            required: true,
            help: "For example /usr/local/bin/hermes. Root-owned, installed by you.",
          },
          {
            name: "expected_agent_version",
            label: "Expected installed version",
            required: true,
            max: 80,
            help: "Your expectation, not a verified value. Check it with the executable's own --version on the host.",
          },
          {
            name: "model_profile_id",
            label: "Model profile",
            required: true,
            options: [
              {
                value: implementation.id,
                label: `Implementation · ${implementation.model}`,
              },
            ],
          },
          {
            name: "timeout_seconds",
            label: "Timeout (10-3600 seconds)",
            type: "number",
            required: true,
          },
        ]}
        initial={{
          name: "Hermes",
          provider: "hermes",
          executable: "/usr/local/bin/hermes",
          expected_agent_version: "",
          model_profile_id: implementation.id,
          timeout_seconds: "300",
        }}
        label="Create agent"
        submit={async (v) => {
          await guard(() =>
            write("/agents", {
              name: v.name,
              provider: v.provider,
              executable: v.executable,
              expected_agent_version: v.expected_agent_version,
              model_profile_id: implementation.id,
              timeout_seconds: Number(v.timeout_seconds),
              active: true,
              expected_version: 0,
            }),
          );
          setSaved(true);
        }}
      />
      {saved && (
        <p className="notice success" role="status">
          Agent configuration saved.{" "}
          <button
            onClick={async () => {
              await onDone();
            }}
          >
            Continue to execution on the host
          </button>
        </p>
      )}
    </StepPanel>
  );
}

function ExecutionStep({ onDone }: { onDone: () => Promise<void> }) {
  return (
    <StepPanel
      title="Execution on the host"
      icon={Server}
      note="Everything above is configuration. Nothing runs until these host steps are done, and this wizard cannot do any of them: it needs root on this host. Do them in order, then reload and the summary below will reflect the new state."
    >
      <ol className="checklist">
        <li>
          <strong>Enable provider network checks, if still off.</strong> Set{" "}
          <code>NACHTLABS_INTEGRATION_NETWORK_ENABLED=true</code> in the
          deployment, then{" "}
          <code>
            NACHTLABS_REWRITE_CONFIG=true docker compose run --rm init
          </code>{" "}
          and <code>docker compose restart api worker</code>.
        </li>
        <li>
          <strong>Place the runtime files the executor will pin.</strong> Copy
          the qualification assets (git, python, demo_doc.py, the opencode
          binary) into <code>/opt/nachtlabs-runtime/</code> so the catalog can
          resolve them under <code>NACHTLABS_RUNTIME_ROOT</code>.
        </li>
        <li>
          <strong>Qualify the executor.</strong> Run{" "}
          <code>
            sudo scripts/qualify-executor.py --evidence /path/report.md
            --confirm-linux-isolation-passed
          </code>{" "}
          with the HMAC key at{" "}
          <code>/etc/nachtlabs/credentials/executor-qualification-key</code>.
          Follow <code>docs/operations/executor-qualification.md</code> for the
          full list of pinned files and the expected report shape.
        </li>
        <li>
          <strong>Restart the stack.</strong>{" "}
          <code>docker compose restart executor worker api</code> so the worker
          picks up the new catalog and the executor image rebuilds cleanly.
        </li>
        <li>
          <strong>Submit the first work request.</strong> Go to{" "}
          <code>/work-requests</code> and create the smallest real change you
          want the executor to make, then watch it under <code>/runs</code>. The
          expected journey is{" "}
          <code>planning → approved → implementation_validated → complete</code>
          .
        </li>
      </ol>
      <div className="actions">
        <Action action={onDone}>Continue to summary</Action>
      </div>
      <p className="notice">
        The full operator reference — every phase above plus diagnosis and
        rollback — lives in <Link href="/help">Help</Link> and in the runbook on
        the repo root.
      </p>
    </StepPanel>
  );
}

function Summary({ state, step }: { state: LlmReadiness; step: number }) {
  return (
    <StepPanel
      title="Where this stands"
      icon={CheckCircle2}
      note="Each line is a separate fact. They are not merged, because a saved configuration, a working endpoint, a proven compatibility and a runnable executor are four different things."
    >
      <ul className="checklist">
        <li>
          Model endpoint saved
          <Badge good={!!state.connection?.active}>
            {state.connection?.active
              ? state.connection.name
              : "Not configured"}
          </Badge>
        </li>
        <li>
          Connection check
          <Badge good={state.discovery.state === "succeeded"}>
            {state.discovery.state === "succeeded"
              ? "Current"
              : state.discovery.state}
          </Badge>
        </li>
        <li>
          Implementation and verification models differ
          <Badge good={state.distinct_models}>
            {state.distinct_models ? "Distinct" : "Not satisfied"}
          </Badge>
        </li>
        <li>
          Coding agent bound
          <Badge good={!!state.agent}>
            {state.agent ? state.agent.name : "Not configured"}
          </Badge>
        </li>
        <li>
          Compatibility proven
          <Badge>Unverified</Badge>
        </li>
        <li>
          Agent execution
          <Badge>Requires operator qualification</Badge>
        </li>
      </ul>
      <p className="notice">
        Step {step + 1} of {steps.length}.{" "}
        {state.complete
          ? "Configuration is complete, but nothing runs yet. "
          : "Configuration is incomplete. Finish the outstanding steps above. "}
        Execution needs a root-owned qualification the interface cannot perform:
        follow <code>docs/operations/executor-qualification.md</code>, record it
        with{" "}
        <code>
          sudo scripts/qualify-executor.py --evidence /path/report.md
          --confirm-linux-isolation-passed
        </code>
        , and only then start the executor. Remember that a loopback model
        address is refused for agent egress.
      </p>
    </StepPanel>
  );
}
