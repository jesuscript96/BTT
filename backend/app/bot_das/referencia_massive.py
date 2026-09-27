"""REST de Massive: ficha del ticker (list_date, SIC, tipo, market cap) y splits del día, con caché diaria.

QUÉ HACE. `Referencia.ficha(ticker)` consulta `/v3/reference/tickers/{t}` y
`Referencia.splits_de_hoy(hoy)` consulta `/v3/reference/splits?execution_date=`
siguiendo `next_url` si hay más páginas. Lo que se consigue se guarda en
memoria y en `cache/referencia_AAAA-MM-DD.json` (una ficha no cambia dentro
del día), así el segundo `ficha("XYZ")` del día no abre red. Lo que NO se
consigue devuelve None y NO se cachea: A12 (no se opera, se reintenta) y la
corrección 17 (sin lista de splits el decisor no excluye y avisa una vez).

POR QUÉ ESTÁ AQUÍ. R-A-03 v2 excluye SPAC (SIC 6770), IPO < 30 días y splits
del día; Massive lo da por REST. NUNCA websocket: la única conexión al socket
de Massive es la del bot de alertas (R-A-06.4) y una cuarta conexión provocó
cinco cortes 1008 el 22-sep. Es la misma clave que `bot_alerts_feed.clave_bot`
(`MASSIVE_BOT_API_KEY`), leída en la llamada (`desde_env`), nunca al importar.

LAS TRAMPAS.
  * La clave viaja SOLO en la cabecera `Authorization: Bearer …`: nunca en la
    URL (`bot_alerts_feed` la pone en `params={"apiKey"}` y de ahí la fuga de
    la memoria «httpx filtra tokens»), nunca en el log, nunca en
    `ultimo_error`: todo texto de error pasa por `_limpiar`, que borra el valor
    literal (R-Q-01, riesgo 20). Si `next_url` trajera `apiKey`, se quita.
  * `next_url` solo se sigue si apunta al MISMO host que la base: la cabecera
    con la clave no se manda a un tercero. Otro host → None (lista incompleta).
  * Las funciones de red NUNCA lanzan: None = no se pudo preguntar; `set()` =
    Massive contestó que no hay splits hoy. Un cuerpo que no es JSON o cuyo
    `results` no tiene la forma esperada también es None.
  * `urllib.request.urlopen` usa el almacén de certificados de Windows (por eso
    el feed evita `certifi` con el antivirus); `abrir` es inyectable para los
    tests: se llama `abrir(Request, timeout=…)` y se lee `.read()` del
    resultado, que se cierra si tiene `.close()`.
  * El fichero de caché se escribe en un temporal + `os.replace`; una caché
    corrupta o ilegible se ignora (se vuelve a preguntar), nunca tumba nada.
  * `Ficha` vive en `tipos.py` (ajuste (a)); aquí se reexporta.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

from app.bot_das.reglas.precios import de_float
from app.bot_das.tipos import Ficha

__all__ = ["Ficha", "Referencia", "BASE_URL_DEFECTO", "VARIABLE_CLAVE", "VARIABLE_BASE_URL",
           "TIMEOUT_S_DEFECTO", "PAGINAS_MAX", "LIMITE_PAGINA"]

BASE_URL_DEFECTO = "https://api.massive.com"    # bot_alerts_feed.REST (MASSIVE_API_BASE_URL)
VARIABLE_CLAVE = "MASSIVE_BOT_API_KEY"          # la del BOT, nunca MASSIVE_API_KEY (bot_alerts_feed.clave_bot)
VARIABLE_BASE_URL = "MASSIVE_API_BASE_URL"
TIMEOUT_S_DEFECTO = 8.0                         # §3.13
PAGINAS_MAX = 50                                # guardia contra un `next_url` que no termina
LIMITE_PAGINA = 1000                            # máximo que admite /v3/reference/splits
_PARAMETRO_CLAVE_URL = "apikey"                 # si un next_url lo trajera, se elimina (comparación sin mayúsculas)

logger = logging.getLogger("btt.bot_das.referencia")


class Referencia:
    """Consultas de referencia a Massive con caché por día. Nunca lanza; None = no se pudo preguntar."""

    def __init__(self, clave: str, cache_dir: Path, reloj, timeout_s: float = TIMEOUT_S_DEFECTO,
                 abrir: Callable[..., Any] = urllib.request.urlopen, base_url: str = BASE_URL_DEFECTO) -> None:
        self._clave = (clave or "").strip()
        self._cache_dir = Path(cache_dir)
        self._reloj = reloj
        self._timeout_s = float(timeout_s)
        self._abrir = abrir
        self._base = (base_url or BASE_URL_DEFECTO).strip().rstrip("/")
        self._host = urllib.parse.urlsplit(self._base).netloc.lower()
        self._dia: Optional[date] = None
        self._fichas: dict[str, Ficha] = {}
        self._splits: dict[str, set[str]] = {}
        self.peticiones = 0                      # aperturas de red intentadas
        self.errores = 0
        self.ultimo_error: Optional[str] = None  # siempre limpio de la clave
        self._avisado_sin_clave = False          # el «sin clave» se registra una vez por instancia, no por señal

    @classmethod
    def desde_env(cls, cache_dir: Path, reloj, timeout_s: float = TIMEOUT_S_DEFECTO,
                  abrir: Callable[..., Any] = urllib.request.urlopen) -> "Referencia":
        """Lee `MASSIVE_BOT_API_KEY` (y `MASSIVE_API_BASE_URL` si existe) EN LA LLAMADA (R-Q-01). Sin clave, todo devuelve None."""
        clave = os.getenv(VARIABLE_CLAVE, "").strip()
        base = os.getenv(VARIABLE_BASE_URL, "").strip() or BASE_URL_DEFECTO
        return cls(clave, cache_dir, reloj, timeout_s=timeout_s, abrir=abrir, base_url=base)

    @property
    def tiene_clave(self) -> bool:
        return bool(self._clave)

    @property
    def base_url(self) -> str:
        return self._base

    # ── consultas ───────────────────────────────────────────────────────
    def ficha(self, ticker: str) -> Optional[Ficha]:
        """`/v3/reference/tickers/{t}` → Ficha (R-A-03 v2); caché por día; None si falla o el JSON no tiene la forma esperada (A12)."""
        simbolo = str(ticker).strip().upper()
        if not simbolo:
            return None
        self._asegurar_dia()
        ficha = self._fichas.get(simbolo)
        if ficha is not None:
            return ficha
        cuerpo = self._get(f"{self._base}/v3/reference/tickers/{urllib.parse.quote(simbolo, safe='')}")
        if cuerpo is None:
            return None
        ficha = _ficha_de_json(simbolo, cuerpo)
        if ficha is None:
            self._registrar_error(f"ficha de {simbolo}: JSON sin «results» con la forma esperada")
            return None
        self._fichas[simbolo] = ficha
        self._guardar()
        return ficha

    def splits_de_hoy(self, hoy: date) -> Optional[set[str]]:
        """`/v3/reference/splits?execution_date=hoy` con paginación → tickers con split/contrasplit hoy; None si no se pudo.

        `set()` es una respuesta real (no hay splits). None → el decisor NO
        excluye y avisa nivel 2 una vez (corrección 17, riesgo 35).
        """
        self._asegurar_dia()
        clave = hoy.isoformat()
        if clave in self._splits:
            return set(self._splits[clave])
        url = f"{self._base}/v3/reference/splits?" + urllib.parse.urlencode(
            {"execution_date": clave, "limit": LIMITE_PAGINA})
        tickers: set[str] = set()
        for _ in range(PAGINAS_MAX):
            cuerpo = self._get(url)
            if cuerpo is None:
                return None
            if not isinstance(cuerpo, dict):
                self._registrar_error("splits: el cuerpo no es un objeto JSON")
                return None
            resultados = cuerpo.get("results", [])
            if resultados is None:
                resultados = []
            if not isinstance(resultados, list):
                self._registrar_error("splits: «results» no es una lista")
                return None
            for fila in resultados:
                if not isinstance(fila, dict):
                    continue
                simbolo = fila.get("ticker")
                fecha = fila.get("execution_date")
                if isinstance(simbolo, str) and simbolo.strip() and (fecha is None or fecha == clave):
                    tickers.add(simbolo.strip().upper())
            siguiente = cuerpo.get("next_url")
            if not siguiente:
                self._splits[clave] = set(tickers)
                self._guardar()
                return set(tickers)
            url_siguiente = self._url_siguiente(siguiente)
            if url_siguiente is None:
                self._registrar_error("splits: next_url apunta a otro host o no es una URL; lista incompleta")
                return None
            url = url_siguiente
        self._registrar_error(f"splits: más de {PAGINAS_MAX} páginas; lista incompleta")
        return None

    # ── red (frontera: nunca lanza) ─────────────────────────────────────
    def _get(self, url: str) -> Optional[Any]:
        """GET con `Authorization: Bearer` → JSON decodificado, o None (sin clave, error de red/HTTP, cuerpo no JSON)."""
        if not self._clave:
            if not self._avisado_sin_clave:
                self._avisado_sin_clave = True
                self._registrar_error(f"sin clave ({VARIABLE_CLAVE}): no se consulta Massive")
            return None
        peticion = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._clave}",
                                                        "Accept": "application/json"})
        self.peticiones += 1
        try:
            respuesta = self._abrir(peticion, timeout=self._timeout_s)
            try:
                crudo = respuesta.read()
            finally:
                cerrar = getattr(respuesta, "close", None)
                if callable(cerrar):
                    cerrar()
        except Exception as exc:  # noqa: BLE001  — frontera de red (R-A-03 v2 / A12): None = no se pudo preguntar, jamás lanzar
            self._registrar_error(f"{type(exc).__name__}: {exc}")
            return None
        try:
            texto = crudo.decode("utf-8") if isinstance(crudo, (bytes, bytearray)) else str(crudo)
            return json.loads(texto)
        except (ValueError, UnicodeDecodeError) as exc:
            self._registrar_error(f"respuesta que no es JSON ({type(exc).__name__})")
            return None

    def _url_siguiente(self, siguiente: object) -> Optional[str]:
        """`next_url` del mismo host, sin ningún `apiKey` en la query; None si no es de fiar."""
        if not isinstance(siguiente, str) or not siguiente.strip():
            return None
        partes = urllib.parse.urlsplit(siguiente.strip())
        if partes.scheme not in ("http", "https") or partes.netloc.lower() != self._host:
            return None
        consulta = [(k, v) for k, v in urllib.parse.parse_qsl(partes.query, keep_blank_values=True)
                    if k.lower() != _PARAMETRO_CLAVE_URL]
        return urllib.parse.urlunsplit((partes.scheme, partes.netloc, partes.path,
                                        urllib.parse.urlencode(consulta), ""))

    def _registrar_error(self, texto: str) -> None:
        self.errores += 1
        self.ultimo_error = self._limpiar(texto)
        logger.warning("[REFERENCIA] %s", self.ultimo_error)

    def _limpiar(self, texto: str) -> str:
        """Borra el valor literal de la clave (R-Q-01): nada de lo que salga de aquí puede llevarla."""
        if self._clave and self._clave in texto:
            return texto.replace(self._clave, "***")
        return texto

    # ── caché diaria (memoria + fichero) ────────────────────────────────
    def _asegurar_dia(self) -> None:
        hoy = self._reloj.hoy()
        if hoy == self._dia:
            return
        self._dia = hoy
        self._fichas = {}
        self._splits = {}
        self._cargar()

    def ruta_cache(self) -> Path:
        """`cache/referencia_AAAA-MM-DD.json` del día del reloj (§1)."""
        dia = self._dia or self._reloj.hoy()
        return self._cache_dir / f"referencia_{dia.isoformat()}.json"

    def _cargar(self) -> None:
        ruta = self.ruta_cache()
        try:
            if not ruta.exists():
                return
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:   # frontera de fichero: una caché ilegible se ignora, se vuelve a preguntar
            logger.warning("[REFERENCIA] caché %s ilegible (%s): se ignora", ruta.name, type(exc).__name__)
            return
        if not isinstance(datos, dict):
            return
        fichas = datos.get("fichas")
        if isinstance(fichas, dict):
            for simbolo, crudo in fichas.items():
                ficha = _ficha_de_dict(str(simbolo).strip().upper(), crudo)
                if ficha is not None:
                    self._fichas[ficha.ticker] = ficha
        splits = datos.get("splits")
        if isinstance(splits, dict):
            for dia, lista in splits.items():
                if isinstance(lista, list):
                    self._splits[str(dia)] = {str(t).strip().upper() for t in lista if str(t).strip()}

    def _guardar(self) -> None:
        ruta = self.ruta_cache()
        datos = {
            "dia": self._dia.isoformat() if self._dia else None,
            "fichas": {t: _ficha_a_dict(f) for t, f in sorted(self._fichas.items())},
            "splits": {d: sorted(s) for d, s in sorted(self._splits.items())},
        }
        temporal = ruta.with_name(ruta.name + ".tmp")
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(temporal, ruta)
        except OSError as exc:   # frontera de fichero: sin caché en disco se sigue con la de memoria
            logger.warning("[REFERENCIA] no se pudo escribir la caché %s (%s)", ruta.name, type(exc).__name__)


# ── conversión de JSON ──────────────────────────────────────────────────
def _ficha_de_json(simbolo: str, cuerpo: Any) -> Optional[Ficha]:
    """`{"results": {...}}` de /v3/reference/tickers/{t} → Ficha; None si no tiene esa forma."""
    if not isinstance(cuerpo, dict):
        return None
    resultados = cuerpo.get("results")
    if not isinstance(resultados, dict):
        return None
    return _ficha_de_dict(simbolo, resultados)


def _ficha_de_dict(simbolo: str, crudo: Any) -> Optional[Ficha]:
    """Campos tolerantes: list_date ISO o None; sic_code como texto; market_cap Decimal; nombre texto (vacío si falta)."""
    if not isinstance(crudo, dict) or not simbolo:
        return None
    return Ficha(
        ticker=simbolo,
        list_date=_fecha(crudo.get("list_date")),
        sic_code=_texto(crudo.get("sic_code")),
        tipo=_texto(crudo.get("type")),
        market_cap=_decimal(crudo.get("market_cap")),
        nombre=_texto(crudo.get("name")) or "",
    )


def _ficha_a_dict(ficha: Ficha) -> dict:
    return {
        "list_date": ficha.list_date.isoformat() if ficha.list_date else None,
        "sic_code": ficha.sic_code,
        "type": ficha.tipo,
        "market_cap": str(ficha.market_cap) if ficha.market_cap is not None else None,
        "name": ficha.nombre,
    }


def _fecha(valor: object) -> Optional[date]:
    if not isinstance(valor, str):
        return None
    try:
        return date.fromisoformat(valor.strip()[:10])
    except ValueError:
        return None


def _texto(valor: object) -> Optional[str]:
    if valor is None or isinstance(valor, bool):
        return None
    texto = str(valor).strip()
    return texto or None


def _decimal(valor: object) -> Optional[Decimal]:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return de_float(valor)
    except ValueError:
        return None
