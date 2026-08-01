#!/usr/bin/env python3
"""ACTIVACIÓN del re-pase de VOLUMEN: sube el lake LIMPIO local a GCS.

Contexto: el re-pase (backfill_volume_driver.py) reescribió el lake LOCAL (raw) con el
volumen limpio (Opción A). Falta que GCS lo refleje para que:
  - CHARTS (view massive.intraday_1m = gs://.../cold_storage/intraday_1m/*/*/*.parquet,
    RAW hardcodeado en database.py) sirvan limpio → FASE A.
  - BACKTESTER (guarda optimized-vs-raw por mtime GCS, _prune_stale_optimized_paths)
    siga usando la copia optimized y limpia, no la rancia → FASE B regenera optimized
    desde el raw limpio y la sube DESPUÉS del raw (mtime opt>raw ⇒ el guard la mantiene).

Mirror EXACTO de la ruta local (month sin zero-pad, igual que ya está en GCS) ⇒ overwrite
1:1, sin duplicar objetos (el glob de charts leería duplicados si cambiara el padding).

Gates duros: tras subir, HEAD y comparo ContentLength == tamaño local (aborta si difiere).
FASE B además exige filas(optimized)==filas(raw) antes de subir.
Reanudable (checkpoint). Discord por fase + abort. NO purga caché ni reinicia (paso C manual).

Env: ACT_PHASE (all|raw|opt), ACT_RAW_YEARS ("2022,2023,2024,2025,2026"),
     BV_LAKE, BV_OPT, ACT_CKPT, GCS_BUCKET, GCS_HMAC_KEY/SECRET, ALERT_DISCORD_WEBHOOK.
"""
import os, sys, glob, json, time, urllib.request
import boto3
import duckdb
from botocore.config import Config

LAKE    = os.getenv("BV_LAKE", "/lake/cold_storage/intraday_1m").rstrip("/")
OPTROOT = os.getenv("BV_OPT",  "/lake/cold_storage/intraday_1m_optimized").rstrip("/")
BUCKET  = os.environ.get("GCS_BUCKET", "strategybuilderbbdd")
CKPT    = os.getenv("ACT_CKPT", "/logs/activate_ckpt.json")
DISCORD = os.getenv("ALERT_DISCORD_WEBHOOK", "").strip()
PHASE   = os.getenv("ACT_PHASE", "all")  # all | raw | opt
RAW_YEARS = [int(x) for x in os.getenv("ACT_RAW_YEARS", "2022,2023,2024,2025,2026").split(",") if x.strip()]
# optimized SOLO 2022-2025 (2026 se sirve de raw: días sueltos / mensual, sin optimized mensual estable)
OPT_MONTHS = [(y, m) for y in (2022, 2023, 2024, 2025) for m in range(1, 13)]


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def notify(msg):
    if not DISCORD: return
    try:
        req = urllib.request.Request(DISCORD, data=json.dumps({"content": msg[:1900]}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "btt-activate/1.0"})
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        log(f"discord fail: {e}")

def s3():
    return boto3.client("s3", endpoint_url="https://storage.googleapis.com",
        aws_access_key_id=os.environ["GCS_HMAC_KEY"], aws_secret_access_key=os.environ["GCS_HMAC_SECRET"],
        config=Config(signature_version="s3v4", request_checksum_calculation="when_required",
                      response_checksum_validation="when_required"))

def load_ckpt():
    try: return json.load(open(CKPT))
    except Exception: return {"raw_done": [], "opt_done": []}
def save_ckpt(c): json.dump(c, open(CKPT, "w"))

def head_size(cli, key):
    try: return cli.head_object(Bucket=BUCKET, Key=key)["ContentLength"]
    except Exception: return -1


