"""Guard del fix fork->forkserver del grid 3D de optimizacion.

El pool del grid 3D forkeaba con `fork` clasico desde el proceso multi-hilo de
la app (hilo SSL del live_screener vivo) -> segfault -> BrokenProcessPool, que
se veia como el error crudo O como una superficie plana en 0.0000 (todos los
puntos a NaN en silencio). El fix migra a `forkserver` (workers desde un
servidor limpio de un solo hilo) pasando el ctx por initializer/initargs, con
red de seguridad secuencial y escape hatch OPT_PARALLEL_WORKERS.

La equivalencia forkserver==secuencial bit-a-bit y la superficie no-plana se
validan en contenedor Linux (Windows/CI solo tienen 'spawn'); aqui se guardan
los contratos que SI son platform-agnostic para que no regresen.
"""
import multiprocessing

from app.services import optimization_service as opt


def test_init_grid_ctx_sets_global():
    """Bajo forkserver el worker NO hereda _GRID_CTX por COW: el initializer
    debe fijarlo desde el ctx pickled que llega por initargs."""
    sentinel = {"grid_points": [(1,)], "is_risk_only": True, "marker": "xyz"}
    opt._GRID_CTX.clear()
    opt._init_grid_ctx(sentinel)
    try:
        assert opt._GRID_CTX is sentinel
        assert opt._GRID_CTX.get("marker") == "xyz"
    finally:
        opt._GRID_CTX.clear()


def test_forkserver_available_on_this_platform_when_fork_is():
    """Donde hay `fork` (Linux/prod) tambien hay `forkserver`: la seleccion de
    start-method del grid prefiere forkserver, que es el que evita el segfault.
    En plataformas solo-spawn (Windows) el grid cae a secuencial y este chequeo
    no aplica."""
    methods = multiprocessing.get_all_start_methods()
    if "fork" in methods:
        assert "forkserver" in methods, (
            "fork sin forkserver: el grid usaria fork clasico (vulnerable al "
            "segfault de fork-en-proceso-multihilo)"
        )
