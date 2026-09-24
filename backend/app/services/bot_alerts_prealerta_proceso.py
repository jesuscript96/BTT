"""Las PREALERTAS en su propio proceso (23-sep-2026).

QUE HACE. Es el unico que ve los prints (`T.`) y los agregados por segundo
(`A.`). Con ellos monta la vela a medias y, del segundo 44 al 59, mira si ya
cumple la estrategia para avisar antes del cierre. El radar y las alertas no
necesitan prints: les basta la vela de minuto de Massive.

POR QUE ESTA AQUI. Era el cuello de verdad, medido el 23-sep-2026. Evaluar la
vela a medias con CADA print, en el mismo hilo que lee el socket, con 300
prints por segundo en premercado, dejaba al bot al 97 % de su unico nucleo (la
maquina entera al 3 %: 19 nucleos parados). La alerta pasaba de 1,2 s a 15 s de
mediana y el p90 a 30 s; con 30 s Massive dejo de recibir respuesta a su ping y
nos corto la conexion — y cada corte nuestro puede echar a un socio de la
cuenta al reconectar.

DOS COSAS ARREGLAN ESO, Y LAS DOS ESTAN AQUI:

  1. Una evaluacion POR SEGUNDO Y TICKER, no una por print. El print se aplica
     igual —la vela a medias es identica—, solo se deja de repetir el calculo.
     Con 12 tickers pasa de ~3.600 evaluaciones por minuto a ~190. Probado en
     vivo el 23-sep a las 15:40: con 380 prints/s (mas que el peor momento de
     la manyana) el bot bajo del 97 % al 7,7 % y la alerta volvio a 2,03 s.
  2. Su propio nucleo, para que ni siquiera esos ~190 le quiten tiempo a la
     lectura del socket.

SU PROPIA COPIA DEL MOTOR. `evaluar_parcial` mide la vela a medias contra el
dia acumulado del ticker (VWAP, maximos, posicion abierta), asi que este
proceso necesita las velas de minuto igual que el de alertas. El bot se las
manda a los dos.

Y POR ESO RESUELVE SUS PREALERTAS EL SOLO. Al cerrar un minuto hay que decir si
cada prealerta viva quedo confirmada o no. Como este proceso aplica la misma
vela con el mismo motor, obtiene los MISMOS eventos que el de alertas y los usa
para decidir — sin preguntarle a nadie. Lo que NO hace es publicarlos: de eso
se encarga el proceso de alertas, para que un aviso no pueda salir dos veces.
"""
from __future__ import annotations

import logging
import sys
import threading
from typing import Optional

from app.services.bot_alerts_proceso_base import AVISO, ProcesoHijo, bucle_hijo

logger = logging.getLogger(__name__)

# ── Mensajes ───────────────────────────────────────────────────────────────
ESTRATEGIAS = "estrategias"
HIDRATAR = "hidratar"
DATOS = "datos"                 # lote de prints (`T.`) y agregados (`A.`)
VELA = "vela"                   # vela de minuto cerrada: sincroniza el motor
VELAS = "velas"                 # varias de golpe (recuperacion tras un corte)
SOLTAR = "soltar"
DIA_NUEVO = "dia_nuevo"
TICKERS = "tickers"             # los que se vigilan ahora mismo

PREALERTA = "prealerta"         # hijo -> bot: hay aviso adelantado
RESUELTAS = "resueltas"         # hijo -> bot: que paso con las de un minuto
METRICAS = "metricas"           # hijo -> bot: para el log de cada 5 min


def clave_prealerta(e) -> tuple:
    """Lo que hace que dos prealertas sean LA MISMA: ticker, ESTRATEGIA, tipo,
    minuto y cuenta. La usan este proceso Y el bot, para que no puedan
    desincronizarse.

    LA ESTRATEGIA VA DENTRO (24-sep-2026, Jaume: «tienen que haber prealertas,
    alertas y demas por cada estrategia»). Antes no iba: con dos estrategias
    sobre el mismo ticker la segunda tenia la misma matricula que la primera y
    se tiraba como repetida. Medido ese dia: 10 prealertas, las 10 de una sola
    estrategia, aunque las alertas de cierre salieron para las dos.

    LA CUENTA TAMBIEN, pero no separa mensajes: una estrategia con varias
    cuentas emite un evento por cuenta (otras acciones), y Telegram los junta en
    UN mensaje por estrategia (`bot_alerts_telegram.clave_grupo`). Asi que sale
    una prealerta por estrategia, con un bloque por cuenta dentro.
    """
    return (e.ticker, e.strategy_id, e.tipo, str(e.momento)[:16],
            getattr(e, "cuenta", None))


