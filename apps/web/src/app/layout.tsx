import type { Metadata } from "next";
import { Providers } from "@/components/providers";
import "@/styles/globals.css";
export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "NachtLabs",
  description: "Governed software engineering operations",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="midnight">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
