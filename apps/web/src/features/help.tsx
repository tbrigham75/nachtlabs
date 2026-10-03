"use client";
import Link from "next/link";
import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { api, type LlmReadiness } from "@nachtlabs/api-client";
import { Badge } from "@/components/ui";

/**
 * A click-to-copy `<code>` block. Uses the Clipboard API when available and
 * falls back to document.execCommand("copy") for older browsers. The fallback
 * still works in a sandboxed iframe.
 */
function CopyCode({ children }: { children: string }) {
  const ref = useRef<HTMLElement>(null);
  const copied = useRef(false);
  return (
    <code
      ref={ref}
      className="code copyable"
      onClick={() => {
        const text = ref.current?.textContent ?? "";
        const done = () => {
          if (copied.current) return;
          copied.current = true;
          const parent = ref.current?.parentElement;
          if (parent) {
            const label = parent.querySelector("[data-copy-label]");
            if (label) {
              label.textContent = "Copied";
              window.setTimeout(() => (label.textContent = "Copy"), 1500);
            }
          }
        };
        if (navigator.clipboard) navigator.clipboard.writeText(text).then(done);
        else {
          const range = window.document.createRange();
          range.selectNodeContents(ref.current!);
          const sel = window.getSelection();
          sel?.removeAllRanges();
          sel?.addRange(range);
          window.document.execCommand("copy");
          sel?.removeAllRanges();
          done();
        }
      }}
    >
      {children}
      <span
        data-copy-label
        className="copy-label"
        style={{ marginLeft: 8, fontSize: 11, opacity: 0.6 }}
      >
        Copy
      </span>
    </code>
  );
}

type Phase = {
  n: number;
  title: string;
  surface: string;
  done?: boolean;
  body: (React.ReactNode & { key: any })[] | React.ReactNode;
};

function Phase({
  n,
  title,
  surface,
  done,
  children,
}: {
  n: number;
  title: string;
  surface: string;
  done?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="panel" data-phase={n}>
      <div className="panel-head">
        <h2>
          <ShieldAlert size={16} /> {`Phase ${n}`} · {title}
        </h2>
        <div>
          <Badge good={surface === "Browser"}>{surface}</Badge>
          {done && <Badge good>Complete</Badge>}
        </div>
      </div>
      <div style={{ display: "grid", gap: 12 }}>
        {Array.isArray(children)
          ? children
          : (
              <>
                {children}
              </>
            )}
      </div>
    </section>
  );
}

function Code({ text }: { text: string }) {
  return (
    <div className="code-block">
      <CopyCode>{text}</CopyCode>
    </div>
  );
}

/**
 * The full runbook, one phase per section. Content is static — it is the
 * canonical operator direction (OPS_RUNBOOK.md is the same text in markdown).
 * `focus` highlights one phase so a screen (e.g. the wizard's execution step)
 * can hand the operator the right slice.
 */
