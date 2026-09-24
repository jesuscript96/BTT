"""Envio de los avisos del bot a Telegram.

CREDENCIALES POR ENTORNO, nunca en el codigo:
    TELEGRAM_BOT_TOKEN   token del bot (el de BotFather)
    TELEGRAM_CHAT_ID     id del grupo donde se avisa

INTERRUPTOR APARTE del resto del bot:
    BOT_ALERTS_TELEGRAM  'true' para enviar de verdad; apagado por defecto.

Sin el interruptor NO SE ENVIA NADA: se formatea el mensaje y se deja en el log.
Asi se puede probar el bot un dia entero sin llenarle el grupo a nadie, que es
justo lo que hace falta mientras se ajusta.

DOS COSAS DE TELEGRAM QUE SORPRENDEN:
  * un bot no puede escribir a quien no le haya dado a "Start" antes; en un
    grupo, hay que anyadirlo al grupo primero;
  * el `chat_id` de un grupo es NEGATIVO (empieza por -100 en los supergrupos).
    Si se copia sin el signo, la API responde "chat not found".
"""
from __future__ import annotations

import logging
import os
import queue
import ssl
import threading
import time
from typing import TYPE_CHECKING, Iterable

import httpx

if TYPE_CHECKING:  # evita el import circular en tiempo de ejecucion
    from app.services.bot_alerts_engine import Evento

logger = logging.getLogger("btt.bot_alerts.telegram")

API = "https://api.telegram.org"
TIMEOUT = 10.0


def _verify():
    """Contexto SSL para hablar con Telegram.

    USA EL ALMACEN DE CERTIFICADOS DE WINDOWS, no `certifi`. En esta maquina
    Avast intercepta el trafico HTTPS y reemplaza el certificado del servidor
    por uno firmado por «Avast Web/Mail Shield Root». `certifi` no conoce esa
    autoridad y rechaza la conexion con CERTIFICATE_VERIFY_FAILED; el almacen de
    Windows si la conoce, porque el propio antivirus la instalo ahi.

    Funciona igual sin antivirus de por medio: el almacen del sistema trae
    tambien las autoridades publicas de siempre.
    """
    try:
        ctx = ssl.create_default_context()
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
        return ctx
    except Exception:  # noqa: BLE001
        try:
            import certifi
            return certifi.where()
        except Exception:  # noqa: BLE001
            return True


def _cfg() -> tuple[str, str]:
    return (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )


def envio_activo() -> bool:
    """Si los avisos salen de verdad hacia Telegram."""
    if os.getenv("BOT_ALERTS_TELEGRAM", "false").strip().lower() not in ("1", "true", "yes", "on"):
        return False
    token, chat = _cfg()
    return bool(token and chat)


def motivo_inactivo() -> str:
    """Por que no se esta enviando, para poder decirlo en pantalla."""
    if os.getenv("BOT_ALERTS_TELEGRAM", "false").strip().lower() not in ("1", "true", "yes", "on"):
        return "BOT_ALERTS_TELEGRAM no esta activado"
    token, chat = _cfg()
    if not token:
        return "falta TELEGRAM_BOT_TOKEN"
    if not chat:
        return "falta TELEGRAM_CHAT_ID"
    return ""


def _esc(t: Any) -> str:
    """Escapa lo que va dentro del HTML de Telegram."""
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _num(v: float | None, dec: int = 4) -> str:
    """Numero en formato espanyol: miles con punto, decimales con coma."""
    if v is None:
        return "—"
    s = f"{v:,.{dec}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


SEPARADOR = "------"


def clave_grupo(ev: "Evento") -> tuple:
    """Lo que hace que dos avisos sean LA MISMA senal en cuentas distintas:
    mismo ticker, estrategia, tipo, minuto, motivo/nivel y estado. Solo cambia
    la cuenta (y con ella las acciones)."""
    return (ev.ticker, ev.strategy_id, ev.tipo, str(ev.momento)[:16],
            getattr(ev, "motivo", None), getattr(ev, "nivel", None),
            getattr(ev, "accion_piramide", None), getattr(ev, "estado", "alerta"))


