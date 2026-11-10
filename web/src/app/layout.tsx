import type { ReactNode } from "react";

import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Newsreader } from "next/font/google";

import "./globals.css";

// next/font downloads these at build time and serves them from this app, so
// the browser makes no request to a font host.
const newsreader = Newsreader({
  subsets: ["latin"],
  style: ["normal", "italic"],
  variable: "--font-newsreader",
  display: "swap",
});

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
});

const DESCRIPTION =
  "ProofMode checks a suspicious message against common scam red flags, or against the official facts of the organisation it claims to come from.";

export const metadata: Metadata = {
  title: "ProofMode: Is this message real?",
  description: DESCRIPTION,
  openGraph: {
    title: "ProofMode: Is this message real?",
    description: DESCRIPTION,
    type: "website",
  },
  referrer: "no-referrer",
};

export const viewport: Viewport = {
  colorScheme: "dark",
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html
      lang="en"
      className={`${newsreader.variable} ${plexSans.variable} ${plexMono.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
