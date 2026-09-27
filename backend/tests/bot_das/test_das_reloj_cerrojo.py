"""reloj.py y cerrojo.py: veredicto R-J-07, reloj simulado, horas de DAS, cerrojo doble en dos procesos, latido e hilos vigilados.

Sin red: el SNTP se prueba contra un servidor UDP falso en 127.0.0.1 dentro
de un hilo; el «no contesta» con un socket que escucha y calla (timeout corto).
"""
from __future__ import annotations

import os
import socket
import struct
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.bot_das import cerrojo as mod_cerrojo
from app.bot_das.cerrojo import OFFSET_CERROJO, CerrojoInstancia, HiloVigilado, Latido
from app.bot_das.reloj import ET, Reloj, RelojSimulado, a_hora_et, desvio_sntp, hora_das_a_et, veredicto_reloj

BACKEND = Path(__file__).resolve().parents[2]
NTP_DELTA = 2_208_988_800


def _esperar(condicion, timeout_s: float = 3.0) -> bool:
    limite = time.monotonic() + timeout_s
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.005)
    return condicion()


# ── veredicto_reloj (R-J-07) ────────────────────────────────────────────
@pytest.mark.parametrize("desvio,puede,tiene_aviso", [
    pytest.param(0.4, True, False, id="R-J-07-0.4s-nada"),
    pytest.param(0.5, True, False, id="R-J-07-0.5s-exacto-nada"),
    pytest.param(0.6, True, True, id="R-J-07-0.6s-aviso"),
    pytest.param(-0.6, True, True, id="R-J-07-adelantado-0.6s-aviso"),
    pytest.param(2.0, True, True, id="R-J-07-2.0s-exacto-solo-aviso"),
    pytest.param(2.1, False, True, id="R-J-07-2.1s-se-niega"),
    pytest.param(-2.5, False, True, id="R-J-07-adelantado-2.5s-se-niega-(memoria)"),
    pytest.param(0.0, True, False, id="R-J-07-0s"),
])
def test_veredicto_reloj(desvio, puede, tiene_aviso):
    puede_operar, aviso = veredicto_reloj(desvio)
    assert puede_operar is puede
    assert (aviso is not None) is tiene_aviso
    if aviso:
        assert "R-J-07" in aviso


def test_veredicto_sin_sntp():
    assert veredicto_reloj(None) == (True, "sin SNTP")


def test_veredicto_umbrales_inyectables():
    assert veredicto_reloj(1.0, negarse_s=0.9, aviso_s=0.1)[0] is False
    assert veredicto_reloj(1.0, negarse_s=5.0, aviso_s=2.0) == (True, None)


# ── Reloj y RelojSimulado ───────────────────────────────────────────────
def test_reloj_real_es_et_y_monotonico():
    r = Reloj()
    ahora = r.ahora()
    assert ahora.tzinfo is not None and ahora.utcoffset() in (timedelta(hours=-4), timedelta(hours=-5))
    assert r.hoy() == ahora.date()
    assert abs(r.epoch() - time.time()) < 1.0
    m1, m2 = r.mono(), r.mono()
    assert isinstance(m1, float) and m2 >= m1


def test_reloj_simulado_fixture(reloj):
    assert reloj.ahora() == datetime(2026, 9, 25, 9, 30, tzinfo=ET)
    assert reloj.hoy() == date(2026, 9, 25)
    assert reloj.epoch() == reloj.ahora().timestamp()
    assert reloj.mono() == 1000.0                      # nunca 0.0: «0.0 = sin valor» en el estado


def test_reloj_simulado_avanzar_mueve_hora_mono_y_epoch(reloj):
    mono0, epoch0 = reloj.mono(), reloj.epoch()
    reloj.avanzar(61.5)
    assert reloj.ahora() == datetime(2026, 9, 25, 9, 31, 1, 500_000, tzinfo=ET)
    assert reloj.mono() == mono0 + 61.5 and reloj.epoch() == epoch0 + 61.5
    with pytest.raises(ValueError):
        reloj.avanzar(-1)


