#!/usr/bin/env python3
"""
Driver del RE-PASE histórico de VOLUMEN (Opción A estricta).

Para cada mes del rango:
  1. GEN (windowed, gap>=BV_GAP_MIN, AUGUS_CLEAN_VOLUME=1) -> staging con `vol_recon`.
  2. MERGE_VOLUME_ONLY por cada fichero del lake del mes: congela O/H/L/C del lake y
     reescribe volume/transactions solo en las velas marcadas (gates duros; aborta si fallan).

Layout: 2022-2025 = data_0.parquet mensual (1 fichero/mes); 2026 = catchup_*.parquet por día.
Reanudable (checkpoint por mes). Backups por fichero (reversible). Gate abort = para todo.
NO sube a GCS ni purga caché ni reinicia: eso es el paso de ACTIVACIÓN manual posterior.

Env: BV_MODE (dry|apply, default dry), BV_FROM (2022-1), BV_TO (2026-6),
     BV_GAP_MIN (5), BV_WORKERS (8), BV_SKIP ("2026-7"), BV_LAKE, BV_STAGING_DIR,
     BV_BACKUP_DIR, BV_CKPT, ALERT_DISCORD_WEBHOOK (opcional), + las del gen (MASSIVE/GCS).
"""
import os, sys, json, glob, re, subprocess, time, urllib.request

HERE   = os.path.dirname(os.path.abspath(__file__))
GEN    = os.path.join(HERE, "gen_clean_augus_par.py")
MERGE  = os.path.join(HERE, "merge_volume_only.py")

LAKE    = os.getenv("BV_LAKE", "/lake/cold_storage/intraday_1m").rstrip("/")
STGDIR  = os.getenv("BV_STAGING_DIR", "/logs/vol_staging")
BACKUP  = os.getenv("BV_BACKUP_DIR", "/logs/vol_backup")
CKPT    = os.getenv("BV_CKPT", "/logs/vol_ckpt.json")
WORKERS = os.getenv("BV_WORKERS", "8")
GAP_MIN = os.getenv("BV_GAP_MIN", "5")
MODE    = os.getenv("BV_MODE", "dry")
SKIP    = set(x for x in os.getenv("BV_SKIP", "").split(",") if x)
DISCORD = os.getenv("ALERT_DISCORD_WEBHOOK", "").strip()

def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def months(a, b):
    ya, ma = [int(x) for x in a.split("-")]; yb, mb = [int(x) for x in b.split("-")]
    y, mo = ya, ma
    while (y, mo) <= (yb, mb):
        yield y, mo
        mo += 1
        if mo > 12: mo = 1; y += 1

def notify(msg):
    if not DISCORD: return
    try:
        req = urllib.request.Request(DISCORD, data=json.dumps({"content": msg[:1900]}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "btt-vol-repass/1.0"})
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        log(f"discord fail: {e}")

def run(cmd, extra_env=None):
    env = dict(os.environ)
    if extra_env: env.update(extra_env)
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr

def lake_files(y, mo):
    d = f"{LAKE}/year={y}/month={mo}"
    if y <= 2025:
        f = f"{d}/data_0.parquet"
        return [f] if os.path.exists(f) else []
    return sorted(glob.glob(f"{d}/catchup_intraday_*.parquet"))

def main():
    frm = os.getenv("BV_FROM", "2022-1"); to = os.getenv("BV_TO", "2026-6")
    os.makedirs(STGDIR, exist_ok=True); os.makedirs(BACKUP, exist_ok=True)
    ckpt = json.load(open(CKPT)) if os.path.exists(CKPT) else {"done": []}
    log(f"=== RE-PASE VOLUMEN {frm}..{to} mode={MODE} gap>={GAP_MIN} workers={WORKERS} skip={sorted(SKIP)} ===")
    started = time.time()
    for y, mo in months(frm, to):
        key = f"{y}-{mo}"
        if key in SKIP:        log(f"{key}: SKIP (env)"); continue
        if key in ckpt["done"]: log(f"{key}: ya hecho (ckpt)"); continue
        files = lake_files(y, mo)
        if not files:          log(f"{key}: sin ficheros de lake, skip"); continue

        # 1) gen -> staging con vol_recon
        stg = f"{STGDIR}/stg_{y}_{mo}.parquet"
        log(f"{key}: GEN gap>={GAP_MIN} -> staging ...")
        rc, out, err = run(
            [sys.executable, GEN, "--month", f"{y}-{mo}", "--window", "--workers", WORKERS,
             "--out", stg, "--tag", f"vol {key}"],
            extra_env={"AUGUS_GAP_MIN": GAP_MIN, "AUGUS_CLEAN_VOLUME": "1",
                       "AUGUS_PROGRESS": f"{STGDIR}/prog_{y}_{mo}.json"})
        if rc != 0:
            log(f"{key}: GEN FALLO rc={rc}\n{out[-1500:]}\n{err[-1500:]}")
            notify(f"⚠️ re-pase volumen {key}: GEN FALLO -> paro"); sys.exit(2)
        mt = re.search(r"\[FIN\][^\n]*marcadas=([\d,]+)", out); marc = mt.group(1) if mt else "?"
        if not os.path.exists(stg):
            log(f"{key}: gen sin staging (universo vacío) -> marco hecho")
            ckpt["done"].append(key); json.dump(ckpt, open(CKPT, "w")); continue

        # 2) merge_volume_only por fichero
        dry = ["--dry"] if MODE != "apply" else []
        for f in files:
            rc, out, err = run([sys.executable, MERGE, "--lake-file", f, "--staging", stg,
                                "--backup", BACKUP] + dry)
            gate_line = next((l for l in out.splitlines() if l.startswith("[") and "filas=" in l), out[-300:])
            log(f"{key}: {os.path.basename(f)} | {gate_line}")
            if rc != 0:
                log(f"{key}: GATE FALLO en {os.path.basename(f)} -> ABORTO\n{out[-1500:]}")
                notify(f"🛑 re-pase volumen {key}: GATE FALLO en {os.path.basename(f)} -> ABORTO"); sys.exit(2)

        ckpt["done"].append(key); json.dump(ckpt, open(CKPT, "w"))
        el = int((time.time() - started) / 60)
        log(f"{key}: OK ({len(files)} fichero(s), marcadas={marc}) [{el}min acum]")
        notify(f"🧼 re-pase volumen {key}: {len(files)} fichero(s), marcadas={marc} [{MODE}]")

    log(f"[FIN] re-pase volumen COMPLETO ({int((time.time()-started)/60)} min)")
    notify(f"✅ re-pase volumen COMPLETO [{MODE}] ({frm}..{to})")

if __name__ == "__main__":
    main()
