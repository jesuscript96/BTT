"""EL CALENDARIO DEL MERCADO: que dias hay sesion y hasta que hora.

El bot esta pensado para no apagarse nunca, asi que no le vale con «son las
10:30». Tiene que saber si HOY hay mercado y hasta cuando. Sin esto, un jueves
de Accion de Gracias el bot dice «RTH» y se queda esperando velas que no van a
llegar, y no hay forma de distinguir ese silencio de una averia.

DOS FUENTES, A PROPOSITO.

1. LAS REGLAS (`_por_reglas`). Los festivos de NYSE son deterministas: tercer
   lunes de enero, ultimo lunes de mayo, Viernes Santo... Se calculan aqui, sin
   red y para cualquier anyo. Es la fuente por defecto **porque no se cae**: si
   Massive no responde, o el bot arranca sin internet, el calendario sigue
   siendo correcto.

2. MASSIVE (`_de_massive`). `/v1/marketstatus/upcoming` da la lista oficial e
   incluye las MEDIAS SESIONES con su hora exacta. Se pide una vez al dia y
   **solo puede anyadir o corregir**, nunca borra lo que dicen las reglas. Sirve
   para lo que las reglas no pueden saber: un cierre por meteorologia, un dia
   de luto nacional. El huracan Sandy tuvo el mercado cerrado dos dias en 2012
   y ninguna regla lo predice.

POR QUE NO UNA LIBRERIA. `pandas_market_calendars` lo haria, pero el bot
arranca con el **Python global** (`arrancar_bot.bat`), no con el venv. Cada
dependencia nueva ahi es una que puede faltar o venir en otra version — que es
exactamente como se rompio la paginacion del universo el 4-sep-2026. Esto no
importa nada fuera de la biblioteca estandar.

TODO SE CUENTA EN HORA DE NUEVA YORK. `ZoneInfo("America/New_York")` ya resuelve
el horario de verano solo, y esa es la unica forma de que no importe el desfase
con Espanya. Medido: el mercado abre SIEMPRE a las 09:30 de Nueva York, pero eso
son las 15:30 en Espanya casi todo el anyo y las 14:30 durante unas tres
semanas, porque los cambios de hora no caen el mismo dia a los dos lados:

    EEUU     2do domingo de marzo    ->  1er domingo de noviembre
    Espanya  ultimo domingo de marzo ->  ultimo domingo de octubre

En 2026 eso deja dos ventanas descolocadas: del 9 al 28 de marzo y del 26 de
octubre al 1 de noviembre. Trabajando en hora de Nueva York el bot ni se entera;
el que tiene que mirar el reloj es quien opera desde aqui.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("btt.bot_alerts.calendario")

ET = "America/New_York"
REST = os.getenv("MASSIVE_API_BASE_URL", "https://api.massive.com")

# Las franjas del dia de mercado, en minutos desde medianoche de Nueva York.
# El cierre de RTH no es fijo: en media sesion son las 13:00. Por eso el limite
# se resuelve en cada llamada y no es una constante suelta.
PREMERCADO_INI = 4 * 60           # 04:00
RTH_INI = 9 * 60 + 30             # 09:30
RTH_FIN = 16 * 60                 # 16:00  (13:00 en media sesion)
POST_FIN = 20 * 60                # 20:00  (17:00 en media sesion)
MEDIA_SESION_FIN = 13 * 60        # 13:00
MEDIA_SESION_POST_FIN = 17 * 60   # 17:00


# -- las reglas -----------------------------------------------------------
def _pascua(anyo: int) -> date:
    """Domingo de Pascua (algoritmo gregoriano anonimo). Hace falta para el
    Viernes Santo, el unico festivo de NYSE que se mueve con la luna."""
    a = anyo % 19
    b, c = divmod(anyo, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    mes, dia = divmod(h + ll - 7 * m + 114, 31)
    return date(anyo, mes, dia + 1)


def _enesimo(anyo: int, mes: int, dia_semana: int, n: int) -> date:
    """El n-esimo <dia_semana> del mes (lunes=0). n=-1 es el ultimo."""
    if n > 0:
        d = date(anyo, mes, 1)
        d += timedelta(days=(dia_semana - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    ultimo = date(anyo, mes, 28)
    while (ultimo + timedelta(days=1)).month == mes:
        ultimo += timedelta(days=1)
    return ultimo - timedelta(days=(ultimo.weekday() - dia_semana) % 7)


def _observado(d: date) -> Optional[date]:
    """Cuando un festivo de fecha fija cae en fin de semana, NYSE lo pasa al
    viernes anterior o al lunes siguiente.

    CON UNA EXCEPCION QUE CUESTA CARA: la regla dice «al viernes anterior SALVO
    que ese viernes sea el ultimo dia de negociacion del anyo». O sea que
    cuando Anyo Nuevo cae en sabado, el 31 de diciembre **se negocia**.
    Comprobado con datos reales: el 31-dic-2021 (viernes, con el 1-ene-2022 en
    sabado) trae 11.151 cierres, y el 31-dic-2010 otros 7.401.

    No es un detalle: ese 31 es precisamente la ultima sesion del anyo, o sea
    el cierre contra el que se miden los gaps del primer dia de enero. Darlo
    por festivo mandaria al bot a buscar el cierre del 30 y todos los gaps de
    esa manyana saldrian mal, sin un solo error.

    Devuelve None cuando el festivo no llega a observarse.
    """
    if d.weekday() == 5:            # sabado -> viernes
        if d.month == 1 and d.day == 1:
            return None
        return d - timedelta(days=1)
    if d.weekday() == 6:            # domingo -> lunes
        return d + timedelta(days=1)
    return d


def _por_reglas(anyo: int) -> dict[date, tuple[str, str]]:
    """Festivos y medias sesiones de NYSE de un anyo.
    {fecha: (estado, nombre)} con estado 'cerrado' o 'media'."""
    cal: dict[date, tuple[str, str]] = {}

    fijos = [
        (date(anyo, 1, 1), "Anyo Nuevo"),
        (date(anyo, 6, 19), "Juneteenth"),
        (date(anyo, 7, 4), "4 de Julio"),
        (date(anyo, 12, 25), "Navidad"),
    ]
    for d, nombre in fijos:
        # Juneteenth solo es festivo de NYSE desde 2022. Ponerlo antes marcaria
        # como cerrados dias que tuvieron sesion, y eso descuadraria cualquier
        # cotejo con el lago.
        if nombre == "Juneteenth" and anyo < 2022:
            continue
        obs = _observado(d)
        if obs is not None:
            cal[obs] = ("cerrado", nombre)

    moviles = [
        (_enesimo(anyo, 1, 0, 3), "Martin Luther King"),
        (_enesimo(anyo, 2, 0, 3), "Washington"),
        (_pascua(anyo) - timedelta(days=2), "Viernes Santo"),
        (_enesimo(anyo, 5, 0, -1), "Memorial Day"),
        (_enesimo(anyo, 9, 0, 1), "Labor Day"),
        (_enesimo(anyo, 11, 3, 4), "Accion de Gracias"),
    ]
    for d, nombre in moviles:
        cal[d] = ("cerrado", nombre)

    # MEDIAS SESIONES (cierre a las 13:00 en vez de a las 16:00).
    medias = [
        (_enesimo(anyo, 11, 3, 4) + timedelta(days=1), "viernes de Accion de Gracias"),
        (date(anyo, 12, 24), "Nochebuena"),
        (date(anyo, 7, 3), "vispera del 4 de Julio"),
    ]
    for d, nombre in medias:
        # Si el dia cae en fin de semana no hay nada que acortar, y si ya es
        # festivo entero manda el festivo: cuando Navidad cae en sabado, el 24
        # es el festivo trasladado, no una media sesion.
        if d.weekday() >= 5 or d in cal:
            continue
        # La vispera del 4 de Julio solo se acorta si el 4 es laborable. Si cae
        # en fin de semana el festivo se traslada y el 3 es un dia normal.
        if d.month == 7 and date(anyo, 7, 4).weekday() >= 5:
            continue
        cal[d] = ("media", nombre)

    return cal


# -- la lista oficial de Massive ------------------------------------------
_cache: dict[int, dict[date, tuple[str, str]]] = {}
_pedido_el: Optional[date] = None
_extra: dict[date, tuple[str, str]] = {}


def _de_massive() -> dict[date, tuple[str, str]]:
    """Lo que Massive sepa de los proximos festivos. NUNCA revienta: si falla,
    se sigue con las reglas, que cubren todo lo previsible. Un calendario que
    tumba el bot por un timeout seria peor que no tenerlo."""
    try:
        import httpx
        from app.services.bot_alerts_feed import clave_bot, _ssl_ctx
        key = clave_bot()
        if not key:
            return {}
        r = httpx.get(f"{REST}/v1/marketstatus/upcoming",
                      params={"apiKey": key}, timeout=20.0, verify=_ssl_ctx())
        r.raise_for_status()
        fuera: dict[date, tuple[str, str]] = {}
        for fila in r.json() or []:
            if str(fila.get("exchange", "")).upper() != "NYSE":
                continue
            try:
                d = datetime.strptime(str(fila.get("date")), "%Y-%m-%d").date()
            except Exception:  # noqa: BLE001
                continue
            estado = "media" if fila.get("status") == "early-close" else "cerrado"
            fuera[d] = (estado, str(fila.get("name") or "festivo"))
        return fuera
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CALENDARIO] no se pudo leer el calendario oficial "
                       "(se sigue con las reglas): %s", exc)
        return {}


def _refrescar_al_fondo() -> None:
    """Pide la lista oficial EN OTRO HILO y la incorpora cuando llegue.

    NO PUEDE BLOQUEAR. `franja_de_mercado()` se llama en cada latido del bot,
    y ese latido se compone dentro del bucle de eventos: una peticion HTTP ahi
    congelaria el proceso entero —feed incluido— hasta 20 segundos, una vez al
    dia. Nadie lo relacionaria con el calendario.

    Mientras el hilo no vuelve se responde con las reglas, que es justo para lo
    que estan. Si falla, se conserva lo que hubiera.
    """
    def tarea() -> None:
        nuevos = _de_massive()
        if nuevos:
            _extra.update(nuevos)
            _cache.clear()          # que se recalculen ya con lo nuevo
    threading.Thread(target=tarea, name="calendario-mercado", daemon=True).start()


def _calendario(anyo: int) -> dict[date, tuple[str, str]]:
    """El calendario del anyo: reglas + lo que anyada Massive (una vez al dia).

    El bot puede estar semanas encendido, asi que la lista oficial se refresca
    al cambiar el dia. Si la peticion falla se conserva la anterior.
    """
    global _pedido_el
    hoy = datetime.now(tz=ZoneInfo(ET)).date()
    if _pedido_el != hoy:
        _pedido_el = hoy
        _refrescar_al_fondo()
    if anyo not in _cache:
        cal = _por_reglas(anyo)
        # Massive MANDA sobre las reglas: es la fuente oficial y la unica que
        # puede saber de un cierre imprevisto.
        cal.update({d: v for d, v in _extra.items() if d.year == anyo})
        _cache[anyo] = cal
    return _cache[anyo]


# -- lo que usa el resto del programa -------------------------------------
def festivo(dia: date) -> Optional[str]:
    """Nombre del festivo si ese dia NO hay sesion; None si la hay.
    El fin de semana NO cuenta como festivo: son cosas distintas y conviene
    poder distinguirlas en el log."""
    e = _calendario(dia.year).get(dia)
    return e[1] if e and e[0] == "cerrado" else None


def media_sesion(dia: date) -> Optional[str]:
    """Motivo si ese dia el mercado cierra a las 13:00 en vez de a las 16:00."""
    e = _calendario(dia.year).get(dia)
    return e[1] if e and e[0] == "media" else None


def hay_sesion(dia: date) -> bool:
    """True si ese dia hubo (o habra) mercado, entero o a medias."""
    return dia.weekday() < 5 and festivo(dia) is None


def ultima_sesion(desde: date, incluir_hoy: bool = False) -> date:
    """El ultimo dia de mercado anterior a `desde`. Es lo que hace falta para
    saber contra que cierre se mide el gap de hoy."""
    d = desde if incluir_hoy else desde - timedelta(days=1)
    for _ in range(30):             # 30 dias cubre cualquier puente imaginable
        if hay_sesion(d):
            return d
        d -= timedelta(days=1)
    return d


def franja_de_mercado(ahora: Optional[datetime] = None) -> str:
    """En que parte del dia de mercado estamos, en hora de Nueva York.

    Devuelve una de: premercado / RTH / postmercado / cerrado / fin de semana /
    'festivo: <nombre>'. En media sesion RTH acaba a las 13:00 y el postmercado
    a las 17:00, y se dice al lado — un «cerrado» a las 14:00 sin explicacion
    parece una averia.
    """
    a = ahora or datetime.now(tz=ZoneInfo(ET))
    if a.tzinfo is None:
        a = a.replace(tzinfo=ZoneInfo(ET))
    dia = a.date()

    if a.weekday() >= 5:
        return "fin de semana"
    nombre = festivo(dia)
    if nombre:
        return f"festivo: {nombre}"

    corta = media_sesion(dia)
    rth_fin = MEDIA_SESION_FIN if corta else RTH_FIN
    post_fin = MEDIA_SESION_POST_FIN if corta else POST_FIN
    cola = " (media sesion)" if corta else ""

    minutos = a.hour * 60 + a.minute
    if PREMERCADO_INI <= minutos < RTH_INI:
        return "premercado" + cola
    if RTH_INI <= minutos < rth_fin:
        return "RTH" + cola
    if rth_fin <= minutos < post_fin:
        return "postmercado" + cola
    return "cerrado" + cola