export function Help({ focus }: { focus?: number }) {
  const ready = useQuery({
    queryKey: ["llm-readiness"],
    queryFn: () => api<LlmReadiness>("/llm-readiness"),
  });
  const state = ready.data;
  const phases: Phase[] = [
    {
      n: 1,
      title: "Preflight (host)",
      surface: "Host console",
      body: [
        <p key="p">
          Sanity-check the install before anything else: all five containers up
          (api, worker, executor-eligible, postgres, web, mcp) and Ollama
          reachable over the LAN.
        </p>,
        <Code
          key="c"
          text={`docker ps | grep nachtlabs
curl -s http://192.168.2.171:11434/v1/models | head`}
        />,
      ],
    },
    {
      n: 2,
      title: "Model endpoint (private HTTP)",
      surface: "Host then Browser",
      done: state?.connection?.active,
      body: (
        <>
          <p>
            A private LAN address on cleartext HTTP is refused unless both of
            these are on the API AND the worker before you save the connection.
            This is an installation switch, not a wizard field.
          </p>
          <Code text={`NACHTLABS_INTEGRATION_NETWORK_ENABLED=true
NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE=true`} />
          <p>
            Then <code>docker compose restart api worker</code>, and in the
            wizard (Settings → LLM setup → Model endpoint) save with base URL{" "}
            <code>http://192.168.2.171:11434/v1</code> and pin{" "}
            <code>192.168.2.171</code>.
          </p>
        </>
      ),
    },
    {
      n: 3,
      title: "Connection check (discovery)",
      surface: "Browser",
      done: state?.discovery.state === "succeeded",
      body: (
        <p>
          The worker issues <code>GET /v1/models</code> once and records a
          probe. A saved connection is not a working one; a successful
          discovery is the first sign of one.
        </p>
      ),
    },
    {
      n: 4,
      title: "Profiles + agent",
      surface: "Browser",
      done: state?.complete || undefined,
      body: (
        <>
          <p>
            Three profiles, three roles. <code>require_distinct_models</code>{" "}
            is always on — implementation and verifier must use two different
            models. There is no override.
          </p>
          <Code text={`implementation · qwen3.8:27b · opencode agent · impl model
verifier     · gemma4:26b  · opencode agent · verifier model   (distinct)
planning     · qwen3.8:27b · worker-side · Ollama adapter`} />
          <p>
            An agent row binds an executable (
            <code>/opt/nachtlabs-runtime/bin/opencode</code>, expected version
            <code> 1.17.13</code>) to a profile. The interface never installs
            or verifies the binary — that is the operator's attestation.
          </p>
        </>
      ),
    },
    {
      n: 5,
      title: "Project policy",
      surface: "Browser",
      body: (
        <>
          <p>
            Every project has a policy document. It is <code>extra="forbid"</code>:
            you cannot add keys the release does not know, and it is the scope
            gate's source of truth.
          </p>
          <Code text={`allowed_paths     · ["docs/"]   ← the scope gate whitelist
max_changed_files · 5
validation_commands · [["python3", "checks/demo_doc.py"]]`} />
          <p>
            Any changed file outside <code>allowed_paths</code>, or inside a
            protected directory (<code>.opencode/</code>,{" "}
            <code>.hermes/</code>, <code>.git</code>), fails the run.
          </p>
        </>
      ),
    },
    {
      n: 6,
      title: "Execution gate (host, root)",
      surface: "Host console",
      body: (
        <>
          <p>
            Three root-owned facts. None of them is editable from the browser,
            and the API will refuse to run a job until every one is true on the
            host.
          </p>
          <Code text={`# 1 — runtime pins (catalog)
/etc/nachtlabs/execution-catalog.json
  runtime_root  · /opt/nachtlabs-runtime
  runtime_files · bin/opencode   (sha256, real file, no symlink)

# 2 — qualification receipt (root + explicit acknowledgement)
sudo scripts/qualify-executor.py --evidence /path/report.md —confirm-linux-isolation-passed
# writes /etc/nachtlabs/executor-qualification.json with:
#   qualified · true
#   release   · 0.1.0
#   catalog_sha256 · sha256(raw catalog bytes)
#   qualification_hmac · hmac-sha256(key, raw bytes)
# key = /etc/nachtlabs/credentials/executor-qualification-key  (base64, 32 decoded bytes, 0640 root:9000)

# 3 — egress policy inside the catalog
allowed_addresses · ["192.168.2.171"]
allow_private_network · true`} />
          <p>
            Change any catalog byte and the HMAC breaks: re-mint the receipt or
            the executor will refuse with <code>executor_unqualified</code>.
          </p>
        </>
      ),
    },
    {
      n: 7,
      title: "First run",
      surface: "Browser",
      body: (
        <>
          <p>
            Project → New work request → short prompt (
            <code>
              "Create docs/greeting.md with one line: Hello."
            </code>
            ) → submit non-dry-run.
          </p>
          <Code text={`plan (worker · planning profile) → you approve
  → discovery (executor clones)
  → implementation (opencode · impl model)
  → validation (scope gate · checks · secret scan)
  → verification (opencode · verifier model · writes nachtlabs-verdict.json)
  → delivery (pr_only · gated)`} />
          <p>
            The <code>verification</code> stage halts the run here by
            <code> delivery_policy=pr_only</code>. The verdict is available from
            the work request detail.
          </p>
        </>
      ),
    },
  ];
  const highlight = focus ? phases.find((p) => p.n === focus) : null;
  return (
    <div style={{ display: "grid", gap: 16 }}>
      {phases.map((p) => {
        const isFocus = focus === p.n;
        return (
          <div
            key={p.n}
            style={
              isFocus
                ? {
                    outline: "2px solid var(--color-accent)",
                    borderRadius: 8,
                    padding: 8,
                  }
                : undefined
            }
          >
            <Phase
              n={p.n}
              title={p.title}
              surface={p.surface}
              done={p.done}
            >
              {p.body}
            </Phase>
          </div>
        );
      })}
      <p className="notice">
        {state?.connection?.active && state?.discovery.state === "succeeded"
          ? "This installation has a working model endpoint. "
          : "Model endpoint and discovery are the two gates before you can build profiles and agents. "}
        See <code>OPS_RUNBOOK.md</code> for the same content in markdown.
      </p>
    </div>
  );
}

/**
 * The full-runbook screen. Mounted at /help from the shell and linked from
 * the wizard summary. Reads the same readiness state the wizard uses, so a
 * "Complete" badge is accurate for an operator who has already walked the
 * wizard.
 */
export function HelpScreen() {
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="panel">
        <div className="panel-head">
          <h2>
            <ShieldAlert size={18} /> Help · Zero to live run
          </h2>
          <Link className="button primary" href="/llm-setup">
            Open the LLM setup wizard
          </Link>
        </div>
        <p>
          The full path from a fresh install to a completed run, phase by
          phase. Each phase says which surface owns the step, what the API
          enforces, and what the host has to do that the browser cannot.
          Click a code block to copy it.
        </p>
      </div>
      <Help />
    </div>
  );
}

/**
 * An embeddable slice of the runbook. Used by the wizard to surface the phase
 * that owns the step the operator is about to walk — e.g. when the wizard
 * ends, the execution step mounts <Help focus={6} /> to hand over the
 * root-only commands. Import only from within an authenticated area; this
 * component reuses the shared readiness query (dedupes with the wizard's own
 * refetch).
 */
export function HelpPanel({ focus, note }: { focus?: number; note?: string }) {
  return (
    <section className="panel" style={{ marginTop: 16 }}>
      <div className="panel-head">
        <h2>
          <ShieldAlert size={16} /> Runbook
        </h2>
        <Link className="button" href="/help">
          Full runbook →
        </Link>
      </div>
      {note && <p>{note}</p>}
      <Help focus={focus} />
    </section>
  );
}