def agrupar(eventos: Iterable["Evento"]) -> list[list["Evento"]]:
    """Junta los avisos hermanos (misma senal, distinta cuenta) en el orden en
    que aparecio la senal. Dentro del grupo, la cuenta de MAS riesgo primero
    (Jaume, 18-sep-2026) y, a igual riesgo, la principal."""
    grupos: dict[tuple, list] = {}
    for ev in eventos:
        grupos.setdefault(clave_grupo(ev), []).append(ev)
    out = []
    for g in grupos.values():
        g.sort(key=lambda e: (-(getattr(e, "riesgo_usd", None) or 0), 1 if getattr(e, "cuenta", None) else 0))
        out.append(g)
    return out


def _etiqueta(ev: "Evento", varias: bool) -> str:
    """El prefijo de cuenta de una linea: solo cuando hay varias cuentas."""
    if not varias:
        return ""
    return f"<b>[{_esc(getattr(ev, 'cuenta', None) or 'principal')}]</b> "


def formatear(ev: "Evento") -> str:
    """El texto de UN aviso (una cuenta). Ver `formatear_grupo`."""
    return formatear_grupo([ev])


def formatear_grupo(eventos: list["Evento"]) -> str:
    """El texto del aviso, en HTML de Telegram, con un bloque POR CUENTA.

    FORMATO AL GRANO (Jaume, 18-sep-2026: «hay que ir al grano en las alertas,
    prealertas, stops, anyadir y take profits»). Tres o cuatro lineas: que es
    (icono + ticker + que hacer), a que precio, y las cantidades. Con varias
    cuentas, la cabecera y el precio van una sola vez, un separador `------`
    y debajo una linea por cuenta con sus acciones, la de mas riesgo primero.
    Asi un take profit en dos cuentas es UN mensaje y no dos.

    SOBRE EL COLOR: Telegram no colorea texto; los emojis marcan la linea.
    Lleva siempre stop y riesgo en las entradas: si el precio se ha movido,
    con esos dos numeros se rehace la cuenta.
    """
    if not eventos:
        return ""
    evs = agrupar(eventos)[0] if len(eventos) > 1 else list(eventos)
    ev = evs[0]
    varias = len(evs) > 1
    hora = str(ev.momento)[11:16]
    largo = (ev.direccion or "").lower().startswith("long")
    lado = "LONG" if largo else "SHORT"
    tk = _esc(ev.ticker)
    est = _esc(ev.estrategia or "")
    prea = getattr(ev, "estado", "alerta") == "prealerta"
    pie = f"<i>— {est} · {hora} —</i>"
    cabecera = ["🔸 <b>PREALERTA</b>"] if prea else []

    if ev.tipo == "entrada":
        icono = "🔺" if largo else "🔻"
        lineas = cabecera + [f"{icono} <b>{tk}</b> · {lado}"]
        precio = f"Precio: <b>{_num(ev.precio)}</b>"
        if ev.stop is not None:
            precio += f" · 🔴 Stop: {_num(ev.stop)}"
        lineas.append(precio)
        bloques = []
        for e in evs:
            b = f"{_etiqueta(e, varias)}Acciones: <b>{_num(e.acciones, 0)}</b>"
            if e.riesgo_usd is not None:
                b += f" (R:{_num(e.riesgo_usd, 0)})"
            bloques.append(b)
        lineas += _unir(bloques) + [pie]
        return "\n".join(lineas)

    if ev.tipo == "piramide":
        lote = {"lot_stop": "STOP DE LOTE", "lot_tp": "TP DE LOTE"}.get(ev.accion_piramide)
        reduce = ev.accion_piramide == "reduce" or lote is not None
        icono = "➖" if reduce else "➕"
        verbo = lote or ("REDUCIR" if reduce else "AÑADIR")
        lineas = cabecera + [f"{icono} <b>{tk}</b> · {verbo}", f"Precio: <b>{_num(ev.precio)}</b>"]
        bloques = []
        for e in evs:
            b = f"{_etiqueta(e, varias)}Acciones: <b>{_num(e.acciones, 0)}</b>"
            if e.posicion_total is not None:
                # Lo que se teclea es el anyadido; el total es para comprobar
                # que la posicion cuadra.
                b += f" <i>(posición total: {_num(e.posicion_total, 0)})</i>"
            bloques.append(b)
        lineas += _unir(bloques) + [pie]
        return "\n".join(lineas)

    # Salida: mismo icono para todos los cierres; el motivo lo dice la linea.
    # QUE CIERRE DEL TODO NO ES QUE CIERRE EL 100 % DE GOLPE: manda lo que
    # queda abierto (posicion_restante); el tamanyo del tramo solo se mira si
    # no lo sabemos (avisos viejos, sin el campo).
    def _entero(e):
        queda_e = getattr(e, "posicion_restante", None)
        total_e = getattr(e, "posicion_total", None)
        if queda_e is not None:
            return queda_e < 0.5
        return bool(e.acciones is not None and total_e and abs(e.acciones - total_e) < 0.5)

    cierre_entero = _entero(ev)
    titulo = "CIERRE POS." if (cierre_entero or ev.acciones is None) else "CIERRE PARCIAL"
    lineas = [f"✅ <b>{tk}</b> · {titulo}",
              f"Precio: <b>{_num(ev.precio)}</b> · ⚫ {_esc(ev.motivo or '?')}"]
    bloques = []
    for e in evs:
        if e.acciones is None:
            continue
        b = f"{_etiqueta(e, varias)}Acciones a cerrar: <b>{_num(e.acciones, 0)}</b>"
        total_e = getattr(e, "posicion_total", None)
        queda_e = getattr(e, "posicion_restante", None)
        if total_e and not _entero(e):
            # El PORCENTAJE va sobre la posicion original («que cierre un 25 %»,
            # como lo piensa Jaume); lo que QUEDA descuenta los tramos ya
            # cerrados. Dos bases distintas a proposito.
            pct = e.acciones / total_e * 100
            queda = queda_e if queda_e is not None else (total_e - e.acciones)
            b += f" <i>({pct:.0f} % de {_num(total_e, 0)} · quedan {_num(queda, 0)})</i>"
        bloques.append(b)
    lineas += _unir(bloques) + [pie]
    return "\n".join(lineas)


