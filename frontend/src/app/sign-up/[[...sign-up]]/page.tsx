import { SignUp } from "@clerk/nextjs";

// Registro ABIERTO: renderiza el <SignUp /> de Clerk. El cierre real se controla
// en Clerk (Restrictions -> sign-up mode). Con mode = Restricted, Clerk rechaza
// el alta aunque este formulario se muestre; con mode = Public, el alta funciona.
// (Histórico: esta página estuvo sustituida por un mensaje de "registro cerrado";
// se restauró el 2026-08-21 para el lanzamiento / pruebas e2e del gate de billing.)
export const dynamic = "force-dynamic";

export default function SignUpPage() {
  return (
    <div
      style={{
        display: "flex",
        height: "100dvh",
        backgroundColor: "#16181A",
        overflow: "hidden",
      }}
    >
      {/* LEFT — branding hero */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "60px",
          borderRight: "0.5px solid #2C2F33",
        }}
      >
        <svg
          width="48"
          height="48"
          viewBox="0 0 90 90"
          style={{ marginBottom: "32px" }}
        >
          <rect width="90" height="90" rx="8" fill="#D87A3D" />
          <rect x="20" y="18" width="52" height="10" fill="#16181A" />
          <rect x="20" y="40" width="38" height="10" fill="#16181A" />
          <rect x="20" y="62" width="52" height="10" fill="#16181A" />
        </svg>

        <h1
          style={{
            fontFamily: "'Fraunces', serif",
            fontSize: "38px",
            fontWeight: 600,
            color: "#E4E2DF",
            letterSpacing: "-0.5px",
            lineHeight: 1.1,
            marginBottom: "16px",
            maxWidth: "380px",
          }}
        >
          Backtesting
          <br />
          <em style={{ fontStyle: "italic" }}>inteligente</em>
          <br />
          para traders serios.
        </h1>

        <p
          style={{
            fontFamily: "'General Sans', sans-serif",
            fontSize: "13px",
            fontWeight: 400,
            color: "#6A6D72",
            lineHeight: 1.6,
            maxWidth: "320px",
          }}
        >
          Simulación histórica, análisis de mercado y estrategias algorítmicas
          en un solo lugar.
        </p>

        <div
          style={{
            marginTop: "48px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <div
            style={{
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              backgroundColor: "#4A9D7F",
            }}
          />
          <span
            style={{
              fontFamily: "'General Sans', sans-serif",
              fontSize: "10px",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.15em",
              color: "#6A6D72",
            }}
          >
            Edgecute v1.0
          </span>
        </div>
      </div>

      {/* RIGHT — formulario Clerk */}
      <div
        style={{
          width: "480px",
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "40px",
          backgroundColor: "#101213",
        }}
      >
        {/* routing="hash": los pasos del alta (email → código → continuar) van en
            el hash de la URL, no en sub-rutas. Con la página en `force-dynamic`,
            navegar entre sub-rutas por paso re-fetcheaba el RSC y hacía parpadear
            la tarjeta de registro varias veces antes del gate; el hash lo evita. */}
        <SignUp routing="hash" />
      </div>
    </div>
  );
}
