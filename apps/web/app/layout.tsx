import type { Metadata } from "next";
import {
  Cormorant_Garamond,
  Plus_Jakarta_Sans,
  Yatra_One,
  Anek_Gujarati,
  JetBrains_Mono,
} from "next/font/google";
import "./globals.css";

// Cormorant Garamond — high-contrast serif with razor italics. The
// closest a free face gets to old illuminated-manuscript drama.
const display = Cormorant_Garamond({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-display",
  display: "swap",
});

// Plus Jakarta Sans — humanist sans, less worn than Inter or Geist.
const body = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

// Yatra One — Devanagari poster face (hand-painted feel).
const deva = Yatra_One({
  subsets: ["devanagari", "latin"],
  weight: ["400"],
  variable: "--font-deva",
  display: "swap",
});

const gu = Anek_Gujarati({
  subsets: ["gujarati", "latin"],
  variable: "--font-gu",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Sarathi — the charioteer for live conversations",
  description:
    "A local-first desktop assistant that listens to your meetings in Gujarati and English, transcribes them, and surfaces answers from your own documents. On-device, in the moment, in your language.",
  metadataBase: new URL("https://sarathi.app"),
  openGraph: {
    title: "Sarathi",
    description: "On-device live transcription. Gujarati + English. Cited.",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${body.variable} ${deva.variable} ${gu.variable} ${mono.variable}`}
    >
      <body className="relative">{children}</body>
    </html>
  );
}
