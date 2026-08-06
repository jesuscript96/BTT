"use client";

/**
 * Sustituto local de los hooks de Clerk (`useUser`, `useClerk`) para cuando
 * NEXT_PUBLIC_LOCAL_AUTH_BYPASS=true. Nunca importa nada que ejecute código
 * real de Clerk: solo se activa este camino cuando la variable está puesta,
 * así que la app no hace ninguna llamada de red a Clerk en local.
 *
 * Quitar en cuanto lleguen claves de Clerk de test reales.
 */
import { useUser as useClerkUser, useClerk as useClerkClerk } from "@clerk/nextjs";

const BYPASS = process.env.NEXT_PUBLIC_LOCAL_AUTH_BYPASS === "true";

const STUB_USER = {
  id: "local-dev-alvaro",
  fullName: "Álvaro (local)",
  createdAt: new Date("2026-01-01"),
  emailAddresses: [{ emailAddress: "alvaro@local.dev" }],
  primaryEmailAddress: { emailAddress: "alvaro@local.dev" },
  publicMetadata: { tier: "Free" as string },
  unsafeMetadata: {} as Record<string, unknown>,
  async update(patch: { unsafeMetadata?: Record<string, unknown> }) {
    if (patch.unsafeMetadata) {
      Object.assign(STUB_USER.unsafeMetadata, patch.unsafeMetadata);
    }
    return STUB_USER;
  },
};

function useStubUser() {
  return { isLoaded: true, isSignedIn: true, user: STUB_USER };
}

function useStubClerk() {
  return {
    signOut: (callback?: () => void) => {
      if (typeof callback === "function") callback();
    },
  };
}

export const useUser = BYPASS ? useStubUser : useClerkUser;
export const useClerk = BYPASS ? useStubClerk : useClerkClerk;
