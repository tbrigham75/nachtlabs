"use client";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="auth">
      <h1>This view could not be displayed</h1>
      <p>
        No action has been confirmed by this screen. Refresh to reconcile with
        the server.
      </p>
      <button onClick={reset}>Try again</button>
    </main>
  );
}