# Posicion del minuto dentro de `clave_prealerta`, para cerrar las de un minuto.
_MINUTO = 3


def filtrar_nuevas(eventos, vivas: set) -> list:
    """De lo que devuelve el motor en un segundo, solo lo que aun no se ha
    avisado; y lo apunta en `vivas`.

    Es lo que sustituye a cerrar el minuto con el primer aviso. Antes, en cuanto
    UNA estrategia prealertaba, la vela a medias se marcaba como evaluada y ya
    no se miraba mas ese minuto: si la otra estrategia se cumplia unos segundos
    despues, no se enteraba nadie. Ahora se sigue mirando cada segundo hasta el
    59 (como mucho 16 evaluaciones por minuto y ticker, lo mismo que cuesta un
    minuto sin avisos) y lo ya avisado se filtra aqui, por estrategia. El
    motivo por el que existia el cierre —que la misma prealerta no saliera
    en el 52, 53, 54... hasta el 59: ocho mensajes iguales— lo cubre este
    filtro igual que antes.
    """
    nuevas = []
    for e in eventos:
        k = clave_prealerta(e)
        if k in vivas:
            continue
        vivas.add(k)
        nuevas.append(e)
    return nuevas


def _hijo(tuberia, cada_seg: float = 300.0) -> None:
    sys.path.insert(0, r"D:\Backtester\backend")
    import time as _time

    import pandas as pd
    from app.services.bot_alerts_prealertas import ConstructorParcial
    from app.services.bot_alerts_runner import RunnerAlertas

    # ESTE PROCESO NO ESCRIBE EN EL CUADERNO DEL BOT. Su motor es una COPIA EN
    # SOMBRA del de alertas: aplica las mismas velas y por tanto escribiria las
    # mismas lineas, y los dos hijos comparten el fichero de log. Visto en vivo
    # el 23-sep nada mas arrancar: «[BOT] EDVA hidratado» salia dos veces. Lo
    # que este proceso tenga que decir sale por `AVISO`, que lo escribe el bot.
    #
    # EL NOMBRE IMPORTA. El 23-sep se silencio `bot` y no sirvio de nada: las
    # lineas repetidas («[BOT] X hidratado», «[BOT] [ENTRADA] ...») no salen del
    # logger del bot sino del motor y su runner, `btt.bot_alerts` y
    # `btt.bot_alerts.runner`. Silenciando el padre, `btt.bot_alerts`, callan los
    # dos. Solo INFO: los WARNING (un fallo de verdad) siguen saliendo.
    logging.getLogger("btt.bot_alerts").setLevel(logging.WARNING)
    logging.getLogger("bot").setLevel(logging.WARNING)

    runner = RunnerAlertas([])
    constructor = ConstructorParcial()
    vigilados: set = set()
    # Prealertas ya dadas que esperan a que cierre su minuto.
    vivas: set = set()
    # Ultimo segundo evaluado por ticker: el recorte del punto 1.
    ultimo_seg: dict = {}
    # Contadores para el resumen de cada 5 min del bot.
    m = {"prints": 0, "evaluaciones": 0, "coste": 0.0, "peor": 0.0}

    def _prealertar(listo, latencia: float, via: str) -> None:
        tk, parcial, ts_minuto, segundo = listo
        if tk not in vigilados:
            return
        # UNA EVALUACION POR SEGUNDO Y TICKER. El print ya esta aplicado: no se
        # pierde dato, solo se deja de repetir el calculo.
        if ultimo_seg.get(tk) == (ts_minuto, segundo):
            return
        ultimo_seg[tk] = (ts_minuto, segundo)

        ts = pd.Timestamp(ts_minuto).tz_localize(None)
        t0 = _time.perf_counter()
        eventos = runner.evaluar_parcial(tk, parcial.como_vela(ts))
        coste = _time.perf_counter() - t0
        m["evaluaciones"] += 1
        m["coste"] += coste
        m["peor"] = max(m["peor"], coste)
        if not eventos:
            # Aun no cumple. NO se marca el minuto: se sigue mirando hasta el
            # 59. Medido en su dia: de 86 % a 100 % de captura, y el margen
            # solo baja de 10 a 9,4 s.
            return
        # NO se cierra el minuto con el primer aviso (`parcial.evaluada`): otra
        # estrategia puede cumplirse unos segundos despues. Lo ya avisado se
        # filtra por estrategia en `filtrar_nuevas`.
        nuevas = filtrar_nuevas(eventos, vivas)
        if not nuevas:
            return
        minuto = str(ts)[:16]
        tuberia.send({"t": PREALERTA, "eventos": nuevas, "via": via,
                      "segundo": segundo, "latencia": latencia,
                      "margen": 60 - segundo - latencia, "minuto": minuto})

    def manejador(msg: dict) -> None:
        t = msg.get("t")

        if t == DATOS:
            # EN LOTE, SIEMPRE. Un mensaje por print desbordaba la cola: con
            # 300 prints/s y la cola acotada, medido el 23-sep, de 800 prints
            # solo llegaban 21 y la vela a medias salia falsa. La trampa numero
            # uno del modulo base, en la que se cae sola.
            for clase, ev in msg["lote"]:
                if clase == "T":
                    m["prints"] += 1
                    listo = constructor.aplicar_operacion(ev)
                    if listo is None:
                        continue
                    t_ms = ev.get("t")
                    lat = max(0.0, _time.time() - int(t_ms) / 1000.0) if t_ms else 0.0
                    _prealertar(listo, lat, "operación")
                else:
                    listo = constructor.aplicar(ev)
                    if listo is None:
                        continue
                    lat = max(0.0, _time.time() - (int(ev.get("s") or 0) / 1000.0))
                    _prealertar(listo, lat, "agregado")

        elif t == VELAS:
            for v in msg["velas"]:
                manejador({"t": VELA, "ticker": msg["ticker"], "vela": v})

        elif t == VELA:
            # El minuto YA ESTA CERRADO. Se aplica al motor para seguir en
            # sincronia con el proceso de alertas y se resuelven las prealertas
            # vivas de ese minuto. Los eventos NO se publican desde aqui: los
            # publica el proceso de alertas, que calcula exactamente lo mismo.
            tk, vela = msg["ticker"], msg["vela"]
            eventos = runner.nueva_vela(tk, vela) or []
            constructor.marcar_cerrada(tk, vela.get("timestamp"))
            ultimo_seg.pop(tk, None)
            minuto = str(vela.get("timestamp"))[:16]
            confirmados = {clave_prealerta(e) for e in eventos}
            descartadas = []
            for clave in list(vivas):
                if clave[0] != tk or clave[_MINUTO] != minuto:
                    continue
                vivas.discard(clave)
                if clave not in confirmados:
                    descartadas.append(list(clave))
            if descartadas:
                tuberia.send({"t": RESUELTAS, "ticker": tk, "minuto": minuto,
                              "descartadas": descartadas})

        elif t == HIDRATAR:
            df = pd.DataFrame(msg["velas"])
            # Se ignoran los avisos que devuelva: el proceso de alertas ya los
            # da. Aqui solo interesa que el motor tenga el dia.
            runner.hidratar(msg["ticker"], df, msg.get("stats"))
            vigilados.add(msg["ticker"])

        elif t == ESTRATEGIAS:
            runner.actualizar(msg["datos"])

        elif t == TICKERS:
            vigilados.clear()
            vigilados.update(msg["datos"])

        elif t == SOLTAR:
            tk = msg["ticker"]
            vigilados.discard(tk)
            ultimo_seg.pop(tk, None)
            constructor.olvidar(tk)
            runner.soltar(tk)

        elif t == DIA_NUEVO:
            runner.reiniciar()
            constructor.reiniciar()
            vivas.clear()
            ultimo_seg.clear()
            tuberia.send({"t": AVISO, "texto": "dia nuevo: prealertas a cero"})

    def resumen() -> None:
        """Cada 5 min: lo que costo el trabajo, para verlo en el log del bot."""
        if not m["evaluaciones"] and not m["prints"]:
            return
        tuberia.send({"t": METRICAS, "prints": m["prints"],
                      "evaluaciones": m["evaluaciones"],
                      "coste": m["coste"], "peor": m["peor"],
                      "tardias": getattr(constructor, "tardias", 0)})
        m.update({"prints": 0, "evaluaciones": 0, "coste": 0.0, "peor": 0.0})

    bucle_hijo(tuberia, manejador, periodica=resumen, cada_seg=cada_seg,
               nombre="prealerta")


