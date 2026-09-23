"""El reintento del cliente del bot cuando la conexion reutilizada esta muerta.

POR QUE EXISTE ESTO. El bot crea el cliente UNA VEZ y reutiliza las conexiones.
Pregunta cada 5 segundos (`INTERVALO_ESTADO`) y **el keep-alive de uvicorn son
tambien 5 segundos**: cliente y servidor hacen las dos cosas a la vez y la
peticion sale por un socket que el otro lado acaba de cerrar.

MEDIDO CONTRA EL BACKEND REAL, y el hueco lo es todo:

    huecos de 12 s (pasado el limite)  ->   0 fallos de  18
    huecos de  5 s (en el limite)      ->  29 fallos de 416   (7,0 %)
    idem, con reintento                ->   0 fallos de 416

Falla SIEMPRE la primera peticion despues del hueco, que es la unica que se
encuentra la conexion podrida. En el bot esa primera es el GET del estado:
medido, de 832 peticiones fallaron 19 y **las 19 eran el GET**. Los POST se
reintentan igualmente por prudencia, no porque se les haya visto fallar.

En el log del 9-sep-2026 son 1.371 fallos de este tipo. Y no era cosmetico:
`debe_vigilar()` devuelve None cuando falla, asi que un fallo justo al pulsar
«Vigilar» retrasaba el interruptor un ciclo entero.
"""
import httpx
import pytest

from app.services import bot_alerts_cliente as mod


class _ClienteFalso:
    """Falla las N primeras veces con el error que se le pase, luego responde."""

    def __init__(self, fallos=0, error=None, cuerpo=None):
        self.fallos = fallos
        self.error = error or httpx.RemoteProtocolError(
            "Server disconnected without sending a response.")
        self.cuerpo = cuerpo if cuerpo is not None else {"vigilando": True}
        self.llamadas = []
        self.cerrado = False

    def request(self, metodo, url, **kw):
        self.llamadas.append((metodo, url))
        if self.fallos > 0:
            self.fallos -= 1
            raise self.error
        # `raise_for_status()` necesita la peticion enganchada a la respuesta
        return httpx.Response(200, json=self.cuerpo,
                              request=httpx.Request(metodo, url))

    def close(self):
        self.cerrado = True


@pytest.fixture
def cliente(monkeypatch):
    """Un ClienteBackend que nunca toca la red: el de dentro y el que se crea
    al reintentar son los dos falsos."""
    creados = []
    conf = {"cuerpo": {"vigilando": True}}      # lo que responde el del reintento

    def fabrica(*a, **kw):
        c = _ClienteFalso(cuerpo=conf["cuerpo"])
        creados.append(c)
        return c

    monkeypatch.setattr(mod.httpx, "Client", fabrica)
    c = mod.ClienteBackend("http://backend")
    c._creados = creados
    c._conf = conf
    return c


def test_una_lectura_que_falla_se_repite_y_sale_bien(cliente):
    primero = _ClienteFalso(fallos=1)
    cliente._cli = primero
    assert cliente.debe_vigilar() is True
    # el pozo entero se tira: la conexion podrida no puede quedarse dentro
    assert primero.cerrado is True
    assert cliente._cli is not primero


def test_el_interruptor_llega_a_la_primera_pese_al_fallo(cliente):
    """Lo que le pasaba a Jaume: pulsaba «Vigilar» y el bot no se enteraba
    hasta el ciclo siguiente porque la lectura se habia perdido."""
    cliente._cli = _ClienteFalso(fallos=1)
    assert cliente.debe_vigilar() is True     # antes: None


def test_si_falla_dos_veces_se_rinde_y_devuelve_none(cliente, monkeypatch):
    """None NO es «apagado»: ante la duda el bot sigue como estaba. Se reintenta
    UNA vez, no en bucle — el backend puede estar de verdad caido."""
    segundo = _ClienteFalso(fallos=1)
    monkeypatch.setattr(mod.httpx, "Client", lambda *a, **kw: segundo)
    cliente._cli = _ClienteFalso(fallos=1)
    assert cliente.debe_vigilar() is None
    assert len(segundo.llamadas) == 1        # uno y no mas


def test_conexion_rechazada_tambien_se_reintenta(cliente):
    """10061: el backend estaba reiniciandose. Si ya volvio, el segundo intento
    entra."""
    cliente._cli = _ClienteFalso(fallos=1, error=httpx.ConnectError("10061"))
    assert cliente.debe_vigilar() is True


def test_un_post_de_avisos_SI_se_repite_y_no_duplica(cliente):
    """`ReadError` es el fallo mas frecuente (25 de 29 reproducidos), asi que
    dejar los POST fuera del reintento arreglaria muy poco.

    Y repetir es seguro: `guardar_eventos` hace `INSERT OR REPLACE` con un id
    estable (ticker+estrategia+momento+tipo), y **ese endpoint no manda
    Telegram** — los avisos los manda el bot. Reenviar la misma tanda no
    duplica ni filas ni mensajes."""
    cliente._conf["cuerpo"] = {"guardados": 1}
    falso = _ClienteFalso(fallos=1, error=httpx.ReadError("10054"))
    cliente._cli = falso
    assert cliente.publicar([{"ticker": "AAPL"}]) == 1


def test_un_post_SI_se_repite_si_no_llego_a_salir(cliente):
    """`RemoteProtocolError` es «cerraron sin responder»: el backend no llego a
    ver nada."""
    cliente._conf["cuerpo"] = {"guardados": 3}
    cliente._cli = _ClienteFalso(fallos=1)
    assert cliente.publicar([{"ticker": "AAPL"}]) == 3


def test_una_lectura_SI_se_repite_aunque_el_corte_fuera_leyendo(cliente):
    """Un GET se puede repetir sin consecuencias."""
    cliente._conf["cuerpo"] = {"estrategias": [{"id": 1}]}
    cliente._cli = _ClienteFalso(fallos=1, error=httpx.ReadError("10054"))
    assert cliente.vigiladas() == [{"id": 1}]


def test_sin_fallos_no_se_toca_el_cliente(cliente):
    """El camino normal no puede pagar nada por esto."""
    primero = _ClienteFalso()
    cliente._cli = primero
    assert cliente.debe_vigilar() is True
    assert cliente._cli is primero
    assert primero.cerrado is False
    assert len(primero.llamadas) == 1


def test_un_timeout_NO_se_reintenta(cliente):
    """Un corte de conexion falla al instante, pero un timeout ya ha esperado
    sus 8 segundos: repetirlo dejaria al bot parado 16 en una llamada que se
    hace en el hilo principal. Y eran 30 fallos de 6.114 — no compensa."""
    falso = _ClienteFalso(fallos=1, error=httpx.ReadTimeout("tarda"))
    cliente._cli = falso
    assert cliente.debe_vigilar() is None
    assert len(falso.llamadas) == 1


def test_el_latido_tambien_se_reintenta(cliente):
    """Sobrescribe estado: repetirlo es escribir lo mismo encima."""
    falso = _ClienteFalso(fallos=1, error=httpx.ReadError("10053"))
    cliente._cli = falso
    cliente.latir(3, "websocket", "en espera")     # no revienta
    assert falso.cerrado is True
    assert len(cliente._creados) >= 1