def test_reloj_simulado_fijar_nunca_retrocede_el_monotonico(reloj):
    mono0 = reloj.mono()
    reloj.fijar(datetime(2026, 9, 25, 9, 40, tzinfo=ET))
    assert reloj.mono() == mono0 + 600
    reloj.fijar(datetime(2026, 9, 25, 9, 0, tzinfo=ET))   # hacia atrás: la hora cambia, mono no
    assert reloj.ahora().hour == 9 and reloj.ahora().minute == 0
    assert reloj.mono() == mono0 + 600
    reloj.fijar(datetime(2026, 9, 26, 4, 0))                # naive = ET
    assert reloj.hoy() == date(2026, 9, 26) and reloj.ahora().tzinfo is ET


def test_reloj_simulado_convierte_aware_a_et():
    r = RelojSimulado(datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc))
    assert r.ahora() == datetime(2026, 9, 25, 9, 30, tzinfo=ET) and r.ahora().tzinfo is ET


# ── horas ───────────────────────────────────────────────────────────────
def test_hora_das_a_et(reloj):
    dt = hora_das_a_et("09:49:27", reloj.hoy())
    assert dt == datetime(2026, 9, 25, 9, 49, 27, tzinfo=ET) and dt.tzinfo is ET   # riesgo 10: fecha = hoy


@pytest.mark.parametrize("texto", ["9:49:27", "09:49", "24:00:00", "09:60:00", "09:49:60", "", "ab:cd:ef", "09:49:27 "],
                         ids=["sin-cero", "sin-segundos", "hora-24", "min-60", "seg-60", "vacio", "letras", "espacio-final-ok?"])
def test_hora_das_a_et_rechaza_mal_formadas(texto):
    if texto == "09:49:27 ":
        assert hora_das_a_et(texto, date(2026, 9, 25)).second == 27   # se recorta espacio exterior
        return
    with pytest.raises(ValueError):
        hora_das_a_et(texto, date(2026, 9, 25))


def test_L0_05_desfase_hora_das_detecta_un_das_en_hora_de_madrid(reloj):
    """L0-05: la hora de un %ORDER recién enviado casa con ET (±60 s) o DAS no está en ET (Madrid = +6 h)."""
    from app.bot_das.reloj import DESFASE_HORA_DAS_MAX_S, desfase_hora_das_s, hora_das_es_et

    ahora = datetime(2026, 9, 25, 9, 30, 10, tzinfo=ET)
    assert desfase_hora_das_s("09:30:12", ahora) == pytest.approx(2.0)
    assert desfase_hora_das_s("09:29:40", ahora) == pytest.approx(-30.0)
    assert hora_das_es_et("09:30:12", ahora) and DESFASE_HORA_DAS_MAX_S == 60.0
    assert desfase_hora_das_s("15:30:10", ahora) == pytest.approx(6 * 3600)      # DAS en hora de Madrid
    assert not hora_das_es_et("15:30:10", ahora)
    assert hora_das_es_et("09:30:10", ahora.astimezone(timezone.utc))            # un aware en UTC se convierte a ET
    cerca_medianoche = datetime(2026, 9, 25, 23, 59, 50, tzinfo=ET)
    assert desfase_hora_das_s("00:00:05", cerca_medianoche) == pytest.approx(15.0)   # no es un desfase de 24 h
    assert hora_das_es_et("09:31:30", ahora, tolerancia_s=90.0) and not hora_das_es_et("09:31:30", ahora)
    with pytest.raises(ValueError):
        desfase_hora_das_s("9:30", ahora)


def test_a_hora_et_respeta_el_horario_de_verano():
    invierno = a_hora_et("03:55", date(2026, 1, 15))
    verano = a_hora_et("03:55", date(2026, 7, 15))
    assert invierno.utcoffset() == timedelta(hours=-5) and verano.utcoffset() == timedelta(hours=-4)
    assert (invierno.hour, invierno.minute) == (3, 55)
    with pytest.raises(ValueError):
        a_hora_et("03:55:00", date(2026, 1, 15))
    with pytest.raises(ValueError):
        a_hora_et("25:00", date(2026, 1, 15))


