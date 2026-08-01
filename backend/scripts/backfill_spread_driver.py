#!/usr/bin/env python3
"""Driver del RE-PASE POR-SPREAD (mercado completo, sin filtro de gap).

Cierra el hueco del re-pase por-gap: ticker-días con misprints premarket (spread>5%)
pero gap<5% que el universo gap>=5 dejaba fuera (p.ej. LIFW 2024-07-23, CNSP, SLNA…).

Por cada mes:
  1. DETECT (detect_dirty_month.py): lee el lake, saca ticker-días con barra PM spread>5%
     (CS/ADRC, sin gap) -> CSV Ticker,Date. Barato, local.
  2. GEN (--csv, --window, AUGUS_CLEAN_VOLUME=1): reconstruye O/H/L/C + volumen de las
     barras marcadas desde trades NBBO-válidos -> staging con vol_recon.
  3. MERGE_OHLCV_RECON por fichero del lake: aplica OHLCV solo en velas marcadas,
     el resto EXACTO como el lake. Gates duros (aborta si fallan).

Reanudable (checkpoint por mes). Backups por fichero. Gate abort = para todo.
NO sube a GCS ni purga caché: eso es la ACTIVACIÓN posterior (activate_volume_to_gcs.py).

Env: SP_MODE (dry|apply), SP_FROM (2022-1), SP_TO (2026-7), SP_WORKERS (8),
     SP_LAKE (raíz intraday_1m), SP_STAGING_DIR, SP_BACKUP_DIR, SP_CSV_DIR, SP_CKPT,
     SP_SKIP, ALERT_DISCORD_WEBHOOK, + las del gen (MASSIVE/GCS).
"""
import os, sys, json, glob, re, subprocess, time, urllib.request

HERE   = os.path.dirname(os.path.abspath(__file__))
DETECT = os.path.join(HERE, "detect_dirty_month.py")
GEN    = os.path.join(HERE, "gen_clean_augus_par.py")
MERGE  = os.path.join(HERE, "merge_ohlcv_recon.py")

LAKE    = os.getenv("SP_LAKE", "/lake/cold_storage/intraday_1m").rstrip("/")
STGDIR  = os.getenv("SP_STAGING_DIR", "/logs/sp_staging")
CSVDIR  = os.getenv("SP_CSV_DIR", "/logs/sp_csv")
BACKUP  = os.getenv("SP_BACKUP_DIR", "/logs/sp_backup")
CKPT    = os.getenv("SP_CKPT", "/logs/sp_ckpt.json")
WORKERS = os.getenv("SP_WORKERS", "8")
MODE    = os.getenv("SP_MODE", "dry")
SKIP    = set(x for x in os.getenv("SP_SKIP", "").split(",") if x)
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
            headers={"Content-Type": "application/json", "User-Agent": "btt-spread-repass/1.0"})
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
    files = sorted(glob.glob(f"{d}/catchup_intraday_*.parquet"))
    f0 = f"{d}/data_0.parquet"
    if os.path.exists(f0): files.append(f0)
    return files

def main():
    frm = os.getenv("SP_FROM", "2022-1"); to = os.getenv("SP_TO", "2026-7")
    for d in (STGDIR, CSVDIR, BACKUP): os.makedirs(d, exist_ok=True)
    ckpt = json.load(open(CKPT)) if os.path.exists(CKPT) else {"done": []}
    log(f"=== RE-PASE POR-SPREAD {frm}..{to} mode={MODE} workers={WORKERS} skip={sorted(SKIP)} ===")
    started = time.time()
    for y, mo in months(frm, to):
        key = f"{y}-{mo}"
        if key in SKIP:         log(f"{key}: SKIP (env)"); continue
        if key in ckpt["done"]: log(f"{key}: ya hecho (ckpt)"); continue
        files = lake_files(y, mo)
        if not files:           log(f"{key}: sin ficheros de lake, skip"); continue

        # 1) DETECT -> CSV
        csvf = f"{CSVDIR}/dirty_{y}_{mo}.csv"
        rc, out, err = run([sys.executable, DETECT, "--year", str(y), "--month", str(mo),
                            "--lake-root", LAKE, "--out", csvf])
        if rc != 0:
            log(f"{key}: DETECT FALLO rc={rc}\n{out[-800:]}\n{err[-800:]}")
            notify(f"⚠️ spread {key}: DETECT FALLO -> paro"); sys.exit(2)
        ndirty = 0
        try: ndirty = sum(1 for _ in open(csvf)) - 1
        except Exception: pass
        log(f"{key}: {out.strip().splitlines()[-1] if out.strip() else 'detect ok'}")
        if ndirty <= 0:
            log(f"{key}: 0 ticker-días sucios -> marco hecho")
            ckpt["done"].append(key); json.dump(ckpt, open(CKPT, "w")); continue

        # 2) GEN --csv -> staging con vol_recon
        stg = f"{STGDIR}/stg_{y}_{mo}.parquet"
        log(f"{key}: GEN (--csv {ndirty} td) -> staging ...")
        rc, out, err = run(
            [sys.executable, GEN, "--csv", csvf, "--window", "--workers", WORKERS,
             "--out", stg, "--tag", f"spread {key}"],
            extra_env={"AUGUS_CLEAN_VOLUME": "1", "AUGUS_PROGRESS": f"{STGDIR}/prog_{y}_{mo}.json"})
        if rc != 0:
            log(f"{key}: GEN FALLO rc={rc}\n{out[-1500:]}\n{err[-800:]}")
            notify(f"⚠️ spread {key}: GEN FALLO -> paro"); sys.exit(2)
        mt = re.search(r"\[FIN\][^\n]*marcadas=([\d,]+)", out); marc = mt.group(1) if mt else "?"
        if not os.path.exists(stg):
            log(f"{key}: gen sin staging -> marco hecho")
            ckpt["done"].append(key); json.dump(ckpt, open(CKPT, "w")); continue

        # 3) MERGE_OHLCV_RECON por fichero (backup por-mes: los data_0.parquet mensuales
        #    comparten nombre; un dir plano colisionaría y se perderían backups)
        dry = ["--dry"] if MODE != "apply" else []
        bdir = f"{BACKUP}/{y}_{mo}"
        for f in files:
            rc, out, err = run([sys.executable, MERGE, "--lake-file", f, "--staging", stg,
                                "--backup", bdir] + dry)
            gate_line = next((l for l in out.splitlines() if l.startswith("[") and "filas=" in l), out[-300:])
            log(f"{key}: {os.path.basename(f)} | {gate_line}")
            if rc != 0:
                log(f"{key}: GATE FALLO en {os.path.basename(f)} -> ABORTO\n{out[-1500:]}")
                notify(f"🛑 spread {key}: GATE FALLO en {os.path.basename(f)} -> ABORTO"); sys.exit(2)

        ckpt["done"].append(key); json.dump(ckpt, open(CKPT, "w"))
        el = int((time.time() - started) / 60)
        log(f"{key}: OK ({ndirty} td, {len(files)} fichero(s), marcadas={marc}) [{el}min acum]")
        notify(f"🧽 spread {key}: {ndirty} td sucios, marcadas={marc} [{MODE}]")

    log(f"[FIN] re-pase POR-SPREAD COMPLETO ({int((time.time()-started)/60)} min)")
    notify(f"✅ re-pase POR-SPREAD COMPLETO [{MODE}] ({frm}..{to})")

if __name__ == "__main__":
    main()
