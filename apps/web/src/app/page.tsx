import { Screen } from "@/components/screen";
import { Suspense } from "react";
/**
 * Renders the screen directly rather than redirecting to /overview.
 *
 * /overview is a private route, so redirecting there made a first-time visit
 * bounce through a 401 and back again, which is what made the sign-in and
 * setup redirects race. Rendering here removes the hop entirely.
 */
export default function Home() {
  return (
    <Suspense fallback={<p className="loading">Loading…</p>}>
      <Screen />
    </Suspense>
  );
}
