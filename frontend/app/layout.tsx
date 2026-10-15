import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Clinical Evidence Intelligence",
  description:
    "An AI-powered evidence intelligence platform for exploring medical literature, comparing studies, and understanding where the evidence agrees — or conflicts.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
