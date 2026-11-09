import type { Metadata, Viewport } from "next";
import Link from "next/link";

import "@fontsource-variable/fraunces/full.css";
import "@fontsource-variable/fraunces/full-italic.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/400-italic.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./globals.css";

import { Mark } from "@/components/Mark";
import { Reveal } from "@/components/Reveal";
import { ThemeToggle } from "@/components/ThemeToggle";

export const metadata: Metadata = {
  title: "Rootline: which evidence does an AI need to find the root cause?",
  description:
    "An open, reproducible benchmark of how free and open AI models diagnose microservice failures, with real Wi-Fi faults on two Arduino UNO Q boards.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f3f0e8" },
    { media: "(prefers-color-scheme: dark)", color: "#0f0f0d" },
  ],
};

const REPO = "https://github.com/Flotrpy/RootLine";

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Scroll reveals only hide content once JS is known to run. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "document.documentElement.classList.add('js');try{var t=localStorage.getItem('rootline-theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}",
          }}
        />
      </head>
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        <header className="site">
          <div className="wrap">
            <Link href="/" className="brand" aria-label="Rootline, home">
              <Mark className="brand-mark" />
              Rootline <span className="ver">v0.1 pilot</span>
            </Link>
            <nav aria-label="Main">
              <Link href="/#results">Results</Link>
              <Link href="/incidents/">Incidents</Link>
              <Link href="/method/" className="nav-extra">
                Method
              </Link>
              <Link href="/hardware/">Hardware</Link>
              <ThemeToggle />
            </nav>
          </div>
        </header>
        <main id="main">{children}</main>
        <footer className="site">
          <div className="wrap">
            <p className="foot-word" aria-hidden="true">
              Rootline
            </p>
            <div className="foot-grid">
              <div>
                <h4>Status</h4>
                <p>
                  Pilot study, v0.1. Every number on this site is computed by the analysis scripts
                  from the published runs; none is typed by hand.
                </p>
              </div>
              <div>
                <h4>Licence</h4>
                <p>Code Apache-2.0. Data CC BY 4.0.</p>
              </div>
              <div>
                <h4>Source</h4>
                <ul>
                  <li>
                    <a href={REPO}>GitHub repository</a>
                  </li>
                  <li>
                    <a href={`${REPO}#limitations`}>Limitations</a>
                  </li>
                  <li>
                    <a href={`${REPO}/blob/main/docs/HARDWARE.md`}>Hardware guide</a>
                  </li>
                </ul>
              </div>
              <div>
                <h4>Author</h4>
                <p>flotrpy</p>
              </div>
            </div>
          </div>
        </footer>
        <Reveal />
      </body>
    </html>
  );
}