def push_raw(cli, ck):
    files = []
    for y in RAW_YEARS:
        files += sorted(glob.glob(f"{LAKE}/year={y}/month=*/*.parquet"))
    log(f"FASE A raw: {len(files)} ficheros ({RAW_YEARS})")
    done = set(ck.get("raw_done", [])); ok = 0; sk = 0; nbytes = 0
    for f in files:
        rel = os.path.relpath(f, LAKE).replace("\\", "/")     # year=Y/month=M/basename
        key = f"cold_storage/intraday_1m/{rel}"
        lsz = os.path.getsize(f)
        if key in done and head_size(cli, key) == lsz:
            sk += 1; continue
        cli.upload_file(f, BUCKET, key)
        gsz = head_size(cli, key)
        if gsz != lsz:
            log(f"[GATE] {key} size GCS={gsz} != local={lsz} -> ABORTO")
            notify(f"🛑 ACT raw GATE size {key}"); sys.exit(2)
        done.add(key); ck["raw_done"] = sorted(done); save_ckpt(ck)
        ok += 1; nbytes += lsz
        if ok % 12 == 0: log(f"  raw subidos={ok} ({nbytes/1e9:.1f} GB) last={key}")
    log(f"FASE A OK: subidos={ok} skip={sk} ({nbytes/1e9:.1f} GB)")
    notify(f"🟢 ACT Fase A (raw→GCS) COMPLETA: {ok} subidos, {sk} ya estaban, {nbytes/1e9:.1f} GB")


def regen_opt(cli, ck):
    done = set(ck.get("opt_done", [])); ok = 0
    log(f"FASE B optimized: {len(OPT_MONTHS)} meses candidatos")
    for (y, m) in OPT_MONTHS:
        tag = f"{y}-{m}"
        gl = f"{LAKE}/year={y}/month={m}/data_0.parquet"
        if not os.path.exists(gl): log(f"[{tag}] sin raw local -> skip"); continue
        if tag in done: continue
        outd = f"{OPTROOT}/year={y}/month={m}"; os.makedirs(outd, exist_ok=True)
        out = f"{outd}/data.parquet"; tmp = out + ".tmp"
        tt = time.time()
        con = duckdb.connect()
        con.execute("SET memory_limit='8GB'; SET threads=4;")
        con.execute(f"SET temp_directory='{LAKE}/_tmp_duckdb';")
        nraw = con.execute(f"SELECT count(*) FROM read_parquet('{gl}')").fetchone()[0]
        con.execute(f"COPY (SELECT * FROM read_parquet('{gl}') ORDER BY ticker) TO '{tmp}' (FORMAT PARQUET)")
        nopt = con.execute(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchone()[0]
        con.close()
        if nopt != nraw:
            os.remove(tmp); log(f"[{tag}] GATE filas opt={nopt} != raw={nraw} -> ABORTO")
            notify(f"🛑 ACT opt GATE filas {tag}"); sys.exit(2)
        os.replace(tmp, out)
        key = f"cold_storage/intraday_1m_optimized/year={y}/month={m}/data.parquet"
        cli.upload_file(out, BUCKET, key)
        if head_size(cli, key) != os.path.getsize(out):
            log(f"[{tag}] GATE upload size -> ABORTO"); notify(f"🛑 ACT opt upload {tag}"); sys.exit(2)
        done.add(tag); ck["opt_done"] = sorted(done); save_ckpt(ck); ok += 1
        log(f"[{tag}] OK {nopt:,} filas, {os.path.getsize(out)/1e6:.0f} MB, subido ({time.time()-tt:.0f}s)")
    log(f"FASE B OK: {ok} meses regenerados+subidos")
    notify(f"🟢 ACT Fase B (optimized→GCS) COMPLETA: {ok} meses")


def main():
    ck = load_ckpt(); cli = s3(); t0 = time.time()
    notify(f"🚀 ACTIVACIÓN volumen→GCS arranca (phase={PHASE})")
    if PHASE in ("all", "raw"): push_raw(cli, ck)
    if PHASE in ("all", "opt"): regen_opt(cli, ck)
    log(f"[FIN] activación GCS en {(time.time()-t0)/60:.1f} min")
    notify(f"✅ ACTIVACIÓN GCS COMPLETA (phase={PHASE}) — falta purga caché + restart (paso C)")


if __name__ == "__main__":
    main()
