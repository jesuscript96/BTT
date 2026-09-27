"""Tests del supervisor del bot de DAS (lote G2, §10 «test_das_supervisor»; R-J-04 v2, R-J-06, R-J-07, R-L-01, EP-7, riesgo 26).

QUÉ PRUEBA.
  `PlanRelanzamiento` (1/2/5/10 y luego 10; reinicio tras 300 s estable); el
  orden de arranque DAS → vigilante → (latido o 10 s) → ejecutor; relanzos
  1/2/5/10/10 de un hijo REAL que muere (`sys.executable -c`); el colgado a
  los 3 s (hijo real que no late) y el que no late nunca tras lanzarse; el
  hijo que sale con 0 sin pedirlo no se relanza; la ventana R-L-01 (config,
  `horario.apagar`, media sesión, sin config, festivo con el calendario
  real sin red); doble instancia; peticiones de `orden_supervisor.jsonl`;
  huérfano con cerrojo tomado y sin latido → muerto por su PID, y adoptado
  si late; DAS sin `DAS_EXE` no lanza nada, con `DAS_EXE` cerrado se abre y
  avisa 3, puerto sin API → no arranca hijos y avisa; apagado ordenado
  fuera de la ventana y NO apagado con posición (L4); disco bajo (R-J-07);
  `main` con doble instancia; importar sin red ni hilos.

POR QUÉ ASÍ. Las decisiones del supervisor van con el reloj inyectado
(`RelojSimulado`): los plazos de 1, 2, 5, 10, 3 y 300 s se recorren en
milisegundos moviendo el reloj; los latidos los escribe el test con ese mismo
reloj. Los procesos son de verdad cuando importa (morir, matar, cerrojo en
otro proceso) y falsos cuando solo se mira la decisión.

LAS TRAMPAS.
  * El `python.exe` del venv es un lanzador: el PID que se mata por cerrojo
    es el del intérprete (el que escribe el fichero), no el del Popen.
  * Todo proceso lanzado se mata en el `finally` de la fixture.
  * `main` se prueba con `RUTA_DOTENV` apuntando a un fichero inexistente: el
    test nunca carga el `.env` real.
"""
from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

from app.bot_das import VERSION
from app.bot_das import config as mod_config
from app.bot_das import supervisor as sup_mod
from app.bot_das.cerrojo import CerrojoInstancia
from app.bot_das.diario import Diario
from app.bot_das.reloj import ET, RelojSimulado
from app.bot_das.supervisor import PlanRelanzamiento, Supervisor
from app.bot_das.tipos import Fase, Nivel

BACKEND = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
CUENTA = "CUENTA_PRUEBA"
HIJO_DORMIDO = "import time; time.sleep(60)"
HIJO_MUERE = "import sys; sys.exit(1)"
HIJO_SALE_BIEN = "import sys; sys.exit(0)"
PLAZO_REAL_S = 10.0

HIJO_CON_CERROJO = r"""
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app.bot_das.cerrojo import CerrojoInstancia
cerrojo = CerrojoInstancia(Path(sys.argv[2]))
if not cerrojo.adquirir():
    sys.exit(7)
print("listo", flush=True)
time.sleep(60)
"""


# ═══════════════════════════ dobles ══════════════════════════════════════
class AvisosGrabados:
    """La cola de avisos, síncrona y en memoria."""

    def __init__(self) -> None:
        self.avisos: list[Any] = []
        self.arrancado = False
        self.parado = False

    def poner(self, aviso: Any) -> None:
        self.avisos.append(aviso)

    def arrancar(self) -> None:
        self.arrancado = True

    def parar(self, espera_s: float = 30.0) -> None:
        self.parado = True

    def de_nivel(self, nivel: Nivel) -> list[str]:
        return [a.texto for a in self.avisos if a.nivel is nivel]

    def claves(self) -> list[Optional[str]]:
        return [a.clave for a in self.avisos]


class ProcesoFalso:
    """Popen falso: vive hasta `terminate`/`kill` o hasta que `salir(codigo)`; `obedece` sale con 0 al leer su «parar»."""

    _siguiente_pid = 40_000

    def __init__(self, argv: list, ruta_orden: Optional[Path] = None, nombre: Optional[str] = None,
                 **kw: Any) -> None:
        ProcesoFalso._siguiente_pid += 1
        self.pid = ProcesoFalso._siguiente_pid
        self.argv = list(argv)
        self.kw = kw
        self.codigo: Optional[int] = None
        self.terminado = False
        self._ruta_orden = ruta_orden
        self._nombre = nombre

    def salir(self, codigo: int) -> None:
        self.codigo = codigo

    def poll(self) -> Optional[int]:
        if self.codigo is None and self._ruta_orden is not None and self._ruta_orden.exists():
            for linea in self._ruta_orden.read_text(encoding="utf-8").splitlines():
                peticion = json.loads(linea)
                if peticion.get("parar") is True and peticion.get("para") in (self._nombre, "todos"):
                    self.codigo = 0
        return self.codigo

    def terminate(self) -> None:
        self.terminado = True
        if self.codigo is None:
            self.codigo = 1

    kill = terminate

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        return self.codigo


class PopenEspia:
    """Registra cada llamada; devuelve `ProcesoFalso` (los hijos se reconocen por el último argumento)."""

    def __init__(self, ruta_orden: Optional[Path] = None) -> None:
        self.llamadas: list[tuple[list, dict]] = []
        self.procesos: list[ProcesoFalso] = []
        self._ruta_orden = ruta_orden

    def __call__(self, argv: list, **kw: Any) -> ProcesoFalso:
        self.llamadas.append((list(argv), kw))
        nombre = next((n for n in sup_mod.HIJOS if str(argv[-1]).endswith(n)), None)
        p = ProcesoFalso(argv, ruta_orden=self._ruta_orden, nombre=nombre, **kw)
        self.procesos.append(p)
        return p

    def de(self, nombre: str) -> list[ProcesoFalso]:
        return [p for p in self.procesos if str(p.argv[-1]).endswith(nombre)]


# ═══════════════════════════ ayudas ══════════════════════════════════════
def firmar(crudo: dict) -> dict:
    """Recalcula los hashes canónicos de un fichero del cuadro modificado (lote 0: hash_canonico)."""
    for e in crudo["estrategias"]:
        e["definition_hash"] = "sha256:" + mod_config.hash_canonico(e["definition"])
    crudo["estrategias_hash"] = "sha256:" + mod_config.hash_canonico(crudo["estrategias"])
    crudo["sha256"] = mod_config.hash_canonico({k: v for k, v in crudo.items() if k != "sha256"})
    return crudo


def escribir_config(dir_bot: Path, cambios: Optional[Callable[[dict], None]] = None) -> Path:
    crudo = json.loads((FIXTURES / "config_ejemplo.json").read_text(encoding="utf-8"))
    if cambios is not None:
        cambios(crudo)
    ruta = dir_bot / "config" / mod_config.NOMBRE_FICHERO_CONFIG
    ruta.write_text(json.dumps(firmar(crudo), ensure_ascii=False), encoding="utf-8")
    return ruta


def latir(dir_bot: Path, nombre: str, reloj: RelojSimulado, hace_s: float = 0.0) -> None:
    ruta = dir_bot / "estado" / sup_mod.nombre_latido(nombre)
    ruta.write_text(repr(float(reloj.epoch()) - hace_s), encoding="ascii")


def registros(dir_bot: Path, dia: date = date(2026, 9, 25)) -> list[dict]:
    ruta = dir_bot / "diario" / f"diario_supervisor_{dia.isoformat()}.jsonl"
    if not ruta.exists():
        return []
    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines() if linea.strip()]


def de_tipo(dir_bot: Path, tipo: str) -> list[dict]:
    return [r for r in registros(dir_bot) if r["tipo"] == tipo]


def argv_python(codigos: dict[str, str]) -> Callable[[str], list]:
    return lambda modulo: [sys.executable, "-c", codigos[modulo]]


def esperar_salida(proceso: Any, plazo_s: float = PLAZO_REAL_S) -> int:
    return proceso.wait(plazo_s)


