"""Re-etiquetado de propiedad por EMAIL para la migración Clerk dev → prod.

CONTEXTO. Los datos de usuario (estrategias, backtests, datasets, queries) viven
en users.duckdb keyed por Clerk user_id. Al crear la instancia Clerk de
PRODUCCIÓN, cada usuario recibe un user_id NUEVO (Clerk los genera; no se
conservan). El email SÍ se conserva, así que cruzamos old→new por email y hacemos
UPDATE de la columna user_id en toda tabla que la tenga. No se pierde dato; solo
se re-conecta la propiedad al login nuevo.

FLUJO (3 pasos, keys por env/flag — NUNCA hardcodeadas):

  1) Volcar el mapa email→user_id de CADA instancia Clerk:
       # instancia DEV (la actual): usa su Secret Key (sk_test_… o sk_…)
       python -m scripts.clerk_remap dump --clerk-secret "$CLERK_DEV_SECRET"  --out dev.json
       # instancia PROD (tras re-registro de los colegas): su Secret Key (sk_live_…)
       python -m scripts.clerk_remap dump --clerk-secret "$CLERK_PROD_SECRET" --out prod.json

  2) Construir el mapeo old→new (join por email; reporta no-emparejados):
       python -m scripts.clerk_remap build-map --old dev.json --new prod.json --out map.json

  3) Aplicar a users.duckdb (SIEMPRE probar antes con --dry-run):
       python -m scripts.clerk_remap apply --map map.json --dry-run
       python -m scripts.clerk_remap apply --map map.json          # ejecuta

SEGURIDAD / IDEMPOTENCIA:
  - Las Secret Keys se pasan por flag/env; el script no las imprime ni persiste.
  - `apply` introspecciona information_schema y actualiza TODA tabla con columna
    user_id (strategies/saved_queries/datasets/backtest_results/feature_votes/…),
    así no se olvida ninguna aunque el esquema crezca.
  - Idempotente: tras remapear, las filas old ya son new; re-correr con el mismo
    mapa encuentra 0 filas old = no-op. Un conflicto de PK (p.ej. feature_votes
    con PK round_id+user_id, si old y new votaron la misma ronda) se captura por
    tabla y se reporta, sin abortar el resto.
  - Correr en el ENTORNO cuyo users.duckdb se quiere cambiar (USER_DB_PATH).
    [WARN] En prod, users.duckdb se sincroniza a GCS al apagar — hacer el apply con la
    app parada (o forzar la subida después) para que el cambio persista.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional


CLERK_API_BASE = "https://api.clerk.com/v1"


# ── Clerk dump (email -> user_id) ─────────────────────────────────────────────
def _primary_email(user: dict) -> Optional[str]:
    """Primary verified email (lowercased) for a Clerk user object, or None."""
    pid = user.get("primary_email_address_id")
    addrs = user.get("email_addresses") or []
    chosen = None
    for a in addrs:
        if a.get("id") == pid:
            chosen = a
            break
    if chosen is None and addrs:
        chosen = addrs[0]  # fallback: first on file
    if not chosen:
        return None
    email = chosen.get("email_address")
    return email.strip().lower() if isinstance(email, str) and email.strip() else None


def cmd_dump(args) -> None:
    import httpx  # lazy: dump doesn't need duckdb

    secret = args.clerk_secret
    if not secret:
        sys.exit("--clerk-secret (or CLERK_SECRET env) is required")

    mapping: dict[str, str] = {}
    dupes: list[str] = []
    offset, page = 0, 500
    with httpx.Client(
        base_url=CLERK_API_BASE,
        headers={"Authorization": f"Bearer {secret}"},
        timeout=30.0,
    ) as c:
        while True:
            r = c.get("/users", params={"limit": page, "offset": offset})
            r.raise_for_status()
            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break
            for u in batch:
                email = _primary_email(u)
                uid = u.get("id")
                if not email or not uid:
                    continue
                if email in mapping and mapping[email] != uid:
                    dupes.append(email)  # same email on two Clerk users (rare)
                mapping[email] = uid
            offset += len(batch)
            if len(batch) < page:
                break

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, sort_keys=True)
    print(f"dumped {len(mapping)} email->user_id to {args.out}")
    if dupes:
        print(f"[WARN] {len(dupes)} email(s) appeared on >1 user (kept the last): {sorted(set(dupes))}")


# ── Build old->new map by email ───────────────────────────────────────────────
def cmd_build_map(args) -> None:
    with open(args.old, encoding="utf-8") as f:
        old = json.load(f)  # {email: old_uid}
    with open(args.new, encoding="utf-8") as f:
        new = json.load(f)  # {email: new_uid}

    mapping: dict[str, str] = {}
    unmatched_old: list[str] = []       # existed in dev, not yet re-registered in prod
    for email, ouid in old.items():
        nuid = new.get(email)
        if nuid:
            if nuid != ouid:            # identical id would be a no-op remap
                mapping[ouid] = nuid
        else:
            unmatched_old.append(email)
    new_only = [e for e in new if e not in old]  # brand-new prod users, nothing to remap

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, sort_keys=True)
    print(f"built {len(mapping)} old->new mappings to {args.out}")
    if unmatched_old:
        print(f"[WARN] {len(unmatched_old)} dev email(s) with NO prod match "
              f"(no re-registrados aún — sus datos quedan bajo el user_id viejo): "
              f"{sorted(unmatched_old)}")
    if new_only:
        print(f"[INFO] {len(new_only)} prod email(s) sin equivalente en dev (usuarios nuevos): "
              f"{sorted(new_only)}")


# ── Apply to users.duckdb ─────────────────────────────────────────────────────
def _user_db_path() -> str:
    try:
        from app.database import user_db_path
        return user_db_path()
    except Exception:
        import os
        return os.getenv("USER_DB_PATH", "users.duckdb")


def cmd_apply(args) -> None:
    import duckdb  # lazy: only apply needs it

    with open(args.map, encoding="utf-8") as f:
        mapping = json.load(f)  # {old_uid: new_uid}
    if not mapping:
        sys.exit("empty map: nothing to do (did build-map find matches?)")
    old_ids = list(mapping.keys())

    path = _user_db_path()
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}users.duckdb: {path}")
    con = duckdb.connect(path, read_only=args.dry_run)
    try:
        rows = con.execute(
            "SELECT DISTINCT table_name FROM information_schema.columns "
            "WHERE column_name = 'user_id' ORDER BY table_name"
        ).fetchall()
        tables = [r[0] for r in rows]
        if not tables:
            print("no tables with a user_id column found — nothing to remap")
            return
        print(f"tables with user_id: {tables}\n")

        grand = 0
        for t in tables:
            # placeholders for the IN (...) filter
            ph = ",".join(["?"] * len(old_ids))
            affected = con.execute(
                f"SELECT count(*) FROM {t} WHERE user_id IN ({ph})", old_ids
            ).fetchone()[0]
            if affected == 0:
                print(f"  {t}: 0 rows to remap")
                continue
            if args.dry_run:
                print(f"  {t}: would remap {affected} row(s)")
                grand += affected
                continue
            # apply per-mapping so we never assign the wrong new_id; per-table
            # try/except so a PK conflict on one table doesn't abort the rest.
            done, err = 0, None
            try:
                for old, new in mapping.items():
                    cur = con.execute(
                        f"UPDATE {t} SET user_id = ? WHERE user_id = ?", [new, old]
                    )
                    # duckdb doesn't expose rowcount reliably; recount not needed
                done = affected
            except Exception as e:  # noqa: BLE001 - report and continue
                err = str(e)
            if err:
                print(f"  {t}: [WARN] ERROR remapping ({err}) — left unchanged")
            else:
                print(f"  {t}: remapped {done} row(s)")
                grand += done

        print(f"\n{'[DRY-RUN] would remap' if args.dry_run else 'remapped'} "
              f"{grand} row(s) across {len(tables)} table(s)")
        if not args.dry_run:
            print("[WARN] Recuerda: en prod, forzar la subida de users.duckdb a GCS "
                  "(o hacerlo con la app parada) para que el cambio persista.")
    finally:
        con.close()


def main() -> None:
    try:  # make prints utf-8 safe on any console (Windows cp1252 included)
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Clerk dev->prod ownership remap by email.")
    sub = p.add_subparsers(dest="cmd", required=True)

    import os
    d = sub.add_parser("dump", help="dump email->user_id from a Clerk instance")
    d.add_argument("--clerk-secret", default=os.getenv("CLERK_SECRET", ""),
                   help="Clerk Secret Key (or CLERK_SECRET env)")
    d.add_argument("--out", required=True)
    d.set_defaults(func=cmd_dump)

    b = sub.add_parser("build-map", help="join old/new dumps by email -> {old:new}")
    b.add_argument("--old", required=True, help="dev dump (email->old_uid)")
    b.add_argument("--new", required=True, help="prod dump (email->new_uid)")
    b.add_argument("--out", required=True)
    b.set_defaults(func=cmd_build_map)

    a = sub.add_parser("apply", help="UPDATE user_id across users.duckdb")
    a.add_argument("--map", required=True, help="{old_uid: new_uid} json from build-map")
    a.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    a.set_defaults(func=cmd_apply)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