class PrealertaEnProceso(ProcesoHijo):
    """Las prealertas, vistas desde el bot.

    `al_prealerta(eventos, via, segundo, latencia, margen, minuto)` se llama
    cuando hay aviso adelantado; `al_resueltas(ticker, minuto, descartadas)`
    cuando un minuto cierra y alguna no se confirmo. Las dos corren en el hilo
    lector del padre: encolar y volver.
    """

    # Cada cuanto se vacia el lote de prints hacia el hijo. 50 ms mantiene el
    # adelanto de la prealerta (el margen medido es de 6 a 12 s) y evita el
    # mensaje por print, que desbordaba la cola.
    CADA_LOTE_S = 0.05
    LOTE_MAX = 30000

    def __init__(self, al_prealerta=None, al_resueltas=None, al_metricas=None,
                 cada_seg: float = 300.0):
        super().__init__(_hijo, "prealerta", al_recibir=self._recibir,
                         argumentos=(cada_seg,))
        self.al_prealerta = al_prealerta
        self.al_resueltas = al_resueltas
        self.al_metricas = al_metricas
        self._estrategias: list = []
        self._pasado: dict = {}
        self._vigilados: set = set()
        self._lote: list = []
        self._cerrojo = threading.Lock()
        self.al_resucitar = self._devolver_estado

    def arrancar(self) -> None:
        super().arrancar()
        threading.Thread(target=self._vaciar_lote, name="prealerta-lote",
                         daemon=True).start()

    def _vaciar_lote(self) -> None:
        while not self._parar.is_set():
            self._parar.wait(self.CADA_LOTE_S)
            with self._cerrojo:
                if not self._lote:
                    continue
                lote, self._lote = self._lote, []
            self.enviar({"t": DATOS, "lote": lote})

    # ── lo que el bot le manda ────────────────────────────────────────────
    def configurar(self, estrategias: list) -> None:
        self._estrategias = list(estrategias)
        self.enviar({"t": ESTRATEGIAS, "datos": self._estrategias})

    def hidratar(self, ticker: str, velas: list, stats: Optional[dict] = None) -> None:
        self._pasado[ticker] = (velas, stats)
        self._vigilados.add(ticker)
        self.enviar({"t": HIDRATAR, "ticker": ticker, "velas": velas, "stats": stats})

    def operacion(self, ev: dict) -> None:
        """Un print. NO sale al instante: se acumula y va en lote (ver
        `_vaciar_lote`). Llamarla cuesta un `append`, que es lo que hace falta
        cuando llegan 300 por segundo por el mismo hilo que lee el socket."""
        self._apuntar("T", ev)

    def tick(self, ev: dict) -> None:
        self._apuntar("A", ev)

    def _apuntar(self, clase: str, ev: dict) -> None:
        with self._cerrojo:
            self._lote.append((clase, ev))
            # Tope de seguridad: si el hilo que vacia muriera, esta lista
            # creceria sin fin y se llevaria la memoria del bot por delante. A
            # 300 prints/s, 30.000 son 100 segundos de datos.
            if len(self._lote) > self.LOTE_MAX:
                sobran = len(self._lote) - self.LOTE_MAX
                del self._lote[:sobran]
                self.lotes_tirados += sobran

    def vela(self, ticker: str, vela: dict) -> None:
        self.enviar({"t": VELA, "ticker": ticker, "vela": vela})

    def vela_lote(self, ticker: str, velas: list) -> None:
        """Varias velas de golpe (la recuperacion por REST tras un corte). En
        un solo mensaje: mandarlas una a una llenaria la cola acotada y se
        perderian, que es la trampa numero uno del modulo base."""
        self.enviar({"t": VELAS, "ticker": ticker, "velas": velas})

    def tickers(self, tickers) -> None:
        self._vigilados = set(tickers)
        self.enviar({"t": TICKERS, "datos": sorted(self._vigilados)})

    def soltar(self, ticker: str) -> None:
        self._pasado.pop(ticker, None)
        self._vigilados.discard(ticker)
        self.enviar({"t": SOLTAR, "ticker": ticker})

    def limpiar_dia(self) -> None:
        self._pasado.clear()
        self._vigilados.clear()
        self.enviar({"t": DIA_NUEVO})

    # ── tripas ────────────────────────────────────────────────────────────
    def _recibir(self, msg: dict) -> None:
        t = msg.get("t")
        if t == PREALERTA and self.al_prealerta is not None:
            self.al_prealerta(msg.get("eventos") or [], msg.get("via"),
                              msg.get("segundo"), msg.get("latencia"),
                              msg.get("margen"), msg.get("minuto"))
        elif t == RESUELTAS and self.al_resueltas is not None:
            self.al_resueltas(msg["ticker"], msg["minuto"], msg.get("descartadas") or [])
        elif t == METRICAS and self.al_metricas is not None:
            self.al_metricas(msg)

    def _devolver_estado(self, _hijo) -> None:
        if self._estrategias:
            self.enviar({"t": ESTRATEGIAS, "datos": self._estrategias})
        for ticker, (velas, stats) in list(self._pasado.items()):
            self.enviar({"t": HIDRATAR, "ticker": ticker, "velas": velas, "stats": stats})
        if self._vigilados:
            self.enviar({"t": TICKERS, "datos": sorted(self._vigilados)})
