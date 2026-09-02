"""Modelos avanzados: XGBoost (y opcionalmente un HMM) sobre el motor de siempre.

Dos modos, los dos con la MISMA idea de fondo: el modelo no sustituye al motor,
lo acompaña.

  · "filter"     — las reglas de la estrategia encuentran los setups como
                   siempre; el modelo decide cuáles merecen la pena. Es una
                   máscara sobre `entries`, nada más.
  · "standalone" — no hay reglas de entrada: entra donde el modelo dice.

Lo que NO se toca: el simulador, la gestión de riesgo, las métricas, el gráfico
ni el Walk Forward. El único punto de contacto es la máscara de entradas, en el
mismo sitio donde el "swing" ya filtra hoy.

────────────────────────────────────────────────────────────────────────────
LA PARTE QUE HAY QUE ENTENDER: por qué el HMM de serie tiene look-ahead
────────────────────────────────────────────────────────────────────────────
`hmm.predict()` ejecuta Viterbi y `hmm.predict_proba()` ejecuta forward-backward.
Los dos miran la secuencia ENTERA: el estado que asignan a las 09:35 está
calculado sabiendo lo que pasó a las 15:00 de ESE MISMO DÍA. Da igual que el
modelo se haya entrenado con otro periodo — el look-ahead está en la inferencia,
no en el entrenamiento.

Por eso aquí la recursión hacia delante está escrita a mano (`hmm_filtered_proba`)
en lugar de llamar a la librería: cada fila usa solo el pasado. Es la diferencia
entre un backtest que se puede reproducir en vivo y uno que no.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.services.indicators import compute_indicator

logger = logging.getLogger("backtester.advanced_model")


# ── Features ──────────────────────────────────────────────────────────────

# Indicadores que son un NIVEL DE PRECIO. Su valor crudo no sirve como feature:
# el modelo aprendería que "18,40 dólares" significa algo, y eso no se traslada
# a otro ticker ni a otro año. Se convierten en DISTANCIA en % al cierre, que sí
# es comparable entre acciones de 2 $ y de 200 $.
_PRICE_LEVEL_INDICATORS = frozenset({
    "SMA", "EMA", "WMA", "VWAP", "AVWAP", "Bollinger Bands", "Donchian",
    "Darvas Box", "Previous max", "Previous min", "PM High", "PM Low", "PM Open",
    "RTH Open", "RTH High", "RTH Low", "AM Open", "Day Open", "High of Day",
    "Low of Day", "Yesterday Open", "Yesterday Close", "Yesterday High",
    "Yesterday Low", "Previous Close", "High of last X days",
    "Low of last X days", "Max N Bars", "Bar Close", "Bar Open", "High Bar",
    "Low Bar", "Prev. Bar Close", "Prev. Bar Open", "Prev. Bar High",
    "Prev. Bar Low", "Linear Regression", "Parabolic SAR", "Opening range +",
    "Opening range -", "Opening range AM +", "Opening range AM -",
})


def feature_label(cfg: dict) -> str:
    """Nombre legible de la columna, con sus parámetros. Se usa en la interfaz
    y en la importancia de features, así que dos configuraciones distintas del
    mismo indicador tienen que leerse distinto."""
    name = cfg.get("name", "?")
    partes = [f"{k}={cfg[k]}" for k in
              ("period", "period2", "period3", "ap_session", "session_ref",
               "fade_ref", "band_line", "range_minutes", "squeeze_direction")
              if cfg.get(k) is not None]
    return f"{name}({', '.join(partes)})" if partes else name


def build_feature_matrix(
    df: pd.DataFrame,
    daily_stats: dict | None,
    feature_defs: list[dict],
    cache: dict | None = None,
) -> np.ndarray:
    """Una columna por feature, una fila por vela del ticker-día.

    Cada feature se calcula con `compute_indicator`, el MISMO código que dispara
    las condiciones. No hay una segunda implementación que pueda divergir, y los
    indicadores causales lo siguen siendo aquí.
    """
    n = len(df)
    cols: list[np.ndarray] = []
    close = np.asarray(df["close"], dtype=np.float64)

    for cfg in feature_defs:
        name = cfg.get("name")
        serie = compute_indicator(
            name, df,
            period=cfg.get("period"), period2=cfg.get("period2"),
            period3=cfg.get("period3"), std_dev=cfg.get("stdDev"),
            multiplier=cfg.get("multiplier"), offset=cfg.get("offset", 0),
            days_lookback=cfg.get("days_lookback"),
            band_line=cfg.get("band_line"), orb_minutes=cfg.get("orb_minutes"),
            ap_session=cfg.get("ap_session"), daily_stats=daily_stats,
            cache=cache, range_minutes=cfg.get("range_minutes"),
            session_ref=cfg.get("session_ref"),
            squeeze_direction=cfg.get("squeeze_direction"),
            fade_ref=cfg.get("fade_ref"),
        )
        vals = np.asarray(serie, dtype=np.float64)
        if len(vals) != n:                       # defensivo: nunca deberia pasar
            vals = np.full(n, np.nan)
        if name in _PRICE_LEVEL_INDICATORS:
            with np.errstate(divide="ignore", invalid="ignore"):
                vals = np.where(vals != 0, (close - vals) / vals * 100.0, np.nan)
        cols.append(vals)

    if not cols:
        return np.empty((n, 0), dtype=np.float64)
    return np.column_stack(cols)


# ── HMM causal ────────────────────────────────────────────────────────────

def hmm_observations(df: pd.DataFrame) -> np.ndarray:
    """Lo que ve el HMM: retorno de la vela, rango relativo y volumen relativo.

    Tres señales sin unidades y comparables entre tickers. Con esto es con lo
    que el modelo separa sus estados (lo que Jaume llama ruido / pump / dump);
    él no sabe cómo se llaman, solo encuentra tres grupos.
    """
    close = np.asarray(df["close"], dtype=np.float64)
    high = np.asarray(df["high"], dtype=np.float64)
    low = np.asarray(df["low"], dtype=np.float64)
    vol = np.asarray(df["volume"], dtype=np.float64)

    prev = np.roll(close, 1)
    prev[0] = close[0] if len(close) else np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = np.where(prev != 0, (close - prev) / prev * 100.0, 0.0)
        rango = np.where(close != 0, (high - low) / close * 100.0, 0.0)
        # Volumen relativo a la media ACUMULADA hasta la vela t, no a la del
        # dia entero. La primera version usaba np.nanmean(vol) — la media del
        # dia COMPLETO — y eso era un look-ahead de libro: la vela de las 07:00
        # quedaba escalada por el volumen que llegaria por la tarde, y en este
        # universo (gaps, pumps) el volumen total del dia es ORO. Un modelo con
        # esa señal daba resultados espectaculares e irreproducibles en vivo.
        # Detectado en la auditoria del 31-ago tras un backtest "demasiado
        # bueno" de Jaume; hay dos tests que impiden que vuelva.
        media_acum = np.cumsum(np.nan_to_num(vol, nan=0.0)) / np.arange(1, len(vol) + 1)
        vol_rel = np.where(media_acum > 0, vol / media_acum, 0.0)

    obs = np.column_stack([ret, rango, vol_rel])
    return np.nan_to_num(obs, nan=0.0, posinf=0.0, neginf=0.0)


def hmm_filtered_proba(model, X: np.ndarray) -> np.ndarray:
    """p(estado_t | observaciones 1..t) — FILTRADO, nunca suavizado.

    Es la recursión hacia delante escrita a mano a propósito. `predict` y
    `predict_proba` de hmmlearn miran la secuencia entera y meterían futuro en
    cada vela; ver la explicación de la cabecera del módulo.
    """
    from scipy.special import logsumexp

    T = len(X)
    if T == 0:
        return np.empty((0, int(getattr(model, "n_components", 0))))

    log_b = model._compute_log_likelihood(X)              # (T, K)
    log_start = np.log(np.asarray(model.startprob_) + 1e-300)
    log_trans = np.log(np.asarray(model.transmat_) + 1e-300)
    K = log_b.shape[1]

    out = np.empty((T, K), dtype=np.float64)
    log_alpha = log_start + log_b[0]
    out[0] = np.exp(log_alpha - logsumexp(log_alpha))
    for t in range(1, T):
        log_alpha = logsumexp(log_alpha[:, None] + log_trans, axis=0) + log_b[t]
        out[t] = np.exp(log_alpha - logsumexp(log_alpha))
    return out


def fit_hmm(observaciones: list[np.ndarray], n_states: int = 3, seed: int = 0):
    """Entrena el HMM sobre los días de ENTRENAMIENTO concatenados.

    `lengths` es importante: sin eso la librería creería que el último minuto de
    un día y el primero del siguiente son consecutivos, y aprendería
    transiciones que no existen.
    """
    from hmmlearn.hmm import GaussianHMM

    utiles = [o for o in observaciones if len(o) > 1]
    if not utiles:
        return None
    X = np.vstack(utiles)
    lengths = [len(o) for o in utiles]
    modelo = GaussianHMM(
        n_components=int(n_states), covariance_type="diag",
        n_iter=25, random_state=seed, tol=1e-3,
    )
    modelo.fit(X, lengths)
    return modelo


def describe_hmm_states(model) -> list[dict]:
    """Traduce los estados a algo legible. El HMM devuelve "0, 1, 2"; esto mira
    la media de cada estado y dice cuál sube, cuál baja y cuál es plano — que es
    lo que se quiere ver en pantalla."""
    if model is None:
        return []
    medias = np.asarray(model.means_)
    orden = np.argsort(medias[:, 0])            # por retorno medio
    etiquetas = {}
    if len(orden) == 3:
        etiquetas = {orden[0]: "caída", orden[1]: "ruido", orden[2]: "subida"}
    salida = []
    for i in range(len(medias)):
        salida.append({
            "estado": int(i),
            "etiqueta": etiquetas.get(i, f"estado {i}"),
            "retorno_medio_pct": round(float(medias[i][0]), 4),
            "rango_medio_pct": round(float(medias[i][1]), 4),
            "volumen_relativo": round(float(medias[i][2]), 3),
        })
    return salida


# ── El modelo entrenado ───────────────────────────────────────────────────

@dataclass
class TrainedModel:
    """Lo que sale del entrenamiento y se aplica luego al periodo de prueba."""
    booster: object
    feature_defs: list[dict]
    threshold: float
    hmm: object | None = None
    hmm_states: int = 0
    feature_names: list[str] = field(default_factory=list)
    importances: list[dict] = field(default_factory=list)
    n_train_rows: int = 0
    n_train_pos: int = 0
    # Cuántas señales ha visto y cuántas ha dejado pasar. Se lleva la cuenta
    # aquí porque es GRATIS: la alternativa era correr el periodo de prueba una
    # segunda vez sin modelo solo para poder restar, y eso es otro backtest
    # entero de espera. Es LA cifra que dice si el umbral está bien puesto.
    n_seen: int = 0
    n_kept: int = 0
    # True en modo «estrategia»: el modelo PONE las entradas en vez de
    # filtrarlas. El motor lo consulta para no saltarse los dias sin señales.
    generates: bool = False

    def score(self, df: pd.DataFrame, daily_stats: dict | None,
              cache: dict | None = None) -> np.ndarray:
        """Probabilidad, vela a vela, de que una entrada aquí acabe bien."""
        X = build_feature_matrix(df, daily_stats, self.feature_defs, cache)
        if self.hmm is not None:
            probas = hmm_filtered_proba(self.hmm, hmm_observations(df))
            X = np.column_stack([X, probas]) if X.size else probas
        if X.size == 0:
            return np.zeros(len(df))
        # XGBoost traga NaN de forma nativa: una feature que aún no existe (un
        # indicador que necesita 20 velas, la vela 3) NO es un cero, es "no sé".
        return self.booster.predict_proba(X)[:, 1]

    def mask(self, entries: np.ndarray, df: pd.DataFrame,
             daily_stats: dict | None, cache: dict | None = None,
             session_mask: np.ndarray | None = None) -> np.ndarray:
        """El veto: deja pasar solo las entradas que superan el listón.

        `entries` vive en el espacio RECORTADO a la sesión (el del simulador);
        `df` es el día COMPLETO (las features necesitan el premarket para tener
        contexto). `session_mask` traduce entre los dos: la puntuación se
        calcula sobre el día entero y se recorta a las velas de la sesión.
        """
        if not np.any(entries):
            return entries
        p = self.score(df, daily_stats, cache)
        if session_mask is not None and len(session_mask) == len(p):
            p = p[np.asarray(session_mask, dtype=bool)]
        if len(p) != len(entries):
            return entries
        filtradas = entries & (p >= self.threshold)
        self.n_seen += int(entries.sum())
        self.n_kept += int(filtradas.sum())
        return filtradas

    def generate(self, df: pd.DataFrame, daily_stats: dict | None,
                 cache: dict | None = None,
                 session_mask: np.ndarray | None = None) -> np.ndarray:
        """Modo «estrategia»: las entradas las pone el modelo, no las reglas.

        A diferencia de `mask`, aquí no hay nada que filtrar — se decide vela a
        vela. Las SALIDAS siguen viniendo de la gestión de riesgo (stop, take
        profit, hora): el modelo dice cuándo entrar, no cuándo salir. Devuelve
        el array en el espacio recortado a la sesión, que es el del simulador.
        """
        p = self.score(df, daily_stats, cache)
        if session_mask is not None and len(session_mask) == len(p):
            p = p[np.asarray(session_mask, dtype=bool)]
        entradas = p >= self.threshold
        # La última vela no puede abrir posición: el relleno va en la apertura
        # de la siguiente y no existe.
        if len(entradas):
            entradas[-1] = False
        self.n_seen += len(entradas)
        self.n_kept += int(entradas.sum())
        return entradas


def label_triple_barrier(
    df: pd.DataFrame, candidatos: np.ndarray, direccion: str,
    sl_stop: float | None, tp_stop: float | None, horizonte: int,
) -> np.ndarray:
    """¿Habría salido bien entrar en esta vela? 1 = sí, 0 = no, -1 = no se sabe.

    Simula desde cada vela candidata con **el stop y el take profit que ha
    puesto el usuario** —los mismos valores que `_parse_risk_management` le da
    al simulador, no una interpretación aparte— y mira qué pasa PRIMERO:

        toca el objetivo  → 1
        toca el stop      → 0
        se acaba el plazo → el signo de lo que llevara

    Por qué esto y no «¿subió un X% en N minutos?»: ese atajo **ignora el
    camino**. Una vela desde la que el precio primero cae un 20% (te salta el
    stop, estás fuera) y luego sube un 5% saldría etiquetada como BUENA. El
    modelo aprendería a buscar justo esas, y en real comerías stop tras stop
    mientras el backtest presume de aciertos.

    Si en la misma vela se tocan los dos, gana el STOP: es lo pesimista, y con
    velas de un minuto no se puede saber cuál llegó antes.
    """
    n = len(df)
    if n == 0 or candidatos.size == 0:
        return np.empty(0, dtype=np.int8)

    open_ = np.asarray(df["open"], dtype=np.float64)
    high = np.asarray(df["high"], dtype=np.float64)
    low = np.asarray(df["low"], dtype=np.float64)
    close = np.asarray(df["close"], dtype=np.float64)
    corto = str(direccion).lower() in ("short", "corto", "-1")

    etiquetas = np.full(candidatos.size, -1, dtype=np.int8)
    for k, i in enumerate(candidatos):
        # El relleno va en la apertura de la vela SIGUIENTE, igual que el motor.
        j = int(i) + 1
        if j >= n:
            continue
        entrada = open_[j]
        if not np.isfinite(entrada) or entrada <= 0:
            continue
        fin = min(n, j + horizonte) if horizonte > 0 else n
        if fin <= j:
            continue

        if corto:
            nivel_stop = entrada * (1 + sl_stop) if sl_stop else None
            nivel_tp = entrada * (1 - tp_stop) if tp_stop else None
            toca_stop = (high[j:fin] >= nivel_stop) if nivel_stop else None
            toca_tp = (low[j:fin] <= nivel_tp) if nivel_tp else None
        else:
            nivel_stop = entrada * (1 - sl_stop) if sl_stop else None
            nivel_tp = entrada * (1 + tp_stop) if tp_stop else None
            toca_stop = (low[j:fin] <= nivel_stop) if nivel_stop else None
            toca_tp = (high[j:fin] >= nivel_tp) if nivel_tp else None

        i_stop = int(np.argmax(toca_stop)) if toca_stop is not None and toca_stop.any() else None
        i_tp = int(np.argmax(toca_tp)) if toca_tp is not None and toca_tp.any() else None

        if i_stop is not None and (i_tp is None or i_stop <= i_tp):
            etiquetas[k] = 0          # empate -> gana el stop (pesimista)
        elif i_tp is not None:
            etiquetas[k] = 1
        else:
            salida = close[fin - 1]
            ganancia = (salida - entrada) if not corto else (entrada - salida)
            etiquetas[k] = 1 if ganancia > 0 else 0
    return etiquetas


@dataclass
class FeatureCollector:
    """Recoge el material de entrenamiento DURANTE la pasada de entrenamiento.

    Se engancha en el mismo sitio que el veto, así que el motor recorre los
    datos una sola vez. Guarda, por ticker-día:

      · las features en las velas CANDIDATAS (donde las reglas dijeron "entra"),
      · las observaciones del día enteras, que hacen falta después para el HMM
        (la recursión hacia delante necesita el día completo desde el principio,
        aunque solo se lean las filas candidatas).
    """
    feature_defs: list[dict]
    con_hmm: bool = False
    # Modo "standalone": no hay reglas de entrada, asi que las candidatas no las
    # marca la estrategia. Se muestrea el dia (una de cada `paso` velas) y cada
    # muestra se etiqueta con la triple barrera del stop/TP del usuario.
    standalone: bool = False
    muestras_por_dia: int = 120
    # (ticker, date) -> (idx_locales, X, idx_dia_completo). Dos sistemas de
    # coordenadas A PROPOSITO: los indices locales son los del frame recortado
    # a la sesion (el espacio de `entry_idx` de los trades del simulador); los
    # del dia completo apuntan a la misma vela dentro del df entero, que es
    # donde se calculan las features y las observaciones del HMM. La primera
    # version solo guardaba uno y con sesion RTH las etiquetas se emparejaban
    # con la vela equivocada.
    _filas: dict = field(default_factory=dict)
    _obs: dict = field(default_factory=dict)         # (ticker, date) -> obs
    _etiquetas: dict = field(default_factory=dict)   # (ticker, date) -> y

    @staticmethod
    def _a_dia_completo(idx_locales: np.ndarray,
                        session_mask: np.ndarray | None) -> np.ndarray:
        """Traduce índices del frame recortado al df del día completo."""
        if session_mask is None:
            return idx_locales
        return np.flatnonzero(np.asarray(session_mask, dtype=bool))[idx_locales]

    def collect(self, ticker: str, date: str, entries: np.ndarray,
                df: pd.DataFrame, daily_stats: dict | None,
                session_mask: np.ndarray | None = None,
                cache: dict | None = None) -> None:
        """`entries` en espacio recortado; `df` es el día COMPLETO."""
        candidatos = np.flatnonzero(entries)
        if candidatos.size == 0:
            return
        full_idx = self._a_dia_completo(candidatos, session_mask)
        X = build_feature_matrix(df, daily_stats, self.feature_defs, cache)
        self._filas[(ticker, date)] = (
            candidatos,
            X[full_idx] if X.size else np.empty((candidatos.size, 0)),
            full_idx,
        )
        if self.con_hmm:
            self._obs[(ticker, date)] = hmm_observations(df)

    def collect_standalone(self, ticker: str, date: str, df: pd.DataFrame,
                           daily_stats: dict | None, direccion: str,
                           sl_stop: float | None, tp_stop: float | None,
                           horizonte: int, cache: dict | None = None,
                           session_mask: np.ndarray | None = None,
                           df_trimmed: pd.DataFrame | None = None) -> None:
        """Material de entrenamiento cuando NO hay reglas de entrada.

        Se muestrea el día en vez de coger las ~700 velas: con miles de días,
        guardarlas todas son cientos de megas y no aporta nada — velas
        consecutivas se parecen tanto que la número 301 no enseña nada nuevo
        sobre la 300.

        Las BARRERAS se miden sobre el frame recortado (`df_trimmed`), que es
        el que simula de verdad: la salida EOD es el final de la sesión
        elegida, no las 20:00. Las features, sobre el día completo.
        """
        base = df_trimmed if df_trimmed is not None else df
        n = len(base)
        if n < 3:
            return
        paso = max(1, n // max(1, self.muestras_por_dia))
        candidatos = np.arange(0, n - 1, paso, dtype=np.int64)
        y = label_triple_barrier(base, candidatos, direccion, sl_stop, tp_stop, horizonte)
        util = y >= 0                      # -1 = no se pudo etiquetar
        if not util.any():
            return
        candidatos, y = candidatos[util], y[util]

        full_idx = self._a_dia_completo(candidatos, session_mask)
        X = build_feature_matrix(df, daily_stats, self.feature_defs, cache)
        self._filas[(ticker, date)] = (
            candidatos,
            X[full_idx] if X.size else np.empty((candidatos.size, 0)),
            full_idx,
        )
        self._etiquetas[(ticker, date)] = y
        if self.con_hmm:
            self._obs[(ticker, date)] = hmm_observations(df)

    # ── Después de la pasada ──────────────────────────────────────────────

    def observaciones(self) -> list[np.ndarray]:
        return list(self._obs.values())

    def dataset(self, trades: list[dict], hmm=None) -> tuple[np.ndarray, np.ndarray, int]:
        """Matriz de entrenamiento y etiquetas, alineadas por (ticker, día, vela).

        Regla de etiquetado, y es importante: una candidata se etiqueta con el
        trade que ABRIÓ justo después de ella. Las candidatas que NO llegaron a
        operarse (porque ya había posición abierta, o se acabaron las
        reentradas) **se descartan**, no se marcan como perdedoras: "no se
        ejecutó" no es "salió mal", y meterlas envenenaría el aprendizaje.
        """
        probas_std: dict = {}
        if self.standalone:
            # Las etiquetas ya se calcularon al recoger (triple barrera): aquí
            # solo hay que pegar las columnas del HMM si las hay.
            if hmm is not None:
                for clave, obs in self._obs.items():
                    probas_std[clave] = hmm_filtered_proba(hmm, obs)
            filas, etiquetas = [], []
            for clave, (candidatos, X, full_idx) in self._filas.items():
                y = self._etiquetas.get(clave)
                if y is None or len(y) != len(candidatos):
                    continue
                p = probas_std.get(clave)
                if p is not None:
                    # Las probas del HMM van indexadas por el DIA COMPLETO,
                    # que es donde se calcularon las observaciones.
                    dentro = full_idx < len(p)
                    X, y, full_idx = X[dentro], y[dentro], full_idx[dentro]
                    X = np.column_stack([X, p[full_idx]]) if X.size else p[full_idx]
                if len(X):
                    filas.append(X)
                    etiquetas.append(y)
            if not filas:
                return np.empty((0, 0)), np.empty(0), 0
            return np.vstack(filas), np.concatenate(etiquetas).astype(np.int32), 0

        # Trades por día, ordenados por la vela en que abrieron.
        por_dia: dict = {}
        for t in trades:
            clave = (t.get("ticker"), t.get("date"))
            por_dia.setdefault(clave, []).append(
                (int(t.get("entry_idx", -1)), float(t.get("pnl", 0.0))))
        for v in por_dia.values():
            v.sort()

        probas_cache: dict = {}
        if hmm is not None:
            for clave, obs in self._obs.items():
                probas_cache[clave] = hmm_filtered_proba(hmm, obs)

        filas, etiquetas = [], []
        descartadas = 0
        for clave, (candidatos, X, full_idx) in self._filas.items():
            operados = por_dia.get(clave, [])
            probas = probas_cache.get(clave)
            for j, idx in enumerate(candidatos):
                # El trade que abrió en esta vela o en la siguiente (el relleno
                # va en la apertura de la vela siguiente por anti-look-ahead).
                # `idx` y `entry_idx` viven AMBOS en el espacio recortado a la
                # sesión — es la condición que la primera versión rompía.
                pnl = None
                for entry_idx, p in operados:
                    if entry_idx in (idx, idx + 1):
                        pnl = p
                        break
                if pnl is None:
                    descartadas += 1
                    continue
                fila = X[j]
                if probas is not None and full_idx[j] < len(probas):
                    fila = np.concatenate([fila, probas[full_idx[j]]])
                filas.append(fila)
                etiquetas.append(1 if pnl > 0 else 0)

        if not filas:
            return np.empty((0, 0)), np.empty(0), descartadas
        return np.vstack(filas), np.asarray(etiquetas, dtype=np.int32), descartadas


def build_feature_names(feature_defs: list[dict], hmm_states: int) -> list[str]:
    nombres = [feature_label(c) for c in feature_defs]
    nombres += [f"HMM p(estado {i})" for i in range(hmm_states)]
    return nombres


def train_booster(X: np.ndarray, y: np.ndarray, seed: int = 0):
    """XGBoost pequeño y muy regularizado, a propósito.

    Aquí las muestras son pocas (los trades de una estrategia en unos años) y el
    ruido es enorme. Un modelo grande memoriza el periodo de entrenamiento y no
    sirve para nada fuera. Profundidad 4 y 300 árboles con submuestreo es un
    punto de partida conservador.
    """
    from xgboost import XGBClassifier

    pos = int(y.sum())
    neg = int(len(y) - pos)
    modelo = XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        min_child_weight=5, reg_lambda=2.0,
        # Clases desbalanceadas: si solo el 30% de los trades ganan, sin esto el
        # modelo aprende a decir "no" a todo y acierta el 70%.
        scale_pos_weight=(neg / pos) if pos > 0 else 1.0,
        n_jobs=-1, eval_metric="logloss", tree_method="hist",
        random_state=seed,
    )
    modelo.fit(X, y)
    return modelo


def importances_of(booster, feature_names: list[str]) -> list[dict]:
    """Qué features está usando de verdad. Es lo primero que hay que mirar
    cuando un modelo parece funcionar: si el peso se lo lleva algo absurdo, el
    resultado es casualidad."""
    try:
        pesos = np.asarray(booster.feature_importances_, dtype=np.float64)
    except Exception:
        return []
    total = float(pesos.sum()) or 1.0
    filas = [
        {"feature": feature_names[i] if i < len(feature_names) else f"f{i}",
         "peso_pct": round(float(pesos[i]) / total * 100.0, 2)}
        for i in range(len(pesos))
    ]
    return sorted(filas, key=lambda r: -r["peso_pct"])
