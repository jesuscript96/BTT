"""Estrategias compartidas entre devs (Alvaro <-> Sailor) via JSON en el repo.

Una carpeta `estrategias_compartidas/` en la raiz del repo, con una subcarpeta
por dev y un JSON por estrategia compartida. El transporte es git: cada dev
commitea los ficheros que decide compartir y los integra por `staging`; la app
solo lee y escribe ficheros, nunca toca git.

Nada automatico: el fichero solo existe si el dev pulsa "Compartir" en la UI.
Re-compartir una estrategia sobreescribe el MISMO fichero (slug del nombre +
4 chars del id de origen), asi las actualizaciones dejan un diff limpio en vez
de amontonar copias.

Config por dev (en `backend/.env`, que no se commitea):
    SHARED_STRATEGIES_OWNER=alvaro|sailor   # subcarpeta propia (default: dev)
    SHARED_STRATEGIES_DIR=ruta/absoluta     # override de la carpeta (tests)
"""

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

# backend/app/services/shared_strategies.py -> parents[3] = raiz del repo
_REPO_ROOT = Path(__file__).resolve().parents[3]
FOLDER_NAME = "estrategias_compartidas"

# Slug + "--" + tag de id: alfanumerico, guiones sueltos o dobles, ".json".
# Sin puntos ni barras en el medio -> no hay traversal posible.
FILENAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.json$")


class InvalidSharedFilename(ValueError):
    """Filename con formato imposible (traversal, espacios, mayusculas...)."""


def shared_dir() -> Path:
    override = os.getenv("SHARED_STRATEGIES_DIR", "").strip()
    return Path(override).resolve() if override else _REPO_ROOT / FOLDER_NAME


def shared_owner() -> str:
    owner = os.getenv("SHARED_STRATEGIES_OWNER", "").strip().lower()
    # Solo para nombres de subcarpeta: fuera [a-z0-9-], a "dev".
    return owner if re.fullmatch(r"[a-z0-9][a-z0-9-]*", owner or "") else "dev"


def slugify(name: str, max_len: int = 50) -> str:
    # NFD separa a tilde en (a + '): se conserva la letra base y los acentos
    # no revientan el slug. Emoji y demas simbolos quedan fuera.
    norm = unicodedata.normalize("NFD", name or "")
    sin_tildes = "".join(c for c in norm if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", sin_tildes.lower()).strip("-")
    return slug[:max_len].strip("-") or "estrategia"


def build_filename(name: str, source_strategy_id: str) -> str:
    id_tag = re.sub(r"[^a-z0-9]", "", (source_strategy_id or "").lower())[:4]
    return f"{slugify(name)}--{id_tag or 'xxxx'}.json"


def _entry_from_payload(filename: str, data: dict) -> dict:
    return {
        "filename": filename,
        "shared_by": data.get("shared_by"),
        "shared_at": data.get("shared_at"),
        "source_strategy_id": data.get("source_strategy_id"),
        "name": data.get("name"),
        "description": data.get("description"),
        "definition": data.get("definition"),
    }


def list_shared() -> list:
    """Todos los JSON de todos los devs, con su metadata. Los ilegibles se
    saltan con un log (un fichero a medio escribir no debe tumbar el listado)."""
    root = shared_dir()
    entries = []
    if not root.is_dir():
        return entries
    for path in sorted(root.glob("*/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"[SHARED] fichero ilegible, se salta: {path} ({e})")
            continue
        entry = _entry_from_payload(path.name, data if isinstance(data, dict) else {})
        if not entry["shared_by"]:
            entry["shared_by"] = path.parent.name
        entries.append(entry)
    entries.sort(key=lambda e: (e.get("shared_by") or "", e.get("name") or ""))
    return entries


def write_shared(*, name: str, description, source_strategy_id: str, definition: dict) -> dict:
    """Escribe/sobreescribe el JSON de una estrategia en la subcarpeta del
    owner. `definition` es EXACTAMENTE el dict que guarda la tabla strategies."""
    owner = shared_owner()
    owner_dir = shared_dir() / owner
    owner_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "format_version": 1,
        "shared_by": owner,
        "shared_at": datetime.now().isoformat(timespec="seconds"),
        "source_strategy_id": source_strategy_id,
        "name": name or "sin nombre",
        "description": description or "",
        "definition": definition,
    }

    filename = build_filename(payload["name"], source_strategy_id)
    target = (owner_dir / filename).resolve()
    # build_filename ya sanitiza; esta contencion es la segunda barrera por si
    # un caller futuro pasa algo raro.
    if not target.is_relative_to(owner_dir.resolve()):
        raise InvalidSharedFilename(f"filename fuera de la carpeta compartida: {filename}")

    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return _entry_from_payload(filename, payload)


def delete_shared(filename: str) -> None:
    """Borra UNO de los ficheros del PROPIO owner (nunca los del otro dev)."""
    if not FILENAME_RE.match(filename or ""):
        raise InvalidSharedFilename(f"nombre de fichero no valido: {filename!r}")
    owner_dir = (shared_dir() / shared_owner()).resolve()
    target = (owner_dir / filename).resolve()
    if not target.is_relative_to(owner_dir) or not target.is_file():
        raise FileNotFoundError(f"no hay fichero compartido propio con ese nombre: {filename}")
    target.unlink()
