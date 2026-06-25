"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { FeedbackWidget } from "@/components/FeedbackWidget";
import WhatsNewModal from "@/components/WhatsNewModal";

export function LayoutShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAuthRoute =
    pathname?.startsWith("/sign-in") || pathname?.startsWith("/sign-up");

  const [feedbackOpen, setFeedbackOpen] = useState(false);

  return (
    <div
      style={{
        display: "flex",
        height: "100dvh",
        overflow: "hidden",
      }}
    >
      {!isAuthRoute && <Sidebar onOpenFeedback={() => setFeedbackOpen(true)} />}
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

      {!isAuthRoute && (
        <>
          <FeedbackWidget open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />
          <WhatsNewModal />
        </>
      )}
    </div>
  );
}