class Montaje:
    """Construye supervisores con dobles por defecto y limpia TODOS sus procesos al final."""

    def __init__(self, dir_bot: Path, reloj: RelojSimulado) -> None:
        self.dir_bot = dir_bot
        self.reloj = reloj
        self.avisos = AvisosGrabados()
        self.supervisores: list[Supervisor] = []
        self.ruta_cfg = escribir_config(dir_bot)

    def __call__(self, **kw: Any) -> Supervisor:
        defectos: dict[str, Any] = dict(cuenta_das=CUENTA, hay_sesion=lambda d: True, media_sesion=lambda d: None,
                                        sonda_das=lambda: True, libre_gb=lambda: 100.0,
                                        argv_hijo=argv_python({"vigilante": HIJO_DORMIDO, "ejecutor": HIJO_DORMIDO}),
                                        espera_parada_s=0.3)
        if isinstance(kw.get("popen"), PopenEspia) and "argv_hijo" not in kw:
            defectos["argv_hijo"] = None                 # con Popen falso: la línea real (python -m app.bot_das.X)
        defectos.update(kw)
        das_exe = defectos.pop("das_exe", None)
        diario = Diario(self.dir_bot / "diario", self.reloj, "supervisor", VERSION, Fase.SOMBRA)
        s = Supervisor(self.ruta_cfg, self.reloj, self.avisos, sys.executable, BACKEND, das_exe,
                       self.dir_bot / "estado", diario, **defectos)
        self.supervisores.append(s)
        return s

    def limpiar(self) -> None:
        for s in self.supervisores:
            for h in s.hijos.values():
                p = h.proceso
                if p is not None and hasattr(p, "kill") and not isinstance(p, ProcesoFalso):
                    try:
                        p.kill()
                        p.wait(5)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            s.parar()


@pytest.fixture
def montar(dir_bot: Path, reloj: RelojSimulado):
    m = Montaje(dir_bot, reloj)
    try:
        yield m
    finally:
        m.limpiar()


def arrancar_con_vigilante_latiendo(m: Montaje, s: Supervisor) -> None:
    """arrancar → lanza vigilante → su latido → lanza ejecutor."""
    assert s.arrancar() == sup_mod.CODIGO_OK
    s.paso()
    latir(m.dir_bot, "vigilante", m.reloj)
    s.paso()
    assert s.hijo("ejecutor").corriendo


# ═══════════════════════════ 1. PlanRelanzamiento ════════════════════════
@pytest.mark.parametrize("n,esperada", [(1, 1.0), (2, 2.0), (3, 5.0), (4, 10.0), (5, 10.0), (9, 10.0)],
                         ids=[f"R-J-04v2-caida{i}" for i in (1, 2, 3, 4, 5, 9)])
def test_r_j_04_plan_1_2_5_10_y_luego_10(n: int, esperada: float) -> None:
    plan = PlanRelanzamiento()
    esperas = [plan.siguiente(1000.0 + i, 1000.0 + i) for i in range(n)]
    assert esperas[-1] == esperada
    assert plan.intentos == n


def test_r_j_04_plan_se_reinicia_tras_300_s_estable() -> None:
    plan = PlanRelanzamiento()
    assert [plan.siguiente(10.0, 9.0) for _ in range(4)] == [1.0, 2.0, 5.0, 10.0]
    assert plan.siguiente(310.0, 10.1) == 10.0                  # 299,9 s vivo: sigue en el tope
    assert plan.siguiente(700.0, 400.0) == 1.0                  # 300 s vivo: vuelve al principio
    assert plan.siguiente(701.0, 700.5) == 2.0
    plan.reiniciar()
    assert plan.siguiente(702.0) == 1.0 and plan.intentos == 1


@pytest.mark.parametrize("esperas,estable", [((), 300.0), ((1.0, -1.0), 300.0), ((float("nan"),), 300.0),
                                             ((True,), 300.0), ((1.0,), 0.0), ((1.0,), float("inf"))],
                         ids=["vacia", "negativa", "nan", "bool", "estable-0", "estable-inf"])
def test_plan_rechaza_valores_imposibles(esperas: tuple, estable: float) -> None:
    with pytest.raises(ValueError):
        PlanRelanzamiento(esperas, estable)


# ═══════════════════════════ 2. arranque DAS → vigilante → ejecutor ══════
def test_r_j_06_vigilante_primero_y_el_ejecutor_tras_su_latido(montar: Montaje) -> None:
    """§6.2.3: el vigilante sale primero; el ejecutor, cuando el vigilante late (latido escrito tras lanzarlo)."""
    popen = PopenEspia()
    s = montar(popen=popen)
    latir(montar.dir_bot, "vigilante", montar.reloj, hace_s=60.0)        # latido VIEJO de ayer: no cuenta
    assert s.arrancar() == 0
    s.paso()
    assert [p.argv[-1] for p in popen.procesos] == ["app.bot_das.vigilante"]
    assert s.hijo("vigilante").corriendo and not s.hijo("ejecutor").corriendo
    montar.reloj.avanzar(1.0)
    s.paso()
    assert not s.hijo("ejecutor").corriendo                              # el latido de ayer no vale
    latir(montar.dir_bot, "vigilante", montar.reloj)
    s.paso()
    assert s.hijo("ejecutor").corriendo and len(popen.procesos) == 2
    assert [r["datos"]["hijo"] for r in de_tipo(montar.dir_bot, "hijo_lanzado")] == ["vigilante", "ejecutor"]


def test_r_j_06_el_ejecutor_sale_a_los_10_s_aunque_el_vigilante_no_lata(montar: Montaje) -> None:
    popen = PopenEspia()
    s = montar(popen=popen)
    s.arrancar()
    s.paso()
    montar.reloj.avanzar(9.9)
    s.paso()
    assert not s.hijo("ejecutor").corriendo
    montar.reloj.avanzar(0.2)
    s.paso()
    assert s.hijo("ejecutor").corriendo


def test_lanzar_usa_python_m_app_bot_das_con_grupo_nuevo(montar: Montaje) -> None:
    """§3.27: [python, -m, app.bot_das.<modulo>], cwd=backend, CREATE_NEW_PROCESS_GROUP, entorno heredado."""
    popen = PopenEspia()
    s = montar(popen=popen, argv_hijo=None)
    s.lanzar("vigilante")
    argv, kw = popen.llamadas[-1]
    assert argv == [sys.executable, "-m", "app.bot_das.vigilante"]
    assert Path(kw["cwd"]) == BACKEND
    assert kw["creationflags"] == getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    assert "env" not in kw
    with pytest.raises(ValueError):
        s.lanzar("decisor")


# ═══════════════════════════ 3. muertos y colgados (procesos reales) ═════
def test_r_j_04_a_relanza_en_1_2_5_10_y_10_segundos(montar: Montaje) -> None:
    """R-J-04 a: un ejecutor que muere al arrancar se relanza tras 1, 2, 5, 10 y 10 s (hijos reales `python -c`)."""
    s = montar(argv_hijo=argv_python({"vigilante": HIJO_DORMIDO, "ejecutor": HIJO_MUERE}))
    arrancar_con_vigilante_latiendo(montar, s)
    ejecutor = s.hijo("ejecutor")
    vistas: list[float] = []
    for esperada in (1.0, 2.0, 5.0, 10.0, 10.0):
        assert esperar_salida(ejecutor.proceso) == 1
        latir(montar.dir_bot, "vigilante", montar.reloj)
        s.paso()                                                         # ve la muerte y programa
        assert not ejecutor.corriendo and ejecutor.ultimo_codigo == 1
        vistas.append(ejecutor.ultima_espera)
        lanzados = ejecutor.lanzamientos
        montar.reloj.avanzar(esperada - 0.05)
        latir(montar.dir_bot, "vigilante", montar.reloj)
        s.paso()
        assert ejecutor.lanzamientos == lanzados                         # aún no
        montar.reloj.avanzar(0.1)
        latir(montar.dir_bot, "vigilante", montar.reloj)
        s.paso()
        assert ejecutor.lanzamientos == lanzados + 1                     # ya
    assert vistas == [1.0, 2.0, 5.0, 10.0, 10.0]
    muertes = de_tipo(montar.dir_bot, "hijo_muerto")
    assert [r["datos"]["espera_s"] for r in muertes] == vistas and {r["datos"]["codigo"] for r in muertes} == {1}
    assert all("ejecutor ha muerto" in t for t in montar.avisos.de_nivel(Nivel.MAXIMO))
    assert not s.hijo("vigilante").lanzamientos > 1                      # el vigilante no se tocó


