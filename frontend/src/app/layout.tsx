import type { Metadata } from "next";
import "./globals.css";
import { LayoutShell } from "@/components/LayoutShell";
import { ClerkProvider } from "@clerk/nextjs";
import { dark } from "@clerk/themes";
import { PHProvider } from "./providers";
import PostHogPageView from "@/components/PostHogPageView";
import { Suspense } from "react";

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
          colorPrimary: "#D87A3D",
          colorBackground: "#16181A",
          colorInputBackground: "#1C1E21",
          colorInputText: "#D4D2CF",
          colorText: "#E4E2DF",
          colorTextSecondary: "#8A8D92",
          colorNeutral: "#2C2F33",
          colorDanger: "#C94D3F",
          colorSuccess: "#4A9D7F",
          borderRadius: "5px",
          fontFamily: "'General Sans', sans-serif",
          fontFamilyButtons: "'General Sans', sans-serif",
          fontSize: "13px",
          spacingUnit: "14px",
        },
        elements: {
          card: {
            backgroundColor: "#1C1E21",
            border: "0.5px solid #2C2F33",
            borderRadius: "7px",
            boxShadow: "none",
            padding: "32px 36px",
            width: "420px",
          },
          headerTitle: {
            fontFamily: "'Fraunces', serif",
            fontSize: "24px",
            fontWeight: "600",
            color: "#E4E2DF",
            letterSpacing: "-0.3px",
          },
          headerSubtitle: {
            fontFamily: "'General Sans', sans-serif",
            fontSize: "12px",
            color: "#6A6D72",
            marginTop: "4px",
          },
          logoImage: {
            width: "32px",
            height: "32px",
          },
          logoBox: {
            marginBottom: "20px",
            justifyContent: "center",
          },
          socialButtonsBlockButton: {
            backgroundColor: "#232528",
            border: "0.5px solid #2C2F33",
            borderRadius: "5px",
            color: "#D4D2CF",
            fontFamily: "'General Sans', sans-serif",
            fontSize: "12px",
            fontWeight: "500",
            padding: "10px 16px",
            transition: "background 150ms ease",
            "&:hover": {
              backgroundColor: "#2C2F33",
            },
          },
          socialButtonsBlockButtonText: {
            fontFamily: "'General Sans', sans-serif",
            fontSize: "12px",
            fontWeight: "500",
            color: "#D4D2CF",
          },
          dividerLine: {
            backgroundColor: "#2C2F33",
            height: "0.5px",
          },
          dividerText: {
            fontFamily: "'General Sans', sans-serif",
            fontSize: "9px",
            fontWeight: "700",
            textTransform: "uppercase",
            letterSpacing: "0.15em",
            color: "#6A6D72",
          },
          formFieldInput: {
            backgroundColor: "#101213",
            border: "0.5px solid #2C2F33",
            borderRadius: "5px",
            padding: "8px 11px",
            fontFamily: "'General Sans', sans-serif",
            fontSize: "12px",
            color: "#D4D2CF",
            "&:focus": {
              borderColor: "#D87A3D",
              outline: "none",
            },
          },
          formFieldLabel: {
            fontFamily: "'General Sans', sans-serif",
            fontSize: "9px",
            fontWeight: "700",
            textTransform: "uppercase",
            letterSpacing: "0.12em",
            color: "#6A6D72",
            marginBottom: "5px",
          },
          formButtonPrimary: {
            backgroundColor: "#D87A3D",
            color: "#1A0A00",
            border: "none",
            borderRadius: "5px",
            padding: "9px 16px",
            fontFamily: "'General Sans', sans-serif",
            fontSize: "11px",
            fontWeight: "700",
            letterSpacing: "1.2px",
            textTransform: "uppercase",
            transition: "background 150ms ease",
            "&:hover": {
              backgroundColor: "#E89C6A",
            },
          },
          footerActionText: {
            fontFamily: "'General Sans', sans-serif",
            fontSize: "11px",
            color: "#6A6D72",
          },
          footerActionLink: {
            fontFamily: "'General Sans', sans-serif",
            fontSize: "11px",
            fontWeight: "600",
            color: "#D87A3D",
            "&:hover": {
              color: "#E89C6A",
            },
          },
          footer: {
            backgroundColor: "transparent",
            borderTop: "0.5px solid #2C2F33",
            marginTop: "20px",
            paddingTop: "16px",
          },
          formFieldErrorText: {
            fontFamily: "'General Sans', sans-serif",
            fontSize: "10px",
            color: "#C94D3F",
          },
          alertText: {
            fontFamily: "'General Sans', sans-serif",
            fontSize: "11px",
            color: "#C94D3F",
          },
          identityPreviewText: {
            fontFamily: "'General Sans', sans-serif",
            fontSize: "11px",
            color: "#6A6D72",
          },
          formFieldHintText: {
            fontFamily: "'General Sans', sans-serif",
            fontSize: "10px",
            color: "#6A6D72",
          },
        },
        layout: {
          logoImageUrl: "/isotipo.svg",
          logoPlacement: "inside",
          socialButtonsPlacement: "top",
          socialButtonsVariant: "blockButton",
          showOptionalFields: false,
          helpPageUrl: undefined,
          privacyPageUrl: undefined,
          termsPageUrl: undefined,
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
          <PHProvider>
            <Suspense fallback={null}>
              <PostHogPageView />
            </Suspense>
            <LayoutShell>{children}</LayoutShell>
          </PHProvider>
        </body>
      </html>
    </ClerkProvider>
  );
}
