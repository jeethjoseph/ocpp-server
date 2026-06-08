import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Navbar from "@/components/Navbar";
import { ThemeProvider } from "@/contexts/ThemeContext";
import { QueryProvider } from "@/contexts/QueryClientProvider";
import { AuthProvider } from "@/contexts/AuthContext";
import { ClerkProvider } from '@clerk/nextjs';
import { Toaster } from "sonner";
import NewRelicInitializer from "@/components/NewRelicInitializer";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "voltNOW EV Charging",
  description: "EV Charging Station Management System",
  icons: {
    // Scheme-named for the media query: the LIGHT color-scheme (white tab bar)
    // gets the dark/black badge; the DARK scheme gets the light-grey badge.
    // This follows the OS preference — the only mechanism browser tabs support.
    icon: [
      { url: "/favicon-light.png", media: "(prefers-color-scheme: light)", type: "image/png" },
      { url: "/favicon-dark.png", media: "(prefers-color-scheme: dark)", type: "image/png" },
    ],
    shortcut: "/favicon.ico",
    apple: "/apple-icon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-background text-foreground transition-colors duration-300`}
      >
        <NewRelicInitializer />
        <ClerkProvider>
          <AuthProvider>
            <QueryProvider>
              <ThemeProvider>
                <Navbar />
                <main className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
                  {children}
                </main>
                <Toaster />
              </ThemeProvider>
            </QueryProvider>
          </AuthProvider>
        </ClerkProvider>
      </body>
    </html>
  );
}