# ── desvio_sntp con un servidor UDP falso (sin red) ─────────────────────
def _paquete_sntp(desvio_s: float, stratum: int = 1) -> bytes:
    ahora = time.time() + desvio_s
    seg = int(ahora) + NTP_DELTA
    frac = int((ahora - int(ahora)) * 2**32)
    cabecera = (0 << 30) | (4 << 27) | (4 << 24) | (stratum << 16)   # LI=0, VN=4, Mode=4 (servidor)
    return struct.pack("!12I", cabecera, 0, 0, 0, 0, 0, 0, 0, seg, frac, seg, frac)


@pytest.fixture
def servidor_udp():
    """Fábrica: servidor_udp(responder) → puerto; `responder(datos) -> bytes | None` (None = callar)."""
    recursos = []

    def _arrancar(responder):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(0.05)
        parar = threading.Event()

        def bucle():
            while not parar.is_set():
                try:
                    datos, quien = sock.recvfrom(1024)
                except socket.timeout:
                    continue
                except OSError:
                    break
                respuesta = responder(datos)
                if respuesta is not None:
                    sock.sendto(respuesta, quien)

        hilo = threading.Thread(target=bucle, daemon=True)
        hilo.start()
        recursos.append((sock, parar, hilo))
        return sock.getsockname()[1]

    try:
        yield _arrancar
    finally:
        for sock, parar, hilo in recursos:
            parar.set()
            hilo.join(1.0)
            sock.close()


def test_desvio_sntp_mide_el_desvio(servidor_udp):
    puerto = servidor_udp(lambda datos: _paquete_sntp(1.5) if len(datos) == 48 and datos[0] == 0x1B else None)
    desvio = desvio_sntp("127.0.0.1", timeout_s=2.0, puerto=puerto)
    assert desvio is not None and abs(desvio - 1.5) < 0.25      # positivo = local atrasado


def test_desvio_sntp_reloj_adelantado_se_niega(servidor_udp):
    puerto = servidor_udp(lambda datos: _paquete_sntp(-2.5))
    desvio = desvio_sntp("127.0.0.1", timeout_s=2.0, puerto=puerto)
    assert desvio is not None and abs(desvio + 2.5) < 0.25
    assert veredicto_reloj(desvio)[0] is False


def test_desvio_sntp_none_si_calla(servidor_udp):
    puerto = servidor_udp(lambda datos: None)
    t0 = time.monotonic()
    assert desvio_sntp("127.0.0.1", timeout_s=0.2, puerto=puerto) is None
    assert time.monotonic() - t0 < 2.0


def test_desvio_sntp_none_con_kiss_of_death_o_paquete_corto(servidor_udp):
    puerto_kod = servidor_udp(lambda datos: _paquete_sntp(0.0, stratum=0))
    assert desvio_sntp("127.0.0.1", timeout_s=1.0, puerto=puerto_kod) is None
    puerto_corto = servidor_udp(lambda datos: b"\x24" * 10)
    assert desvio_sntp("127.0.0.1", timeout_s=1.0, puerto=puerto_corto) is None


def test_desvio_sntp_none_con_puerto_cerrado_o_host_invalido():
    assert desvio_sntp("127.0.0.1", timeout_s=0.3, puerto=1) is None
    assert desvio_sntp("", timeout_s=0.3, puerto=70_000) is None   # puerto imposible → OverflowError → None


# ── CerrojoInstancia (R-J-04 c) ────────────────────────────────────────
def _codigo_hijo(ruta: Path, morir_sin_soltar: bool = False) -> str:
    return (
        "import os, sys\n"
        f"sys.path.insert(0, {str(BACKEND)!r})\n"
        "from pathlib import Path\n"
        "from app.bot_das.cerrojo import CerrojoInstancia\n"
        f"c = CerrojoInstancia(Path({str(ruta)!r}))\n"
        "print(('TOMADO' if c.adquirir() else 'OCUPADO') + ' ' + str(os.getpid()), flush=True)\n"
        + ("os._exit(0)\n" if morir_sin_soltar else "sys.stdin.readline()\nc.soltar()\nprint('SOLTADO', flush=True)\n")
    )


