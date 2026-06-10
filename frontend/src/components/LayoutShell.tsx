"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";

export function LayoutShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAuthRoute =
    pathname?.startsWith("/sign-in") || pathname?.startsWith("/sign-up");

  return (
    <div
      style={{
        display: "flex",
        height: "100dvh",
        overflow: "hidden",
      }}
    >
      {!isAuthRoute && <Sidebar />}
      <main
        style={{
          flex: 1,
          minHeight: "100dvh",
          minWidth: 0,
          backgroundColor: "var(--color-ec-bg-base)",
          overflow: isAuthRoute ? "visible" : "auto",
        }}
      >
        {children}
      </main>
    </div>
  );
}
