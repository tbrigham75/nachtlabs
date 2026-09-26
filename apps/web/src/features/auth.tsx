"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Moon } from "lucide-react";
import { write } from "@nachtlabs/api-client";
import { Form, type Field } from "@/components/ui";

export function AuthScreen({ path }: { path: string }) {
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
  const title = challenge
    ? "Verify your identity"
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
          },
          {
            name: "bootstrap_token",
            label: "One-time setup token",
            type: "password",
            required: true,
            help: "Read from the protected token file created by your Linux administrator.",
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
        <p>
          {setup
            ? "The first account becomes the Owner. Public setup closes after initialization."
            : "Your organization’s engineering control plane."}
        </p>
        {message ? (
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
                await write("/auth/setup", values);
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
        <div className="auth-links">
          <Link href="/login">Sign in</Link>
          {login ? (
            <Link href="/forgot-password">Forgot password?</Link>
          ) : (
            <Link href="/setup">Initial setup</Link>
          )}
        </div>
        <small style={{ marginTop: 24 }}>
          Credentials remain on this installation. No public registration.
        </small>
      </main>
    </div>
  );
}