def _leer_estado(proc: subprocess.Popen) -> tuple[str, int]:
    """«TOMADO <pid>» / «OCUPADO <pid>» del hijo. OJO: con el python.exe del venv (launcher) `proc.pid` NO es
    el PID del intérprete que escribe el fichero; por eso el hijo dice el suyo (trampa para el supervisor, lote G)."""
    estado, pid = proc.stdout.readline().split()
    return estado, int(pid)


@pytest.fixture
def hijo():
    procesos = []

    def _lanzar(ruta: Path, morir_sin_soltar: bool = False) -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "-c", _codigo_hijo(ruta, morir_sin_soltar)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        procesos.append(proc)
        return proc

    try:
        yield _lanzar
    finally:
        for proc in procesos:
            if proc.poll() is None:
                proc.kill()
            proc.wait(10)


def test_cerrojo_doble_en_dos_procesos(dir_bot, hijo):
    ruta = dir_bot / "estado" / "cerrojo_ejecutor.lock"
    proc = hijo(ruta)
    estado, pid_hijo = _leer_estado(proc)
    assert estado == "TOMADO"
    assert CerrojoInstancia.pid_guardado(ruta) == pid_hijo          # legible mientras el otro lo tiene
    nuestro = CerrojoInstancia(ruta)
    assert nuestro.adquirir() is False and nuestro.tomado is False   # la segunda instancia NO arranca
    assert CerrojoInstancia.pid_guardado(ruta) == pid_hijo           # y no pisa el PID del dueño
    proc.stdin.write("\n")
    proc.stdin.flush()
    assert proc.stdout.readline().strip() == "SOLTADO"
    assert proc.wait(10) == 0
    assert nuestro.adquirir() is True and nuestro.tomado
    assert CerrojoInstancia.pid_guardado(ruta) == os.getpid()
    nuestro.soltar()
    assert nuestro.tomado is False


def test_cerrojo_nuestro_bloquea_al_hijo(dir_bot, hijo):
    ruta = dir_bot / "estado" / "cerrojo_vigilante.lock"
    nuestro = CerrojoInstancia(ruta)
    try:
        assert nuestro.adquirir() is True
        assert nuestro.adquirir() is True                          # idempotente en la misma instancia
        proc = hijo(ruta)
        assert _leer_estado(proc)[0] == "OCUPADO"
        proc.stdin.write("\n")
        proc.stdin.flush()
        proc.wait(10)
        assert CerrojoInstancia.pid_guardado(ruta) == os.getpid()
        assert CerrojoInstancia(ruta).adquirir() is False          # ni otra instancia del MISMO proceso
    finally:
        nuestro.soltar()


def test_cerrojo_se_libera_si_el_proceso_muere_sin_soltar(dir_bot, hijo):
    ruta = dir_bot / "estado" / "cerrojo_supervisor.lock"
    proc = hijo(ruta, morir_sin_soltar=True)
    estado, pid_hijo = _leer_estado(proc)
    assert estado == "TOMADO" and CerrojoInstancia.pid_guardado(ruta) == pid_hijo
    proc.wait(10)
    nuestro = CerrojoInstancia(ruta)
    assert nuestro.adquirir() is True                              # el SO lo soltó con el proceso muerto
    nuestro.soltar()


def test_pid_guardado_sin_fichero_o_basura(dir_bot):
    assert CerrojoInstancia.pid_guardado(dir_bot / "estado" / "no_existe.lock") is None
    basura = dir_bot / "estado" / "basura.lock"
    basura.write_text("no es un pid", encoding="ascii")
    assert CerrojoInstancia.pid_guardado(basura) is None
    assert CerrojoInstancia.pid_guardado(basura) is None and OFFSET_CERROJO >= 1 << 20


def test_cerrojo_crea_el_directorio(tmp_path):
    c = CerrojoInstancia(tmp_path / "nuevo" / "estado" / "cerrojo.lock")
    assert c.adquirir() is True and c.ruta.exists()
    c.soltar()
    c.soltar()   # soltar dos veces no falla


