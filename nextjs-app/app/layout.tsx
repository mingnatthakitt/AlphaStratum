import type { Metadata } from "next";
import "./globals.css";
import { ThemeProvider } from "@/components/ThemeProvider";
import { Providers } from "@/components/Providers";
import { WatchlistProvider } from "@/contexts/WatchlistContext";
import Navbar from "@/components/Navbar";

export const metadata: Metadata = {
  title: "Alpha Stratum — Multi-layered quantitative intelligence",
  description: "AI-powered stock analysis with quantitative models, regime detection, Monte Carlo forecasting, and transparent source citations",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans antialiased">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
          <Providers>
            <WatchlistProvider>
              <Navbar />
              <main className="container mx-auto px-4 py-6">{children}</main>
            </WatchlistProvider>
          </Providers>
        </ThemeProvider>
      </body>
    </html>
  );
}