def test_r_j_04_a_tras_300_s_estable_la_espera_vuelve_a_1_s(montar: Montaje) -> None:
    s = montar(argv_hijo=argv_python({"vigilante": HIJO_DORMIDO, "ejecutor": HIJO_MUERE}))
    arrancar_con_vigilante_latiendo(montar, s)
    ejecutor = s.hijo("ejecutor")
    for _ in range(3):                                                   # 1, 2, 5 s
        esperar_salida(ejecutor.proceso)
        latir(montar.dir_bot, "vigilante", montar.reloj)
        s.paso()
        montar.reloj.avanzar(ejecutor.ultima_espera + 0.1)
        latir(montar.dir_bot, "vigilante", montar.reloj)
        s.paso()
    assert ejecutor.plan.intentos == 3
    esperar_salida(ejecutor.proceso)
    montar.reloj.avanzar(300.0)                                          # «vivió» 300 s antes de verse la caída
    latir(montar.dir_bot, "vigilante", montar.reloj)
    s.paso()
    assert ejecutor.ultima_espera == 1.0


@pytest.mark.parametrize("edad,colgado", [(3.0, False), (3.2, True)], ids=["R-J-04b-3s-justo", "R-J-04b-pasado-3s"])
def test_r_j_04_b_colgado_a_los_3_s_se_mata_y_se_relanza(montar: Montaje, edad: float, colgado: bool) -> None:
    """R-J-04 b: hijo REAL que deja de tocar el latido: a los 3 s justos sigue; pasado, terminate + relanzar en 1 s."""
    s = montar()
    arrancar_con_vigilante_latiendo(montar, s)
    ejecutor = s.hijo("ejecutor")
    proceso = ejecutor.proceso
    latir(montar.dir_bot, "ejecutor", montar.reloj)
    montar.reloj.avanzar(edad)
    latir(montar.dir_bot, "vigilante", montar.reloj)
    s.paso()
    if not colgado:
        assert ejecutor.proceso is proceso and proceso.poll() is None
        return
    assert ejecutor.proceso is None and proceso.poll() is not None      # muerto de verdad
    assert ejecutor.ultima_espera == 1.0
    assert de_tipo(montar.dir_bot, "hijo_colgado")[0]["datos"]["regla"] == "R-J-04 b"
    assert any("colgado" in t for t in montar.avisos.de_nivel(Nivel.MAXIMO))
    montar.reloj.avanzar(1.1)
    latir(montar.dir_bot, "vigilante", montar.reloj)
    s.paso()
    assert ejecutor.corriendo and ejecutor.lanzamientos == 2


def test_un_hijo_que_no_late_nunca_tras_lanzarse_se_da_por_colgado(montar: Montaje) -> None:
    popen = PopenEspia()
    s = montar(popen=popen, arranque_max_s=30.0)
    arrancar_con_vigilante_latiendo(montar, s)
    primero = s.hijo("ejecutor").proceso
    montar.reloj.avanzar(29.0)
    latir(montar.dir_bot, "vigilante", montar.reloj)
    s.paso()
    assert s.hijo("ejecutor").proceso is primero
    montar.reloj.avanzar(1.5)
    latir(montar.dir_bot, "vigilante", montar.reloj)
    s.paso()
    assert primero.terminado and "no ha latido" in de_tipo(montar.dir_bot, "hijo_colgado")[0]["datos"]["motivo"]


def test_codigo_0_sin_pedirlo_es_parada_a_mano_y_no_se_relanza_hasta_manana(montar: Montaje) -> None:
    s = montar(argv_hijo=argv_python({"vigilante": HIJO_DORMIDO, "ejecutor": HIJO_SALE_BIEN}))
    arrancar_con_vigilante_latiendo(montar, s)
    esperar_salida(s.hijo("ejecutor").proceso)
    s.paso()
    ejecutor = s.hijo("ejecutor")
    assert ejecutor.parado_a_mano and not ejecutor.corriendo
    montar.reloj.avanzar(60.0)
    latir(montar.dir_bot, "vigilante", montar.reloj)
    s.paso()
    assert ejecutor.lanzamientos == 1
    assert de_tipo(montar.dir_bot, "hijo_parado_a_mano") and any(
        "NO lo relanzo" in t for t in montar.avisos.de_nivel(Nivel.MAXIMO))


def test_un_fallo_dentro_de_la_vuelta_no_tumba_al_supervisor(montar: Montaje, tmp_path: Path) -> None:
    def revienta() -> bool:
        raise RuntimeError("tasklist roto")

    s = montar(popen=PopenEspia(), das_exe=tmp_path / "DASTrader.exe", das_vivo=revienta)
    s.arrancar()
    assert s.paso() == sup_mod.PERIODO_S
    assert de_tipo(montar.dir_bot, "excepcion")[0]["datos"]["donde"] == "supervisor.paso"
    assert s.codigo is None


# ═══════════════════════════ 4. ventana R-L-01 ═══════════════════════════
def _fin_1600(crudo: dict) -> None:
    crudo["estrategias"][0]["definition"]["custom_end_time"] = "16:00"


def _apagar_1200(crudo: dict) -> None:
    crudo["horario"]["apagar"] = "12:00"


def _encender_0700(crudo: dict) -> None:
    crudo["horario"]["encender"] = "07:00"


@pytest.mark.parametrize("cambios,media,esperado", [
    (None, None, ("03:55:00", "11:30:30")),
    (_apagar_1200, None, ("03:55:00", "12:00:00")),
    (_encender_0700, None, ("07:00:00", "11:30:30")),
    (_fin_1600, None, ("03:55:00", "16:00:30")),
    (_fin_1600, "viernes de Accion de Gracias", ("03:55:00", "13:00:30")),
    (None, "viernes de Accion de Gracias", ("03:55:00", "11:30:30")),
], ids=["R-L-01-ultimo-eod-mas-30s", "R-L-01-horario-apagar", "R-L-01-horario-encender",
        "R-L-01-eod-1600", "F10-media-sesion-recorta-a-1300", "F10-media-sesion-no-alarga"])
def test_r_l_01_ventana(montar: Montaje, dir_bot: Path, cambios: Any, media: Optional[str], esperado: tuple) -> None:
    montar.ruta_cfg = escribir_config(dir_bot, cambios)
    s = montar(media_sesion=lambda d: media)
    s.arrancar()
    inicio, fin = s.ventana(date(2026, 9, 25))
    assert (inicio.strftime("%H:%M:%S"), fin.strftime("%H:%M:%S")) == esperado
    assert inicio.tzinfo is not None and inicio.utcoffset() == datetime(2026, 9, 25, tzinfo=ET).utcoffset()


def test_r_l_01_sin_config_ventana_larga_y_no_lanza_hijos(montar: Montaje, dir_bot: Path) -> None:
    montar.ruta_cfg.write_text("{roto", encoding="utf-8")
    popen = PopenEspia()
    s = montar(popen=popen)
    s.arrancar()
    inicio, fin = s.ventana(date(2026, 9, 25))
    assert (inicio.strftime("%H:%M"), fin.strftime("%H:%M")) == ("03:55", "20:00")
    s.paso()
    assert popen.procesos == [] and s.cfg is None
    assert any("no hay config válida" in t for t in montar.avisos.de_nivel(Nivel.MAXIMO))


def test_r_l_01_la_config_invalida_usa_el_ultimo_bueno_sin_escribirlo(montar: Montaje, dir_bot: Path) -> None:
    ultimo = dir_bot / "config" / mod_config.NOMBRE_ULTIMO_BUENO
    ultimo.write_bytes(montar.ruta_cfg.read_bytes())
    montar.ruta_cfg.write_text("{roto", encoding="utf-8")
    antes = ultimo.stat().st_mtime_ns
    s = montar()
    s.arrancar()
    assert s.cfg is not None and ultimo.stat().st_mtime_ns == antes
    assert any("último bueno" in t for t in montar.avisos.de_nivel(Nivel.AVISO))


