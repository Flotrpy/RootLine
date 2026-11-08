import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "Rootline",
  description:
    "An open, reproducible benchmark of how free and open AI models diagnose and fix microservice failures.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header className="site">
          <div className="wrap">
            <Link href="/" className="brand">
              Rootline
            </Link>
            <nav aria-label="Main">
              <Link href="/">Results</Link>
              <Link href="/incidents/">Incidents</Link>
              <Link href="/method/">Method</Link>
              <Link href="/hardware/">Hardware</Link>
            </nav>
          </div>
        </header>
        <main className="wrap">{children}</main>
        <footer className="site">
          <div className="wrap">
            Pilot study. Every number on this site is produced by the analysis scripts from the
            published runs. Code Apache-2.0, data CC BY 4.0.
          </div>
        </footer>
      </body>
    </html>
  );
}
