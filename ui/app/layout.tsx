import type { Metadata } from "next";
import "./globals.css";
import { ThemeProvider } from "@/components/shell/theme-provider";

export const metadata: Metadata = {
  title: "Aegis — Local Knowledge Assistant",
  description: "Air-gapped document intelligence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
