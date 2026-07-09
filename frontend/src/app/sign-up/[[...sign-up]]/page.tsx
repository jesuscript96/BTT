import Link from "next/link";

// Registro CERRADO: el alta está bloqueada en Clerk (Restrictions -> sign-up
// mode = Restricted), que es lo que impide de verdad crear cuentas. Esta página
// sustituye al <SignUp /> para que el visitante vea un mensaje en vez del error
// crudo de Clerk. Para reabrir el registro: volver a poner <SignUp /> aquí Y
// cambiar el sign-up mode a Public en el dashboard de Clerk (ambas cosas).
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

      {/* RIGHT — registro cerrado (sustituye al formulario de Clerk) */}
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
        <div
          style={{
            width: "100%",
            maxWidth: "360px",
            border: "0.5px solid #2C2F33",
            borderRadius: "10px",
            padding: "36px 32px",
            backgroundColor: "#16181A",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              marginBottom: "20px",
            }}
          >
            <div
              style={{
                width: "6px",
                height: "6px",
                borderRadius: "50%",
                backgroundColor: "#D87A3D",
              }}
            />
            <span
              style={{
                fontFamily: "'General Sans', sans-serif",
                fontSize: "10px",
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.15em",
                color: "#D87A3D",
              }}
            >
              Acceso por invitación
            </span>
          </div>

          <h2
            style={{
              fontFamily: "'Fraunces', serif",
              fontSize: "24px",
              fontWeight: 600,
              color: "#E4E2DF",
              letterSpacing: "-0.3px",
              lineHeight: 1.2,
              marginBottom: "12px",
            }}
          >
            El registro está cerrado
          </h2>

          <p
            style={{
              fontFamily: "'General Sans', sans-serif",
              fontSize: "13px",
              fontWeight: 400,
              color: "#8B8E93",
              lineHeight: 1.65,
              marginBottom: "28px",
            }}
          >
            Estamos afinando Edgecute con un grupo reducido de traders. Abriremos
            el acceso muy pronto — si ya tienes una cuenta, puedes entrar con
            ella.
          </p>

          <Link
            href="/sign-in"
            style={{
              display: "block",
              textAlign: "center",
              fontFamily: "'General Sans', sans-serif",
              fontSize: "13px",
              fontWeight: 600,
              color: "#16181A",
              backgroundColor: "#D87A3D",
              borderRadius: "6px",
              padding: "11px 16px",
              textDecoration: "none",
            }}
          >
            Iniciar sesión
          </Link>
        </div>
      </div>
    </div>
  );
}