# ── Latido (R-J-04 b) ──────────────────────────────────────────────────
def test_latido_escribe_atomico_y_edad(dir_bot, reloj):
    ruta = dir_bot / "estado" / "latido_ejecutor"
    assert Latido.edad(ruta, reloj.epoch()) is None
    latido = Latido(ruta, reloj)
    latido.tocar()
    assert latido.escrituras == 1 and latido.fallos == 0
    assert Latido.edad(ruta, reloj.epoch()) == 0.0
    assert not ruta.with_name(ruta.name + ".tmp").exists()        # os.replace: nunca queda el tmp
    reloj.avanzar(2.5)
    assert Latido.edad(ruta, reloj.epoch()) == 2.5


def test_latido_como_mucho_cada_cada_s(dir_bot, reloj):
    ruta = dir_bot / "estado" / "latido_ejecutor"
    latido = Latido(ruta, reloj, cada_s=1.0)
    latido.tocar()
    reloj.avanzar(0.5)
    latido.tocar()                                                 # demasiado pronto: no escribe
    assert latido.escrituras == 1 and Latido.edad(ruta, reloj.epoch()) == 0.5
    reloj.avanzar(0.5)
    latido.tocar()                                                 # 1,0 s exactos: escribe
    assert latido.escrituras == 2 and Latido.edad(ruta, reloj.epoch()) == 0.0


def test_latido_todo_vivo_false_no_escribe(dir_bot, reloj):
    ruta = dir_bot / "estado" / "latido_ejecutor"
    latido = Latido(ruta, reloj)
    latido.tocar()
    reloj.avanzar(5.0)
    latido.tocar(todo_vivo=False)                                  # injerto §8.11: el supervisor lo verá viejo
    assert latido.escrituras == 1 and Latido.edad(ruta, reloj.epoch()) == 5.0
    latido.tocar(todo_vivo=True)
    assert latido.escrituras == 2 and Latido.edad(ruta, reloj.epoch()) == 0.0


