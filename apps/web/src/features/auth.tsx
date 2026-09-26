"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Moon } from "lucide-react";
import { write } from "@nachtlabs/api-client";
import { Form, type Field } from "@/components/ui";

export function ApiUnreachable({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="notice" role="alert">
      <p>
        <strong>NachtLabs cannot reach its own API.</strong>
      </p>
      <p>
        Setup status could not be read, so this page cannot tell whether an
        account exists yet. It will not offer a sign-in form that might not
        work.
      </p>
      <p>
        Check that the API service is running and that the reverse proxy
        forwards <code>/api/</code> to it, then try again.
      </p>
      <button className="primary" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

export function AuthScreen({
  path,
  initialized,
  checkingSetup,
  setupUnreachable,
  retrySetup,
}: {
  path: string;
  initialized?: boolean;
  checkingSetup: boolean;
  setupUnreachable: boolean;
  retrySetup: () => void;
}) {
  const router = useRouter();
  const client = useQueryClient();
  const [challenge, setChallenge] = useState<string>();
  const [message, setMessage] = useState("");
  const [token, setToken] = useState("");
  useEffect(() => {
    const value = new URLSearchParams(window.location.hash.slice(1)).get(
      "token",
    );
    if (value) {
      // Capture the browser-only fragment after hydration, then remove it from the address bar.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setToken(value);
      history.replaceState(null, "", window.location.pathname);
    }
  }, []);
  const login = path === "/login";
  const setup = path === "/setup";
  const forgot = path === "/forgot-password";
  const invitation = path === "/accept-invitation";
  // Nobody has registered on this installation yet, so there is nothing to sign
  // in to. Offer Owner setup instead of a form that cannot succeed.
  const firstRun = initialized === false;
  const setupClosed = initialized === true && setup;
  const title = setupUnreachable
    ? "NachtLabs is not reachable"
    : firstRun
      ? "Welcome to NachtLabs"
      : challenge
        ? "Verify your identity"
        : setupClosed
          ? "Setup is already complete"
          : setup
            ? "Initialize NachtLabs"
            : forgot
              ? "Reset your password"
              : invitation
                ? "Accept your invitation"
                : login
                  ? "Welcome back"
                  : "Choose a new password";
  const fields: Field[] = challenge
    ? [
        {
          name: "code",
          label: "Authenticator or recovery code",
          required: true,
        },
      ]
    : setup
      ? [
          {
            name: "organization",
            label: "Organization name",
            required: true,
            max: 120,
          },
          { name: "name", label: "Your name", required: true, max: 120 },
          {
            name: "email",
            label: "Email address",
            type: "email",
            required: true,
          },
          {
            name: "password",
            label: "Password",
            type: "password",
            required: true,
            min: 12,
            max: 128,
            help: "This account becomes the Owner. At least 12 characters.",
          },
          {
            name: "password_confirm",
            label: "Confirm password",
            type: "password",
            required: true,
            min: 12,
            max: 128,
            help: "Type the same password again.",
          },
        ]
      : login || forgot
        ? [
            {
              name: "email",
              label: "Email address",
              type: "email",
              required: true,
            },
            ...(forgot
              ? []
              : [
                  {
                    name: "password",
                    label: "Password",
                    type: "password",
                    required: true,
                    max: 128,
                  },
                ]),
          ]
        : [
            ...(!token
              ? [
                  {
                    name: "token",
                    label: "Single-use link token",
                    type: "password",
                    required: true,
                  },
                ]
              : []),
            ...(invitation
              ? [{ name: "name", label: "Your name", required: true }]
              : []),
            {
              name: "password",
              label: "New password",
              type: "password",
              required: true,
              min: 12,
              max: 128,
            },
          ];
  async function signedIn() {
    client.clear();
    router.replace("/overview");
  }
  return (
    <div className="auth-layout">
      <section className="auth-art">
        <Link className="brand" href="/login">
          <Moon />
          NachtLabs
        </Link>
        <div>
          <p className="eyebrow">BUILT FOR TRUSTWORTHY DELIVERY</p>
          <h2>
            Clear intent.
            <br />
            Recorded evidence.
            <br />
            Human control.
          </h2>
          <p>
            A deliberate workspace for governing the software your agents will
            build.
          </p>
        </div>
        <span className="auth-stamp">
          LINUX NATIVE / SELF HOSTED / MILESTONE 4
        </span>
      </section>
      <main className="auth">
        <h1>{title}</h1>
        {setupUnreachable ? (
          <ApiUnreachable onRetry={retrySetup} />
        ) : (
          <>
            <p>
              {firstRun
                ? "No account exists on this installation yet. Create the first one; it becomes the Owner and setup then closes."
                : setupClosed
                  ? "Nothing can be created here. Use one of the routes below."
                  : setup
                    ? "The first account becomes the Owner. Public setup closes after initialization."
                    : "Your organization’s engineering control plane."}
            </p>
            {firstRun && !setup ? (
              <div className="notice" role="status">
                <p>
                  {checkingSetup
                    ? "Checking whether this installation has been initialized…"
                    : "Owner setup is required before anyone can sign in."}
                </p>
                <Link className="button primary" href="/setup">
                  Create the Owner account
                </Link>
              </div>
            ) : setupClosed ? (
              <div className="notice" role="status">
                <p>
                  <strong>
                    An account already exists on this installation.
                  </strong>{" "}
                  First-time setup is closed and will not create a second
                  account, so the page you are on cannot register you.
                </p>
                <ul>
                  <li>
                    You know the credentials: <Link href="/login">sign in</Link>
                    .
                  </li>
                  <li>
                    You know the email but not the password:{" "}
                    <Link href="/forgot-password">request a reset</Link>. This
                    needs email delivery to be configured.
                  </li>
                  <li>
                    You are the operator and have neither: on the host console
                    run <code>make recover-owner</code> to reset the Owner
                    password. It needs root. If no account exists at all, add{" "}
                    <code>--bootstrap</code> to create the first one.
                  </li>
                  <li>
                    Adding somebody else: the Owner issues an invitation under
                    Settings. Invitations are sent by email, so an installation
                    without SMTP cannot onboard anyone.
                  </li>
                </ul>
              </div>
            ) : message ? (
              <div className="notice success" role="status">
                {message}
              </div>
            ) : path === "/mfa/verify" ? (
              <p className="notice">
                Start a fresh sign-in to receive a verification challenge.
              </p>
            ) : (
              <Form
                key={`${path}-${Boolean(challenge)}-${Boolean(token)}`}
                fields={fields}
                // A first run should need only an email and a password, so the
                // two descriptive fields arrive prefilled but stay editable.
                initial={
                  setup
                    ? { organization: "NachtLabs", name: "Owner" }
                    : undefined
                }
                label={
                  challenge
                    ? "Verify"
                    : setup
                      ? "Create Owner account"
                      : login
                        ? "Sign in"
                        : forgot
                          ? "Send reset link"
                          : "Save password"
                }
                submit={async (values) => {
                  if (challenge) {
                    await write("/auth/mfa/verify", {
                      challenge,
                      code: values.code,
                    });
                    setChallenge(undefined);
                    await signedIn();
                  } else if (setup) {
                    if (values.password !== values.password_confirm) {
                      throw new Error(
                        "The two passwords do not match. Retype them and try again.",
                      );
                    }
                    // The API forbids unknown fields, so the confirmation must
                    // never leave the browser. Name the payload explicitly.
                    await write("/auth/setup", {
                      organization: values.organization,
                      name: values.name,
                      email: values.email,
                      password: values.password,
                    });
                    await signedIn();
                  } else if (login) {
                    const result = await write<{
                      mfa_required: boolean;
                      challenge?: string;
                    }>("/auth/login", values);
                    if (result.mfa_required) setChallenge(result.challenge);
                    else await signedIn();
                  } else if (forgot) {
                    const result = await write<{ message: string }>(
                      "/auth/forgot-password",
                      values,
                    );
                    setMessage(result.message);
                  } else {
                    await write(
                      invitation
                        ? "/auth/accept-invitation"
                        : "/auth/reset-password",
                      { ...values, token: token || values.token },
                    );
                    setToken("");
                    setMessage("Password saved. You can now sign in.");
                  }
                }}
              />
            )}
          </>
        )}
        <div className="auth-links">
          {/*
              Fails open. The link is hidden only when setup-status positively
              reports that an account already exists; when the answer is false
              or unknown it stays visible, because hiding it on an unknown
              answer is what removed the only route to registering. A visible
              link that explains itself is safer than an invisible one.
            */}
          {login ? (
            initialized === true ? null : (
              <Link href="/setup">First-time setup</Link>
            )
          ) : firstRun || setupClosed ? null : (
            <>
              <Link href="/login">Sign in</Link>
              {login ? null : (
                <Link href="/forgot-password">Forgot password?</Link>
              )}
            </>
          )}
        </div>
        {/*
            The server cannot tell "no account" from "account whose password
            you have lost", so recovery is always documented rather than
            inferred. Additional accounts are invitations, not setup.
          */}
        {login ? (
          <div className="auth-help">
            <p>
              <strong>No account yet, or locked out?</strong>
            </p>
            <ul>
              <li>
                No account on this installation yet: use the First-time setup
                link. The first account becomes the Owner and setup then closes.
              </li>
              <li>
                Already initialized but you cannot sign in: on the host console
                run <code>make recover-owner</code> to reset the Owner password,
                or <code>recover-owner.py --bootstrap</code> if no account
                exists at all. Both require root.
              </li>
              <li>
                Adding colleagues later: the Owner issues invitations under
                Settings. Invitations are delivered by email, so an installation
                without SMTP cannot onboard anyone.
              </li>
            </ul>
          </div>
        ) : null}
        <small style={{ marginTop: 24 }}>
          Credentials remain on this installation. No public registration.
        </small>
      </main>
    </div>
  );
}
