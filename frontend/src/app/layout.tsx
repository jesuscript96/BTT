import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { ClerkProvider } from "@clerk/nextjs";
import { dark } from "@clerk/themes";

export const metadata: Metadata = {
  title: "Edgecute",
  description: "Trading strategy platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ClerkProvider
      appearance={{
        baseTheme: dark,
        variables: {
          colorPrimary: '#D87A3D',
          colorBackground: '#0D0D0D',
          colorInputBackground: '#1A1A1A',
          colorText: '#F5F0EB',
          borderRadius: '5px',
          fontFamily: 'General Sans, sans-serif',
        },
      }}
    >
      <html lang="en">
        <head>
          <link rel="preconnect" href="https://fonts.googleapis.com" />
          <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
          <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..700;1,9..144,400..700&display=swap" rel="stylesheet" />
          <link href="https://api.fontshare.com/v2/css?f[]=general-sans@400,500,600,700&display=swap" rel="stylesheet" />
        </head>
        <body>
          <div style={{
            display: 'flex',
            height: '100dvh',
            overflow: 'hidden',
          }}>
            <Sidebar />
            <main style={{
              flex: 1,
              minHeight: '100dvh',
              minWidth: 0,
              backgroundColor: 'var(--color-ec-bg-base)',
              overflow: 'auto'
            }}>
              {children}
            </main>
          </div>
        </body>
      </html>
    </ClerkProvider>
  );
}
