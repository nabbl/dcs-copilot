import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

const title = "MARA — Your second seat in DCS";
const description = "Meet MARA, the free mission-aware voice copilot for DCS. Bring your own OpenAI API key.";

export function generateMetadata(): Metadata {
  const siteOrigin = process.env.PUBLIC_SITE_ORIGIN;
  const image = siteOrigin ? new URL("og.png", siteOrigin.endsWith("/") ? siteOrigin : `${siteOrigin}/`).toString() : undefined;

  return {
    title,
    description,
    ...(siteOrigin ? { metadataBase: new URL(siteOrigin) } : {}),
    openGraph: {
      title,
      description,
      type: "website",
      ...(image ? { images: [{ url: image, width: 1672, height: 941, alt: "MARA — your second seat in DCS" }] } : {}),
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      ...(image ? { images: [image] } : {}),
    },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable}`}>{children}</body>
    </html>
  );
}