def _unir(bloques: list[str]) -> list[str]:
    """Un separador tras el precio/stop y, debajo, una linea por cuenta, una
    encima de otra (Jaume, 18-sep-2026: «colocar precio y stop como estan, un
    separador, y despues las lineas por cuenta»)."""
    return [SEPARADOR] + list(bloques) if bloques else []


def _post(texto: str) -> tuple[bool, bool, str]:
    """Un intento de envio. Devuelve (salio, merece_reintento, detalle).

    Un rechazo de Telegram (4xx: mensaje mal formado, chat equivocado…) no
    cambia por repetirlo; un timeout o un 5xx si.
    """
    token, chat = _cfg()
    try:
        r = httpx.post(
            f"{API}/bot{token}/sendMessage",
            json={
                "chat_id": chat, "text": texto,
                # HTML y no Markdown: en Markdown un ticker con guion bajo
                # (o un guion suelto) rompe el mensaje entero.
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT, verify=_verify(),
        )
        if r.status_code == 200:
            return True, False, ""
        return False, r.status_code >= 500, f"rechazado ({r.status_code}): {r.text[:300]}"
    except Exception as exc:  # noqa: BLE001
        return False, True, f"fallo de envio: {exc}"


def enviar_texto(texto: str) -> bool:
    """Manda un mensaje y espera la respuesta. Devuelve si salio de verdad.

    Nunca lanza: un fallo de red no puede tumbar el bot ni hacerle perder la
    vela siguiente. Si falla, queda en el log y el aviso sigue estando en el
    cuadro de mandos. Es UN intento y bloquea hasta TIMEOUT: para los avisos
    del bot en vivo se usa `encolar`, que no espera y reintenta.
    """
    if not envio_activo():
        logger.info("[TELEGRAM] (no enviado: %s)\n%s", motivo_inactivo(), texto)
        return False
    ok, _, detalle = _post(texto)
    if not ok:
        logger.warning("[TELEGRAM] %s", detalle)
    return ok


# ── Envio en segundo plano ──────────────────────────────────────────────────
#
# 17-sep-2026, 14:31: cinco tramos de take profit a la vez; el tercero (KXIN,
# 394 de 787) se quedo esperando a Telegram 10 s y se dio por perdido. No hubo
# reintento y, peor, el bot entero estuvo esos 10 s parado (el aviso siguiente
# salio 10 s tarde y el feed acumulo 12 s de retraso). Un aviso que Jaume
# ejecuta a mano no puede depender de que Telegram conteste a la primera.
#
# Un solo hilo consume la cola, asi que los mensajes salen en el ORDEN en que
# se generaron (entrada antes que su piramide, tramo 1 antes que tramo 2).

REINTENTOS = 3
ESPERA_REINTENTO = 2.0      # entre intentos: 2 s, luego 4 s

_cola: "queue.Queue[str | None]" = queue.Queue()
_hilo_envio: threading.Thread | None = None
_LOCK_HILO = threading.Lock()
perdidos = 0                 # mensajes que no salieron tras todos los intentos


def enviar_con_reintentos(texto: str) -> bool:
    """Hasta REINTENTOS intentos con espera creciente. Deja en el log si costo
    mas de uno o si al final se perdio. Bloquea: es lo que corre el hilo."""
    global perdidos
    detalle = ""
    intento = 0
    for intento in range(1, REINTENTOS + 1):
        ok, reintentar, detalle = _post(texto)
        if ok:
            if intento > 1:
                logger.warning("[TELEGRAM] enviado al intento %d (antes: %s)", intento, detalle)
            return True
        if not reintentar:
            break
        if intento < REINTENTOS:
            time.sleep(ESPERA_REINTENTO * intento)
    perdidos += 1
    logger.error("[TELEGRAM] PERDIDO tras %d intento(s): %s\n%s", intento, detalle, texto)
    return False


def _bucle_envio() -> None:
    while True:
        texto = _cola.get()
        try:
            if texto is not None:
                enviar_con_reintentos(texto)
        except Exception as exc:  # noqa: BLE001  # el hilo no muere nunca
            logger.error("[TELEGRAM] error inesperado enviando: %s", exc)
        finally:
            _cola.task_done()
        if texto is None:
            return


def encolar(texto: str) -> bool:
    """Deja el mensaje en la cola y vuelve al instante; el hilo de envio lo
    manda con reintentos. Devuelve False solo si Telegram esta apagado."""
    global _hilo_envio
    if not envio_activo():
        logger.info("[TELEGRAM] (no enviado: %s)\n%s", motivo_inactivo(), texto)
        return False
    with _LOCK_HILO:
        if _hilo_envio is None or not _hilo_envio.is_alive():
            _hilo_envio = threading.Thread(target=_bucle_envio, name="telegram-envio", daemon=True)
            _hilo_envio.start()
    _cola.put(texto)
    return True


def pendientes_de_envio() -> int:
    return _cola.unfinished_tasks


def vaciar(espera: float = 30.0) -> bool:
    """Espera a que salga lo encolado (al cerrar el bot). Devuelve si se vacio.

    El hilo es daemon: sin esto, cerrar el bot con un aviso a medio enviar lo
    perderia sin dejar rastro.
    """
    if _hilo_envio is None or not _hilo_envio.is_alive():
        return _cola.unfinished_tasks == 0
    limite = time.time() + espera
    while time.time() < limite:
        if _cola.unfinished_tasks == 0:
            return True
        time.sleep(0.1)
    logger.warning("[TELEGRAM] cierro con %d mensaje(s) sin enviar", _cola.unfinished_tasks)
    return False


def recibir(offset: int = 0, espera: int = 0) -> tuple[list[dict], int]:
    """Mensajes nuevos del chat configurado. Devuelve (mensajes, offset nuevo).

    PRIMERA VEZ QUE EL BOT ESCUCHA. Hasta ahora solo emitia, y eso lo hacia
    inofensivo: nadie podia hacerle nada desde fuera. Al abrir esta puerta hay
    UNA regla que no se salta — **solo se devuelven los mensajes del
    `TELEGRAM_CHAT_ID` configurado**. Un bot de Telegram contesta a cualquiera
    que le escriba si no se filtra, y este sabe precios y estrategias.

    `espera` es el long polling de Telegram: el servidor aguanta la conexion
    hasta que haya algo. 0 = pregunta y vuelve, que es lo que quiere una tarea
    que corre junto al bucle de velas.

    NUNCA lanza. Si Telegram no contesta, se devuelve lo mismo que habia.
    """
    if not envio_activo():
        return [], offset
    token, chat = _cfg()
    try:
        r = httpx.get(
            f"{API}/bot{token}/getUpdates",
            params={"offset": offset, "timeout": espera,
                    "allowed_updates": '["message"]'},
            timeout=TIMEOUT + espera,
        )
        r.raise_for_status()
        datos = r.json()
    except Exception as e:                                   # noqa: BLE001
        logger.debug("[TELEGRAM] no se pudo leer: %s", e)
        return [], offset

    fuera: list[dict] = []
    ultimo = offset
    for u in (datos.get("result") or []):
        ultimo = max(ultimo, int(u.get("update_id", 0)) + 1)
        m = u.get("message") or {}
        origen = str((m.get("chat") or {}).get("id") or "")
        if origen != chat:
            # No es del grupo configurado: ni se procesa ni se contesta.
            logger.warning("[TELEGRAM] mensaje de un chat desconocido (%s), ignorado", origen)
            continue
        texto = (m.get("text") or "").strip()
        if texto:
            fuera.append({"texto": texto, "de": (m.get("from") or {}).get("first_name") or "?"})
    return fuera, ultimo


def enviar_eventos(eventos: Iterable["Evento"]) -> int:
    """Manda una tanda de avisos. Devuelve cuantos salieron."""
    return sum(1 for ev in eventos if enviar_texto(formatear(ev)))


_cache_probar: tuple[float, dict] | None = None
TTL_PROBAR = 60.0


def probar() -> dict:
    """Comprueba la configuracion sin mandar nada al grupo.

    Usa getMe, que solo valida el token. Para saber si el bot puede escribir en
    el grupo hace falta un envio real — eso lo decide el usuario.

    CACHEADO 60 s: esto es una llamada de RED a la API de Telegram, y la pagina
    pedia el estado cada 2 segundos. Con la red lenta, cada peticion se comia
    hasta 10 s de espera y el navegador acababa dando «request timed out».
    El token y el grupo no cambian mientras la app corre.
    """
    global _cache_probar
    ahora = time.time()
    if _cache_probar is not None and ahora - _cache_probar[0] < TTL_PROBAR:
        return dict(_cache_probar[1])

    token, chat = _cfg()
    if not token:
        return {"ok": False, "detalle": "falta TELEGRAM_BOT_TOKEN"}
    try:
        r = httpx.get(f"{API}/bot{token}/getMe", timeout=TIMEOUT, verify=_verify())
        if r.status_code != 200:
            return {"ok": False, "detalle": f"token rechazado ({r.status_code})"}
        nombre = (r.json().get("result") or {}).get("username")
        res = {
            "ok": True,
            "bot": nombre,
            "chat_id": chat or "(sin configurar)",
            "enviando": envio_activo(),
            "detalle": motivo_inactivo() or "listo",
        }
        _cache_probar = (ahora, res)
        return dict(res)
    except Exception as exc:  # noqa: BLE001
        # Un fallo NO se cachea: si es un corte pasajero, el siguiente intento
        # debe volver a probar en vez de dar por muerto a Telegram un minuto.
        return {"ok": False, "detalle": f"error de red: {exc}"}


# ── La misma comprobacion, pero SIN ESPERAR a la red ─────────────────────────
#
# `probar()` cachea los exitos 60 s, pero cuando la cache caduca la peticion que
# llega en ese momento PAGA la llamada a Telegram (hasta TIMEOUT = 10 s), y los
# fallos no se cachean: con Telegram o el DNS lentos, TODAS las peticiones
# esperan. Eso viviria dentro de GET /estado, que el bot sondea cada 5 s con
# 8 s de paciencia: el 15-sep-2026 el bot anoto 22 «timed out» leyendo su
# propio estado, en racimos, mientras el backend respondia en milisegundos al
# resto. Una llamada de red no puede estar en el camino del latido.
#
# Aqui la red va SIEMPRE en un hilo aparte. Quien pregunta recibe al instante
# lo ultimo que se supo (aunque este caducado) y, si toca refrescar, se lanza
# el refresco de fondo. Los fallos si se recuerdan, TTL_FALLO segundos, para no
# relanzar un hilo por peticion cuando Telegram esta caido.
TTL_FALLO = 15.0
_cache_fallo: tuple[float, dict] | None = None
_refresco_en_curso = False
_LOCK_PROBAR = threading.Lock()


def _refrescar_probar() -> None:
    global _cache_fallo, _refresco_en_curso
    try:
        res = probar()                       # la de siempre: red + cache de exitos
        with _LOCK_PROBAR:
            _cache_fallo = None if res.get("ok") else (time.time(), res)
    finally:
        with _LOCK_PROBAR:
            _refresco_en_curso = False


def probar_sin_esperar() -> dict:
    """Lo que sabe de Telegram AHORA, sin tocar la red en este hilo.

    Devuelve la ultima respuesta buena si tiene menos de TTL_PROBAR; si no, el
    ultimo fallo si tiene menos de TTL_FALLO; y si toca refrescar, lanza la
    llamada real en un hilo de fondo y mientras tanto devuelve lo ultimo que
    hubo (o «comprobando…» si nunca hubo nada). Nunca bloquea mas que un lock.
    """
    global _refresco_en_curso
    token, chat = _cfg()
    if not token:
        return {"ok": False, "detalle": "falta TELEGRAM_BOT_TOKEN", "enviando": False}

    ahora = time.time()
    lanzar = False
    with _LOCK_PROBAR:
        bueno, fallo = _cache_probar, _cache_fallo
        if bueno is not None and ahora - bueno[0] < TTL_PROBAR:
            return dict(bueno[1])
        if fallo is not None and ahora - fallo[0] < TTL_FALLO:
            return dict(fallo[1])
        if not _refresco_en_curso:
            _refresco_en_curso = lanzar = True
    if lanzar:
        threading.Thread(target=_refrescar_probar, name="telegram-probar", daemon=True).start()

    # Mientras llega el refresco: lo ultimo que se supo, aunque este viejo.
    if bueno is not None:
        return dict(bueno[1])
    if fallo is not None:
        return dict(fallo[1])
    return {"ok": False, "detalle": "comprobando…", "chat_id": chat or "(sin configurar)",
            "enviando": envio_activo()}
