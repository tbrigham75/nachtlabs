import { Screen } from "@/components/screen";
import { Suspense } from "react";
export default function Page() { return <Suspense fallback={<p className="loading">Loading…</p>}><Screen /></Suspense>; }