def test_latido_no_lanza_si_el_disco_falla(dir_bot, reloj, monkeypatch):
    ruta = dir_bot / "estado" / "latido_ejecutor"
    latido = Latido(ruta, reloj)

    def falla(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(mod_cerrojo.os, "replace", falla)
    latido.tocar()
    assert latido.fallos == 1 and latido.escrituras == 0 and "No space" in (latido.ultimo_error or "")
    assert Latido.edad(ruta, reloj.epoch()) is None


def test_latido_edad_con_contenido_raro(dir_bot, reloj):
    ruta = dir_bot / "estado" / "latido_raro"
    ruta.write_text("hola", encoding="ascii")
    assert Latido.edad(ruta, reloj.epoch()) is None


# ── HiloVigilado (injerto §8.11) ───────────────────────────────────────
def test_hilo_vigilado_relanza_y_para_tras_max_relanzos():
    llamadas, caidas = [], []

    def cuerpo():
        llamadas.append(1)
        raise RuntimeError(f"boom {len(llamadas)}")

    hilo = HiloVigilado("das-lector", cuerpo, lambda n, e, r: caidas.append((n, e, r)), max_relanzos=5, espera_s=0.005)
    hilo.arrancar()
    assert _esperar(lambda: not hilo.vivo)
    assert len(llamadas) == 6 and hilo.caidas == 6
    assert [r for _n, _e, r in caidas] == [True] * 5 + [False]
    assert all(n == "das-lector" for n, _e, _r in caidas)
    assert caidas[0][1] == "RuntimeError: boom 1" and "boom 6" in caidas[-1][1]
    assert hilo.ultima_traza and "RuntimeError" in hilo.ultima_traza


def test_hilo_vigilado_max_relanzos_cero_no_relanza():
    caidas = []

    def cuerpo():
        raise ValueError("una")

    hilo = HiloVigilado("x", cuerpo, lambda n, e, r: caidas.append(r), max_relanzos=0, espera_s=0.0)
    hilo.arrancar()
    assert _esperar(lambda: not hilo.vivo)
    assert caidas == [False] and hilo.caidas == 1


def test_hilo_vigilado_parar_cooperativo():
    vueltas = []

    def cuerpo():
        while not hilo.parando.is_set():
            vueltas.append(1)
            hilo.parando.wait(0.005)

    hilo = HiloVigilado("fuente-tuberia", cuerpo, lambda *_a: None, espera_s=0.005)
    hilo.arrancar()
    assert _esperar(lambda: len(vueltas) >= 2) and hilo.vivo
    hilo.parar(espera_s=2.0)
    assert not hilo.vivo and hilo.caidas == 0
    hilo.parar()   # idempotente


def test_hilo_vigilado_cuerpo_que_termina_no_se_relanza():
    llamadas = []
    hilo = HiloVigilado("config-vigia", lambda: llamadas.append(1), lambda *_a: None, espera_s=0.005)
    hilo.arrancar()
    assert _esperar(lambda: not hilo.vivo)
    assert llamadas == [1] and hilo.caidas == 0
    hilo.arrancar()                                                # se puede volver a arrancar
    assert _esperar(lambda: not hilo.vivo) and llamadas == [1, 1]


def test_hilo_vigilado_se_recupera_y_un_aviso_roto_no_impide_relanzar():
    llamadas, avisos = [], []

    def cuerpo():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise OSError("socket cerrado")

    def al_caida(nombre, error, relanzado):
        avisos.append(relanzado)
        raise RuntimeError("el aviso falla")

    hilo = HiloVigilado("das-emisor", cuerpo, al_caida, max_relanzos=5, espera_s=0.005)
    hilo.arrancar()
    assert _esperar(lambda: not hilo.vivo)
    assert len(llamadas) == 3 and hilo.caidas == 2 and avisos == [True, True]


def test_hilo_vigilado_parar_durante_la_espera_no_relanza():
    llamadas, avisos = [], []

    def cuerpo():
        llamadas.append(1)
        raise RuntimeError("cae")

    hilo = HiloVigilado("telegram-recibo", cuerpo, lambda n, e, r: avisos.append(r), max_relanzos=50, espera_s=5.0)
    hilo.arrancar()
    assert _esperar(lambda: len(avisos) == 1)
    hilo.parar(espera_s=2.0)                                      # estaba esperando 5 s: sale al instante
    assert not hilo.vivo and len(llamadas) == 1 and avisos == [True]


def test_hilo_vigilado_rechaza_parametros_negativos():
    with pytest.raises(ValueError):
        HiloVigilado("x", lambda: None, lambda *_a: None, max_relanzos=-1)
    with pytest.raises(ValueError):
        HiloVigilado("x", lambda: None, lambda *_a: None, espera_s=-0.1)
    with pytest.raises(ValueError):
        HiloVigilado("x", lambda: None, lambda *_a: None, estable_s=-1.0)


class _MonoFalso:
    """Reloj monotónico a mano: el cuerpo lo adelanta para simular que corrió mucho rato antes de caer."""

    def __init__(self) -> None:
        self.t = 5_000.0

    def __call__(self) -> float:
        return self.t


def test_L0_02_seis_caidas_aisladas_tras_rachas_estables_siguen_relanzando():
    """L0-02: seis caídas separadas por ≥ 60 s de cuerpo estable NO agotan max_relanzos=5 (fallos sueltos en 16 h)."""
    mono = _MonoFalso()
    llamadas, relanzos = [], []

    def cuerpo():
        llamadas.append(1)
        if len(llamadas) <= 6:
            mono.t += 61.0                               # corrió 61 s «estable» y luego cae
            raise RuntimeError(f"fallo suelto {len(llamadas)}")
        # la séptima vuelta termina por las buenas

    hilo = HiloVigilado("avisos-envio", cuerpo, lambda n, e, r: relanzos.append(r), max_relanzos=5, espera_s=0.0,
                        mono=mono)
    hilo.arrancar()
    assert _esperar(lambda: not hilo.vivo)
    assert relanzos == [True] * 6 and len(llamadas) == 7
    assert hilo.caidas == 6 and hilo.caidas_seguidas == 1          # el total se sigue contando (métrica)


def test_L0_02_seis_caidas_seguidas_paran_el_hilo():
    """L0-02: seis caídas SIN racha estable entre ellas (un bucle de caída) paran el hilo con relanzado=False."""
    mono = _MonoFalso()
    relanzos = []

    def cuerpo():
        mono.t += 1.0                                    # cae al segundo: bucle de caída
        raise RuntimeError("bucle")

    hilo = HiloVigilado("das-lector", cuerpo, lambda n, e, r: relanzos.append(r), max_relanzos=5, espera_s=0.0,
                        mono=mono)
    hilo.arrancar()
    assert _esperar(lambda: not hilo.vivo)
    assert relanzos == [True] * 5 + [False] and hilo.caidas_seguidas == 6


def test_L0_02_arrancar_tras_agotar_pone_las_seguidas_a_cero():
    """L0-02: un `arrancar()` tras un paro por agotamiento empieza con la cuenta de seguidas a 0 (no cae «a la primera»)."""
    mono = _MonoFalso()
    relanzos = []

    def cuerpo():
        raise RuntimeError("cae")

    hilo = HiloVigilado("config-vigia", cuerpo, lambda n, e, r: relanzos.append(r), max_relanzos=1, espera_s=0.0,
                        mono=mono)
    hilo.arrancar()
    assert _esperar(lambda: not hilo.vivo)
    assert relanzos == [True, False]
    hilo.arrancar()
    assert _esperar(lambda: not hilo.vivo)
    assert relanzos == [True, False, True, False] and hilo.caidas == 4


# ── CanalFalso: el ORDEN invalidar → enviar (L0-01, riesgo 7, injerto §8.6) ──
def test_L0_01_canal_falso_graba_invalidar_y_enviar_en_una_sola_secuencia():
    """L0-01: `eventos` guarda invalidar y enviar en el orden real; un decisor que invalidara DESPUÉS de encolar
    el stop nuevo ya no pasa el test (antes eran dos listas separadas sin orden común)."""
    from canal_falso import EVENTO_ENVIAR, EVENTO_INVALIDAR, CanalFalso

    bien = CanalFalso()
    bien.enviar("NEWORDER 126800001 SS XYZ SAGEREB 100 3.45 PostOnly TIF=DAY+")
    bien.invalidar("stops:XYZ", 1)
    bien.enviar("NEWORDER 126800002 B XYZ STOP 100 STOPLMTP 4 4.12 TIF=DAY+", "stops:XYZ", 1)
    assert bien.eventos == [
        (EVENTO_ENVIAR, "NEWORDER 126800001 SS XYZ SAGEREB 100 3.45 PostOnly TIF=DAY+", None, 0),
        (EVENTO_INVALIDAR, "stops:XYZ", 1),
        (EVENTO_ENVIAR, "NEWORDER 126800002 B XYZ STOP 100 STOPLMTP 4 4.12 TIF=DAY+", "stops:XYZ", 1),
    ]
    assert bien.indice_invalidar("stops:XYZ", 1) == 1 and bien.indice_primer_envio("stops:XYZ", 1) == 2
    assert bien.invalida_antes_de_enviar("stops:XYZ", 1)
    # compatibilidad: las dos listas de antes siguen igual
    assert bien.series_invalidadas == [("stops:XYZ", 1)] and len(bien.lineas) == 2

    mal = CanalFalso()
    mal.enviar("NEWORDER 126800002 B XYZ STOP 100 STOPLMTP 4 4.12 TIF=DAY+", "stops:XYZ", 1)
    mal.invalidar("stops:XYZ", 1)
    assert not mal.invalida_antes_de_enviar("stops:XYZ", 1)
    assert not CanalFalso().invalida_antes_de_enviar("stops:XYZ", 1)              # sin invalidar no vale
    solo = CanalFalso()
    solo.invalidar("stops:XYZ", 2)
    assert solo.invalida_antes_de_enviar("stops:XYZ", 2) and solo.indice_primer_envio("stops:XYZ") is None
