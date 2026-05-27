import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import "./globals.css";

const terminalMono = JetBrains_Mono({
  variable: "--font-terminal-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "CloudTurtle",
  description: "Deployment console for backend applications with real-time diagnostics and management tools.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${terminalMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