def test_r_l_01_festivo_sin_ventana_y_sin_hijos(montar: Montaje) -> None:
    popen = PopenEspia()
    s = montar(popen=popen, hay_sesion=lambda d: False)
    s.arrancar()
    assert s.ventana(date(2026, 9, 25)) == (None, None)
    assert s.paso() == sup_mod.ESPERA_FUERA_S
    assert popen.procesos == []


def test_r_l_01_calendario_real_accion_de_gracias_y_media_sesion(montar: Montaje, dir_bot: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Con `bot_alerts_calendario` real (sin red: se anula su refresco de Massive): festivo → (None, None);
    viernes siguiente = media sesión → el EOD de 16:00 se recorta a las 13:00 (+30 s); sábado → sin ventana."""
    from app.services import bot_alerts_calendario
    monkeypatch.setattr(bot_alerts_calendario, "_refrescar_al_fondo", lambda dia: None)
    montar.ruta_cfg = escribir_config(dir_bot, _fin_1600)
    s = montar(hay_sesion=None, media_sesion=None)
    s.arrancar()
    assert s.ventana(date(2026, 11, 26)) == (None, None)
    _, fin = s.ventana(date(2026, 11, 27))
    assert fin.strftime("%H:%M:%S") == "13:00:30"
    assert s.ventana(date(2026, 11, 28)) == (None, None)
    _, fin = s.ventana(date(2026, 11, 30))
    assert fin.strftime("%H:%M:%S") == "16:00:30"


def test_r_l_01_fin_de_semana_duerme_y_el_lunes_arranca_a_las_0355(montar: Montaje, dir_bot: Path) -> None:
    """§6.2.1: sin sesión duerme 30 s por vuelta; antes de encender, justo lo que falta; a las 03:55, vigilante."""
    popen = PopenEspia()
    montar.reloj.fijar(datetime(2026, 9, 26, 3, 0, tzinfo=ET))           # sábado 03:00 → sin sesión
    s = montar(popen=popen, hay_sesion=lambda d: d.weekday() < 5)
    s.arrancar()
    assert s.paso() == sup_mod.ESPERA_FUERA_S and popen.procesos == []
    montar.reloj.fijar(datetime(2026, 9, 28, 3, 54, 50, tzinfo=ET))      # lunes 03:54:50: faltan 10 s
    assert s.paso() == 10.0 and popen.procesos == []
    montar.reloj.avanzar(10.0)
    s.paso()
    assert [p.argv[-1] for p in popen.procesos] == ["app.bot_das.vigilante"]
    assert (dir_bot / "diario" / "diario_supervisor_2026-09-28.jsonl").exists()


# ═══════════════════════════ 5. doble instancia y main ═══════════════════
def test_r_j_04_c_doble_instancia_no_arranca_ni_toca_nada(montar: Montaje, dir_bot: Path) -> None:
    otro = CerrojoInstancia(dir_bot / "estado" / sup_mod.NOMBRE_CERROJO)
    assert otro.adquirir()
    try:
        popen = PopenEspia()
        s = montar(popen=popen)
        assert s.arrancar() == sup_mod.CODIGO_DOBLE_INSTANCIA
        assert s.correr() == sup_mod.CODIGO_DOBLE_INSTANCIA
        assert popen.llamadas == []
        assert registros(dir_bot) == []                                  # el diario es de la instancia viva
        assert montar.avisos.claves() == ["arranque:doble_instancia"]
        assert montar.avisos.avisos[0].nivel is Nivel.MAXIMO
        s.parar()
        assert otro.tomado
    finally:
        otro.soltar()


def test_main_con_otro_supervisor_devuelve_3_sin_leer_el_env_real(dir_bot: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sup_mod, "RUTA_DOTENV", dir_bot / "no_existe.env")
    escribir_config(dir_bot)
    otro = CerrojoInstancia(dir_bot / "estado" / sup_mod.NOMBRE_CERROJO)
    assert otro.adquirir()
    nombres = [n for n in ("SIGINT", "SIGBREAK", "SIGTERM") if hasattr(signal, n)]
    previos = {n: signal.getsignal(getattr(signal, n)) for n in nombres}
    try:
        assert sup_mod.main([]) == sup_mod.CODIGO_DOBLE_INSTANCIA
    finally:
        otro.soltar()
        for n, manejador in previos.items():                            # main instala sus manejadores: se restauran
            signal.signal(getattr(signal, n), manejador)
    logs = list((dir_bot / "logs").glob("bot_das_supervisor_*.log"))
    assert logs and "R-J-04 c" in logs[0].read_text(encoding="utf-8")


def test_el_constructor_rechaza_piezas_equivocadas(montar: Montaje) -> None:
    with pytest.raises(TypeError):
        montar(popen="no")
    with pytest.raises(ValueError):
        montar(periodo_s=0)
    with pytest.raises(ValueError):
        montar(colgado_s=float("nan"))
    with pytest.raises(ValueError):
        montar(esperas_relanzar=())
    s = montar()
    with pytest.raises(RuntimeError):
        s.paso()
    s.arrancar()
    with pytest.raises(RuntimeError):
        s.arrancar()


def test_importar_no_abre_red_ni_hilos_ni_carga_el_calendario() -> None:
    codigo = ("import sys, threading; sys.path.insert(0, sys.argv[1]); import app.bot_das.supervisor; "
              "import app.bot_das.herramientas.comprobar_das; "
              "print(int('pandas' in sys.modules), threading.active_count(), "
              "int('app.services.bot_alerts_calendario' in sys.modules), int('app.bot_das.ejecutor' in sys.modules), "
              "int('app.bot_das.vigilante' in sys.modules), int('websockets' in sys.modules))")
    salida = subprocess.run([sys.executable, "-c", codigo, str(BACKEND)], capture_output=True, text=True,
                            timeout=60, cwd=str(BACKEND))
    assert salida.returncode == 0, salida.stderr
    assert salida.stdout.split() == ["0", "1", "0", "0", "0", "0"]


# ═══════════════════════════ 6. peticiones (corrección 16) ═══════════════
def _peticion(dir_bot: Path, **cuerpo: Any) -> None:
    with open(dir_bot / "estado" / sup_mod.NOMBRE_ORDEN_SUPERVISOR, "a", encoding="utf-8") as f:
        f.write(json.dumps(cuerpo) + "\n")


def test_correccion16_lee_orden_supervisor_y_relanza_el_ejecutor(montar: Montaje, dir_bot: Path) -> None:
    _peticion(dir_bot, proceso="vigilante", peticion="relanzar ejecutor", relanzar="ejecutor")   # de antes: se ignora
    popen = PopenEspia()
    s = montar(popen=popen, gracia_peticion_s=15.0)
    arrancar_con_vigilante_latiendo(montar, s)
    primero = s.hijo("ejecutor").proceso
    _peticion(dir_bot, proceso="vigilante", peticion="relanzar ejecutor", relanzar="ejecutor")
    latir(dir_bot, "ejecutor", montar.reloj)
    s.paso()
    assert not primero.terminado                                         # recién lanzado: gracia
    assert de_tipo(dir_bot, "peticion_ignorada")[-1]["datos"]["motivo"] == "recién lanzado"
    montar.reloj.avanzar(16.0)
    latir(dir_bot, "vigilante", montar.reloj)
    latir(dir_bot, "ejecutor", montar.reloj)
    _peticion(dir_bot, proceso="supervisor", parar=True, para="ejecutor")        # la propia: se salta
    _peticion(dir_bot, proceso="vigilante", peticion="relanzar ejecutor", relanzar="ejecutor")
    with open(dir_bot / "estado" / sup_mod.NOMBRE_ORDEN_SUPERVISOR, "a", encoding="utf-8") as f:
        f.write('{"relanzar": "ejecutor", "proceso": "vigil')                   # a medio escribir: aún no
    s.paso()
    assert primero.terminado and s.hijo("ejecutor").ultima_espera == 1.0
    assert [r["datos"]["accion"] for r in de_tipo(dir_bot, "peticion_supervisor")] == ["relanzar"]
    assert any("pide relanzar el ejecutor" in t for t in montar.avisos.de_nivel(Nivel.MAXIMO))
    montar.reloj.avanzar(1.1)
    latir(dir_bot, "vigilante", montar.reloj)
    s.paso()
    assert len(popen.de("ejecutor")) == 2 and s.hijo("ejecutor").lanzamientos == 2


def test_correccion16_no_relanza_lo_que_paro_una_persona(montar: Montaje, dir_bot: Path) -> None:
    popen = PopenEspia()
    s = montar(popen=popen)
    arrancar_con_vigilante_latiendo(montar, s)
    s.hijo("ejecutor").proceso.salir(0)
    s.paso()
    _peticion(dir_bot, proceso="vigilante", peticion="relanzar ejecutor", relanzar="ejecutor")
    s.paso()
    assert s.hijo("ejecutor").lanzamientos == 1
    assert de_tipo(dir_bot, "peticion_ignorada")[-1]["datos"]["motivo"] == "parado a mano"


# ═══════════════════════════ 7. huérfanos (riesgo 26) ════════════════════
def _huerfano(dir_bot: Path, nombre: str) -> subprocess.Popen:
    ruta = dir_bot / "estado" / sup_mod.nombre_cerrojo(nombre)
    p = subprocess.Popen([sys.executable, "-c", HIJO_CON_CERROJO, str(BACKEND), str(ruta)], stdout=subprocess.PIPE,
                         text=True, cwd=str(BACKEND))
    assert p.stdout.readline().strip() == "listo"
    return p


def test_riesgo_26_huerfano_con_cerrojo_y_sin_latido_se_mata_por_su_pid(montar: Montaje, dir_bot: Path) -> None:
    p = _huerfano(dir_bot, "ejecutor")
    try:
        pid_interprete = CerrojoInstancia.pid_guardado(dir_bot / "estado" / sup_mod.nombre_cerrojo("ejecutor"))
        assert pid_interprete is not None and sup_mod.pid_vivo(pid_interprete)
        latir(dir_bot, "ejecutor", montar.reloj, hace_s=120.0)           # latido viejo
        s = montar(popen=PopenEspia())
        assert s.arrancar() == 0
        assert p.wait(PLAZO_REAL_S) is not None
        assert not sup_mod.pid_vivo(pid_interprete)
        assert de_tipo(dir_bot, "huerfano_matado")[0]["datos"]["pid"] == pid_interprete
        assert not sup_mod.cerrojo_tomado_por_otro(dir_bot / "estado" / sup_mod.nombre_cerrojo("ejecutor"))
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(5)


def test_riesgo_26_huerfano_que_late_se_adopta_y_se_vigila(montar: Montaje, dir_bot: Path) -> None:
    p = _huerfano(dir_bot, "ejecutor")
    try:
        latir(dir_bot, "ejecutor", montar.reloj, hace_s=0.5)
        latir(dir_bot, "vigilante", montar.reloj)
        popen = PopenEspia()
        s = montar(popen=popen)
        s.arrancar()
        ejecutor = s.hijo("ejecutor")
        assert ejecutor.adoptado and p.poll() is None
        assert ejecutor.pid == CerrojoInstancia.pid_guardado(dir_bot / "estado" / sup_mod.nombre_cerrojo("ejecutor"))
        s.paso()
        assert popen.de("ejecutor") == [] and s.hijo("vigilante").corriendo      # no se duplica el ejecutor
        p.kill()
        p.wait(PLAZO_REAL_S)
        limite = time.monotonic() + PLAZO_REAL_S
        while sup_mod.pid_vivo(ejecutor.pid) and time.monotonic() < limite:
            time.sleep(0.05)
        latir(dir_bot, "vigilante", montar.reloj)
        s.paso()
        assert not ejecutor.adoptado and ejecutor.ultima_espera == 1.0 and ejecutor.ultimo_codigo is None
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(5)


def test_pid_vivo_pregunta_sin_matar() -> None:
    """Trampa: en Windows `os.kill(pid, 0)` MATA el proceso; `pid_vivo` no."""
    p = subprocess.Popen([sys.executable, "-c", HIJO_DORMIDO])
    try:
        assert sup_mod.pid_vivo(p.pid) and sup_mod.pid_vivo(p.pid)
        assert p.poll() is None
        assert not sup_mod.pid_vivo(0) and not sup_mod.pid_vivo(-5) and not sup_mod.matar_pid(0)
    finally:
        p.kill()
        p.wait(5)
    assert p.poll() is not None and not sup_mod.pid_vivo(p.pid)


# ═══════════════════════════ 8. DAS (EP-7) ═══════════════════════════════
def test_ep7_sin_das_exe_no_lanza_nada_ni_pregunta_a_tasklist(montar: Montaje) -> None:
    popen = PopenEspia()
    preguntas: list[int] = []
    s = montar(popen=popen, das_vivo=lambda: preguntas.append(1) or False)
    s.arrancar()
    s.paso()
    assert preguntas == []
    assert [argv[-1] for argv, _ in popen.llamadas] == ["app.bot_das.vigilante"]    # solo el vigilante, sin DAS


def test_ep7_das_cerrado_con_das_exe_se_abre_y_avisa_login_2fa(montar: Montaje, tmp_path: Path) -> None:
    exe = tmp_path / "DAS" / "DASTrader.exe"
    popen = PopenEspia()
    respuestas = iter([False, True, True, True])
    s = montar(popen=popen, das_exe=exe, das_vivo=lambda: next(respuestas), sonda_das=lambda: False)
    s.arrancar()
    s.paso()
    argv, kw = popen.llamadas[0]
    assert argv == [str(exe)] and Path(kw["cwd"]) == exe.parent
    assert any("LOGIN/2FA A MANO" in t for t in montar.avisos.de_nivel(Nivel.MAXIMO))
    assert len(popen.llamadas) == 1                                      # sin API: ni vigilante ni ejecutor
    assert de_tipo(montar.dir_bot, "das_lanzado") and de_tipo(montar.dir_bot, "das_sin_api")


def test_das_sin_api_no_arranca_hijos_y_avisa_cada_5_min(montar: Montaje) -> None:
    popen = PopenEspia()
    estado = {"acepta": False}
    s = montar(popen=popen, sonda_das=lambda: estado["acepta"])
    s.arrancar()
    s.paso()
    montar.reloj.avanzar(60.0)
    s.paso()
    assert popen.llamadas == [] and len([c for c in montar.avisos.claves() if c == "das_sin_api"]) == 1
    montar.reloj.avanzar(240.0)
    s.paso()
    assert len([c for c in montar.avisos.claves() if c == "das_sin_api"]) == 2
    estado["acepta"] = True
    montar.reloj.avanzar(5.0)
    s.paso()
    assert s.das_listo_hoy and s.hijo("vigilante").corriendo
    assert "das_listo" in montar.avisos.claves()


def test_sonda_sin_puerto_no_bloquea(montar: Montaje) -> None:
    s = montar(popen=PopenEspia(), sonda_das=lambda: None)
    s.arrancar()
    s.paso()
    assert s.das_listo_hoy and s.hijo("vigilante").corriendo
    assert sup_mod.sonda_puerto_das() is None                            # sin DAS_API_PORT en el entorno


# ═══════════════════════════ 9. apagado (R-L-01, L4) ═════════════════════
def test_r_l_01_fuera_de_ventana_ordena_parar_espera_y_termina(montar: Montaje, dir_bot: Path) -> None:
    """§6.2.5 con hijos REALES que no obedecen: {"parar": true} por hijo (ejecutor primero), espera y terminate."""
    s = montar(espera_parada_s=0.3)
    arrancar_con_vigilante_latiendo(montar, s)
    procesos = {n: s.hijo(n).proceso for n in sup_mod.HIJOS}
    montar.reloj.fijar(datetime(2026, 9, 25, 11, 31, tzinfo=ET))
    s.paso()
    assert all(p.poll() is not None for p in procesos.values())
    ordenes = [json.loads(linea) for linea in s.ruta_orden_supervisor.read_text(encoding="utf-8").splitlines()]
    assert [(o["parar"], o["para"], o["proceso"]) for o in ordenes] == [(True, "ejecutor", "supervisor"),
                                                                        (True, "vigilante", "supervisor")]
    assert [r["datos"]["hijo"] for r in de_tipo(dir_bot, "hijo_parado")] == ["ejecutor", "vigilante"]
    assert de_tipo(dir_bot, "apagado") and not de_tipo(dir_bot, "hijo_muerto")
    montar.reloj.avanzar(60.0)
    assert s.paso() == sup_mod.ESPERA_FUERA_S
    assert all(s.hijo(n).lanzamientos == 1 for n in sup_mod.HIJOS)


def test_r_l_01_el_hijo_que_obedece_el_parar_no_se_termina(montar: Montaje, dir_bot: Path) -> None:
    popen = PopenEspia(ruta_orden=dir_bot / "estado" / sup_mod.NOMBRE_ORDEN_SUPERVISOR)
    s = montar(popen=popen, espera_parada_s=2.0)
    arrancar_con_vigilante_latiendo(montar, s)
    montar.reloj.fijar(datetime(2026, 9, 25, 12, 0, tzinfo=ET))
    s.paso()
    assert not any(p.terminado for p in popen.procesos) and all(p.codigo == 0 for p in popen.procesos)
    assert not de_tipo(dir_bot, "hijo_terminado") and not any(h.parado_a_mano for h in s.hijos.values())


@pytest.mark.parametrize("foto,apaga", [
    ({"posiciones": {"XYZ": {"neta_fills": -100, "neta_das": -100, "intento": None}}}, False),
    ({"posiciones": {"XYZ": {"neta_fills": 0, "neta_das": None, "intento": {"fase": "agregando"}}}}, False),
    ({"posiciones": {"XYZ": {"neta_fills": 0, "neta_das": 0, "intento": None}}}, True),
    ({"posiciones": {}}, True),
    ("{roto", False),
    (None, True),
    ({"posiciones": {}, "ordenes": [{"token": 1, "ticker": "XYZ", "estado": "Accepted"}]}, False),
    ({"posiciones": {}, "ordenes": "raro"}, False),
    ({"posiciones": {}, "ordenes": []}, True),
], ids=["L4-corto-vivo", "L4-intento-vivo", "posicion-cerrada", "sin-posiciones", "foto-ilegible", "sin-foto",
        "G2-04-orden-viva-sin-posicion", "G2-04-ordenes-ilegibles", "G2-04-sin-ordenes-vivas"])
def test_l4_con_posicion_a_la_hora_de_apagar_avisa_3_y_no_apaga(montar: Montaje, dir_bot: Path, foto: Any,
                                                                  apaga: bool) -> None:
    popen = PopenEspia()
    s = montar(popen=popen)
    arrancar_con_vigilante_latiendo(montar, s)
    if foto is not None:
        s.ruta_foto.write_text(foto if isinstance(foto, str) else json.dumps(foto), encoding="utf-8")
    montar.reloj.fijar(datetime(2026, 9, 25, 11, 45, tzinfo=ET))
    for nombre in sup_mod.HIJOS:          # G2-01: fuera de la ventana con posición se siguen vigilando los colgados
        latir(montar.dir_bot, nombre, montar.reloj)
    s.paso()
    s.paso()
    assert all(p.terminado or p.codigo is not None for p in popen.procesos) is apaga
    avisos_l4 = [c for c in montar.avisos.claves() if c == "apagado_con_posicion"]
    assert len(avisos_l4) == (0 if apaga else 1)
    if not apaga:
        s.ruta_foto.write_text(json.dumps({"posiciones": {}}), encoding="utf-8")
        s.paso()
        assert all(p.terminado for p in popen.procesos)


def test_g2_01_fuera_de_ventana_con_posicion_relanza_al_muerto_y_mata_al_colgado(montar: Montaje) -> None:
    """G2-01 (L4 / R-D-02): pasada la ventana con un corto vivo, un ejecutor que sale con 1 se RELANZA a 1 s (el aviso
    dice la verdad) y uno que deja de latir se mata y se relanza; al cerrarse la posición, apagado ordenado."""
    popen = PopenEspia()
    s = montar(popen=popen)
    arrancar_con_vigilante_latiendo(montar, s)
    s.ruta_foto.write_text(json.dumps({"posiciones": {"XYZ": {"neta_fills": -100, "neta_das": -100, "intento": None}},
                                       "ordenes": []}), encoding="utf-8")
    montar.reloj.fijar(datetime(2026, 9, 25, 11, 45, tzinfo=ET))
    for nombre in sup_mod.HIJOS:
        latir(montar.dir_bot, nombre, montar.reloj)
    s.paso()
    ejecutor = s.hijo("ejecutor")
    ejecutor.proceso.salir(1)
    s.paso()
    assert not ejecutor.corriendo and ejecutor.ultima_espera == 1.0
    montar.reloj.avanzar(1.1)
    latir(montar.dir_bot, "vigilante", montar.reloj)
    s.paso()
    assert ejecutor.corriendo and ejecutor.lanzamientos == 2                         # relanzado fuera de la ventana
    latir(montar.dir_bot, "ejecutor", montar.reloj)
    montar.reloj.avanzar(3.5)                                                          # deja de latir: colgado
    latir(montar.dir_bot, "vigilante", montar.reloj)
    colgado = ejecutor.proceso
    s.paso()
    assert colgado.terminado and [r["datos"]["hijo"] for r in de_tipo(montar.dir_bot, "hijo_colgado")] == ["ejecutor"]
    assert len([c for c in montar.avisos.claves() if c == "apagado_con_posicion"]) == 1
    s.ruta_foto.write_text(json.dumps({"posiciones": {}, "ordenes": []}), encoding="utf-8")
    montar.reloj.avanzar(1.1)
    s.paso()
    assert not any(h.corriendo for h in s.hijos.values()) and de_tipo(montar.dir_bot, "apagado")


def test_g2_01_sin_bot_en_marcha_una_foto_vieja_no_lanza_nada_fuera_de_ventana(montar: Montaje) -> None:
    """G2-01: la prórroga es para el bot que YA estaba en marcha; una foto vieja con posición no arranca hijos de noche."""
    popen = PopenEspia()
    s = montar(popen=popen)
    s.arrancar()
    s.ruta_foto.write_text(json.dumps({"posiciones": {"XYZ": {"neta_fills": -100, "neta_das": -100}}}),
                           encoding="utf-8")
    montar.reloj.fijar(datetime(2026, 9, 25, 21, 0, tzinfo=ET))
    s.paso()
    assert popen.llamadas == []


def test_g2_03_das_que_se_cierra_a_media_sesion_se_relanza_y_se_avisa_cada_5_min(montar: Montaje,
                                                                              tmp_path: Path) -> None:
    """G2-03 (R-J-02 (2), EP-7): con DAS ya listo, si su proceso desaparece el supervisor lo nota en ≤ 30 s, lo abre y
    avisa 3 «LOGIN/2FA a mano»; mientras su API no responda, repite el aviso cada 5 min; al volver, aviso 1."""
    exe = tmp_path / "DAS" / "DASTrader.exe"
    popen = PopenEspia()
    estado = {"vivo": True, "api": True}
    s = montar(popen=popen, das_exe=exe, das_vivo=lambda: estado["vivo"], sonda_das=lambda: estado["api"])
    arrancar_con_vigilante_latiendo(montar, s)
    assert s.das_listo_hoy and not [a for a, _ in popen.llamadas if a == [str(exe)]]
    estado["vivo"], estado["api"] = False, False
    for _ in range(3):
        montar.reloj.avanzar(10.0)
        for nombre in sup_mod.HIJOS:
            latir(montar.dir_bot, nombre, montar.reloj)
        s.paso()
    lanzados_das = [a for a, _ in popen.llamadas if a == [str(exe)]]
    assert len(lanzados_das) == 1 and de_tipo(montar.dir_bot, "das_caido")
    assert any("LOGIN/2FA A MANO" in t for t in montar.avisos.de_nivel(Nivel.MAXIMO))
    estado["vivo"] = True                                   # el proceso vuelve, pero sin LOGIN
    avisos_api = lambda: len([c for c in montar.avisos.claves() if c == "das_sin_api"])   # noqa: E731
    montar.reloj.avanzar(30.0)
    for nombre in sup_mod.HIJOS:
        latir(montar.dir_bot, nombre, montar.reloj)
    s.paso()
    assert avisos_api() == 1
    montar.reloj.avanzar(120.0)
    for nombre in sup_mod.HIJOS:
        latir(montar.dir_bot, nombre, montar.reloj)
    s.paso()
    assert avisos_api() == 1                                 # como mucho cada 5 min
    montar.reloj.avanzar(200.0)
    for nombre in sup_mod.HIJOS:
        latir(montar.dir_bot, nombre, montar.reloj)
    s.paso()
    assert avisos_api() == 2
    estado["api"] = True
    montar.reloj.avanzar(30.0)
    for nombre in sup_mod.HIJOS:
        latir(montar.dir_bot, nombre, montar.reloj)
    s.paso()
    assert "das_listo" in montar.avisos.claves()
    assert len([a for a, _ in popen.llamadas if a == [str(exe)]]) == 1


@pytest.mark.parametrize("codigo", [4, 5], ids=["G2-08-motor-distinto", "G2-08-config-imposible"])
def test_g2_08_codigos_que_relanzar_no_arregla_quedan_a_control_humano(montar: Montaje, codigo: int) -> None:
    """G2-08: un ejecutor que sale con 4 (motor distinto) o 5 (config/entorno) NO se relanza cada 10 s: control humano
    con aviso 3; si el fichero del cuadro cambia, se reintenta UNA vez."""
    popen = PopenEspia()
    s = montar(popen=popen)
    arrancar_con_vigilante_latiendo(montar, s)
    ejecutor = s.hijo("ejecutor")
    ejecutor.proceso.salir(codigo)
    s.paso()
    assert ejecutor.parado_a_mano and ejecutor.parado_por_codigo == codigo
    for _ in range(3):
        montar.reloj.avanzar(10.0)
        latir(montar.dir_bot, "vigilante", montar.reloj)
        s.paso()
    assert ejecutor.lanzamientos == 1
    assert de_tipo(montar.dir_bot, "hijo_no_relanzable") and \
        len([c for c in montar.avisos.claves() if c == "hijo_no_relanzable:ejecutor"]) == 1
    escribir_config(montar.dir_bot, lambda crudo: crudo.update({"config_version": crudo["config_version"] + 1}))
    latir(montar.dir_bot, "vigilante", montar.reloj)
    s.paso()
    assert ejecutor.lanzamientos == 2 and de_tipo(montar.dir_bot, "hijo_reintento_config")


def test_g2_08_el_reloj_desviado_se_relanza_por_plan_y_a_la_tercera_queda_a_mano(montar: Montaje) -> None:
    """G2-08: el código 2 (reloj, R-J-07) se relanza por plan (puede ser un SNTP puntual) y, tras 3 seguidos, control
    humano; el 1 y el 3 siguen el plan sin límite."""
    popen = PopenEspia()
    s = montar(popen=popen)
    arrancar_con_vigilante_latiendo(montar, s)
    ejecutor = s.hijo("ejecutor")
    for n in range(1, 4):
        ejecutor.proceso.salir(2)
        latir(montar.dir_bot, "vigilante", montar.reloj)
        s.paso()
        if n < 3:
            assert not ejecutor.parado_a_mano
            montar.reloj.avanzar(ejecutor.ultima_espera + 0.1)
            latir(montar.dir_bot, "vigilante", montar.reloj)
            s.paso()
            assert ejecutor.corriendo
    assert ejecutor.parado_a_mano and ejecutor.parado_por_codigo == 2 and ejecutor.lanzamientos == 3


# ═══════════════════════════ 10. disco (R-J-07) ══════════════════════════
def test_r_j_07_disco_bajo_avisa_2_como_mucho_cada_hora(montar: Montaje) -> None:
    libre = {"gb": 4.2}
    s = montar(popen=PopenEspia(), libre_gb=lambda: libre["gb"])
    s.arrancar()
    s.paso()
    assert de_tipo(montar.dir_bot, "disco")[0]["datos"] == {"libre_gb": 4.2, "minimo_gb": 5.0, "regla": "R-J-07"}
    assert any("4.2 GB" in t for t in montar.avisos.de_nivel(Nivel.AVISO))
    montar.reloj.avanzar(120.0)
    s.paso()
    assert len(de_tipo(montar.dir_bot, "disco")) == 1
    montar.reloj.avanzar(3600.0)
    latir(montar.dir_bot, "vigilante", montar.reloj)
    s.paso()
    assert len(de_tipo(montar.dir_bot, "disco")) == 2
    libre["gb"] = 50.0
    montar.reloj.avanzar(3600.0)
    s.paso()
    assert len(de_tipo(montar.dir_bot, "disco")) == 2


def test_dia_nuevo_abre_el_diario_del_dia_y_perdona_la_parada_a_mano(montar: Montaje, dir_bot: Path) -> None:
    popen = PopenEspia()
    s = montar(popen=popen)
    arrancar_con_vigilante_latiendo(montar, s)
    s.hijo("ejecutor").proceso.salir(0)
    s.paso()
    assert s.hijo("ejecutor").parado_a_mano
    montar.reloj.fijar(datetime(2026, 9, 28, 4, 0, tzinfo=ET))
    s.paso()
    assert not s.hijo("ejecutor").parado_a_mano
    assert (dir_bot / "diario" / "diario_supervisor_2026-09-28.jsonl").exists()


# ═══════════════════════════ 11. comprobar_das: SOLO --ayuda ═════════════
def test_comprobar_das_ayuda_lista_los_10_pasos_sin_tocar_nada(dir_bot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§3.27: `--ayuda` imprime los 10 pasos (3-6 y el 10 de A-02 marcados CANARIO) y sale con 0 sin leer el entorno,
    sin red y sin escribir nada. La herramienta NUNCA se ejecuta de verdad en los tests (va contra DAS real)."""
    from app.bot_das.herramientas import comprobar_das as cd

    def prohibido(*a: Any, **k: Any) -> Any:
        raise AssertionError("--ayuda no puede construir un cliente de DAS")

    monkeypatch.setattr(cd.ClienteDAS, "desde_env", staticmethod(prohibido))
    salida: list[str] = []
    antes = sorted(p for p in dir_bot.rglob("*"))
    assert cd.main(["--ayuda"], consola=cd.Consola(entrada=prohibido, salida=salida.append)) == cd.CODIGO_OK
    texto = "\n".join(salida)
    for paso in cd.PASOS:
        assert f"  {paso.numero}. {paso.titulo}" in texto
    assert [p.numero for p in cd.PASOS] == list(range(1, 11))
    assert [p.numero for p in cd.PASOS if p.canario] == [3, 4, 5, 6, 10]
    assert texto.count("[CANARIO]") == 5 and "BOT_DAS_PERMITIR_ORDENES=1" in texto
    assert sorted(p for p in dir_bot.rglob("*")) == antes


@pytest.mark.parametrize("texto,esperado", [(None, list(range(1, 11))), ("1, 9", [1, 9]), ("3", [3]), ("10", [10])],
                         ids=["todos", "lista", "uno", "A-02-paso-10"])
def test_comprobar_das_lista_de_pasos(texto: Optional[str], esperado: list[int]) -> None:
    from app.bot_das.herramientas import comprobar_das as cd
    assert cd._pasos_de(texto) == esperado


@pytest.mark.parametrize("texto", ["0", "11", "uno", "1,,2"], ids=["cero", "once", "texto", "vacio"])
def test_comprobar_das_pasos_mal_escritos_salen_con_5_sin_red(texto: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.bot_das.herramientas import comprobar_das as cd
    monkeypatch.setattr(cd.ClienteDAS, "desde_env", staticmethod(lambda *a, **k: pytest.fail("sin red")))
    salida: list[str] = []
    assert cd.main(["--pasos", texto], consola=cd.Consola(salida=salida.append)) == cd.CODIGO_ENTORNO
    assert "paso desconocido" in salida[0]


# ═══════════════════════════ 12. comprobar_das: la lógica de los pasos con un DAS simulado ═══
TICKER_CD = "ABCD"
CUENTA_CD = "CUENTA_PRUEBA"


class ClienteEmparejado:
    """Un «DAS» en memoria para el `Comprobador`: cada línea va al `Emparejador` y lo que contesta, parseado, a la
    cola. `SB` devuelve la cotización del libro. `tragar` = cuántas respuestas se pierden (eco tardío, G2-07)."""

    def __init__(self, emparejador: Any, libro: Any, cola: Any) -> None:
        from app.bot_das.protocolo import Parser
        self.emp = emparejador
        self.libro = libro
        self.cola = cola
        self.parser = Parser(lambda t: True, watch=False, cuenta=CUENTA_CD)
        self.enviadas: list[str] = []
        self.tragar = 0

    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> bool:
        self.enviadas.append(linea)
        palabras = linea.split()
        if palabras[0].upper() in ("SB", "UNSB"):
            crudas = [] if palabras[0].upper() == "UNSB" else list(self.libro.cotizar(
                palabras[1], self._cot["bid"], self._cot["ask"], last=self._cot["ask"]))
        else:
            crudas = self.emp.recibir(linea)
        if self.tragar > 0:
            self.tragar -= 1
            return True
        for cruda in crudas:
            self.cola.put(self.parser.parsear(cruda))
        return True

    def cotizar(self, bid: str, ask: str) -> None:
        from decimal import Decimal as Dec
        self._cot = {"bid": Dec(bid), "ask": Dec(ask)}
        self.libro.cotizar(TICKER_CD, Dec(bid), Dec(ask), last=Dec(ask))


def _respuestas(precio: str = "") -> Callable[[str], str]:
    def responder(pregunta: str) -> str:
        if "Escribe SI" in pregunta:
            return "SI"
        if "[s/N]" in pregunta:
            return "s"
        if "Ticker" in pregunta:
            return TICKER_CD
        if "Precio" in pregunta:
            return precio
        return ""
    return responder


def _comprobador(dir_bot: Path, reloj_das: RelojSimulado, reloj: RelojSimulado, share_es_abierta: bool = True,
                 precio: str = "") -> tuple[Any, ClienteEmparejado, Any, list[str]]:
    import queue
    from app.bot_das.herramientas import comprobar_das as cd
    from app.bot_das.simulador_das import Emparejador, LibroSimulado
    libro = LibroSimulado(cuenta=CUENTA_CD)
    emp = Emparejador(libro, reloj_das, replace_share_es_abierta=share_es_abierta)
    cola: "queue.Queue[Any]" = queue.Queue()
    cliente = ClienteEmparejado(emp, libro, cola)
    cliente.cotizar("2.45", "2.47")
    salida: list[str] = []
    diario = Diario(dir_bot / "diario", reloj, "supervisor", VERSION, Fase.CANARIO)
    diario.abrir_dia(reloj.hoy())
    comprobador = cd.Comprobador(cliente, cola, reloj, diario, dir_bot / "informes" / "prueba.txt",
                                 cd.Consola(entrada=_respuestas(precio), salida=salida.append), True,
                                 {"stop": "STOP", "agregar": {"ge_1": "SAGEREB"}, "cruzar": {"ge_1": "SAGEPRO"}},
                                 lambda texto: texto, lambda **kw: pytest.fail("sin segunda conexión"))
    return comprobador, cliente, libro, salida


def _conclusiones(dir_bot: Path, paso: int) -> list[str]:
    return [r["datos"]["conclusion"] for r in de_tipo(dir_bot, "comprobacion_das") if r["datos"]["paso"] == paso]


@pytest.mark.parametrize("share_es_abierta, propuesta", [(True, "replace_share_es_abierta = true"),
                                                         (False, "replace_share_es_abierta = false")],
                         ids=["A-02-DAS-abierta", "A-02-DAS-total"])
def test_a_02_d2a_08_paso_10_mide_el_share_de_un_replace_parcial_y_vende_lo_comprado(
        dir_bot: Path, reloj: RelojSimulado, monkeypatch: pytest.MonkeyPatch, share_es_abierta: bool,
        propuesta: str) -> None:
    """A-02 / D2a-08 (director): el paso canario 10 compra 2 que quedan parciales (1 llena), hace REPLACE id 2 y lee
    lvqty/qty: propone el interruptor que corresponde en cada lectura de DAS; después VENDE solo la 1 comprada."""
    from decimal import Decimal as Dec
    from app.bot_das.herramientas import comprobar_das as cd
    monkeypatch.setattr(cd, "ESPERA_RESPUESTA_S", 0.01)
    comprobador, cliente, libro, _ = _comprobador(dir_bot, reloj, reloj, share_es_abierta, precio="2.47")
    libro.llenar_parcial(Dec("0.5"), ticker=TICKER_CD)
    assert comprobador.ejecutar([10]) == cd.CODIGO_OK
    conclusion = _conclusiones(dir_bot, 10)[0]
    assert propuesta in conclusion and "vendidas las 1 compradas" in conclusion
    assert libro.posiciones().get(TICKER_CD) == 0                       # la cuenta no queda larga
    assert [x for x in cliente.enviadas if x.startswith("REPLACE")] and \
        [x for x in cliente.enviadas if x.split()[:3][-1:] == ["S"]]


def test_g2_07_una_orden_canario_con_eco_tardio_se_cancela_al_terminar_el_paso(dir_bot: Path, reloj: RelojSimulado,
                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """G2-07 (riesgo 11): el %ORDER del STOPLMTP del paso 3 no llega (ni tras el primer GET ORDERS): el paso lo registra
    «sin %ORDER», pero el barrido de GET ORDERS al terminar el paso la encuentra (token canario) y la CANCELA."""
    from app.bot_das.herramientas import comprobar_das as cd
    monkeypatch.setattr(cd, "ESPERA_RESPUESTA_S", 0.01)
    comprobador, cliente, libro, _ = _comprobador(dir_bot, reloj, reloj)
    cliente.tragar = 0

    original = cliente.enviar

    def enviar_con_eco_tardio(linea: str, serie: Optional[str] = None, version: int = 0) -> bool:
        if linea.startswith("NEWORDER"):
            cliente.tragar = 2                                     # el eco del NEWORDER y el del GET ORDERS siguiente
        return original(linea, serie, version)

    cliente.enviar = enviar_con_eco_tardio
    comprobador.ejecutar([3])
    assert "sin %ORDER" in _conclusiones(dir_bot, 3)[0]
    stop = [o for o in libro.ordenes() if o["tipo"] == "STOPLMTP"]
    assert len(stop) == 1 and stop[0]["estado"] == "Canceled"
    assert f"CANCEL {stop[0]['id']}" in cliente.enviadas
    assert any("G2-07" in c for c in _conclusiones(dir_bot, 3))


def test_l0_05_d2a_10_paso_3_compara_la_hora_de_das_con_et_y_aborta_si_no_casa(dir_bot: Path, reloj: RelojSimulado,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """L0-05 (riesgo 13): la hora del %ORDER del paso 3 se compara con ET; si DAS pinta en otra zona (6 h) se ABORTA
    (el paso 4 no se hace) y el stop canario se cancela al salir. D2a-10: se dice si el precio del %ORDER es el disparo
    o el límite."""
    from app.bot_das.herramientas import comprobar_das as cd
    monkeypatch.setattr(cd, "ESPERA_RESPUESTA_S", 0.01)
    reloj_das = RelojSimulado(datetime(2026, 9, 25, 15, 30, tzinfo=ET))          # DAS en hora de Madrid
    comprobador, cliente, libro, _ = _comprobador(dir_bot, reloj_das, reloj)
    comprobador.ejecutar([3, 4])
    paso3 = _conclusiones(dir_bot, 3)[0]
    assert "ABORTO" in paso3 and "L0-05" in paso3
    assert "DISPARO" in paso3 or "LÍMITE" in paso3 or "ni el disparo" in paso3
    assert "ABORTADA" in _conclusiones(dir_bot, 4)[0]
    assert not [x for x in cliente.enviadas if x.startswith("REPLACE")]
    assert all(o["estado"] == "Canceled" for o in libro.ordenes() if o["tipo"] == "STOPLMTP")


def test_l0_05_con_das_en_et_no_aborta(dir_bot: Path, reloj: RelojSimulado, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.bot_das.herramientas import comprobar_das as cd
    monkeypatch.setattr(cd, "ESPERA_RESPUESTA_S", 0.01)
    comprobador, cliente, libro, _ = _comprobador(dir_bot, reloj, reloj)
    comprobador.ejecutar([3, 4])
    assert "= ET" in _conclusiones(dir_bot, 3)[0] and "ABORT" not in _conclusiones(dir_bot, 4)[0]
    assert [x for x in cliente.enviadas if x.startswith("REPLACE")]
