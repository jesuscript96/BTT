"""La ventana de entrada se comprueba TAMBIEN en la vela de RELLENO.

EL BUG (2026-09-06, medido sobre una corrida real de 2.688 trades). La mascara
de `entry_time_windows` se aplicaba a la vela de la SENAL, pero con
`look_ahead_prevention` el simulador compra en la apertura de la vela SIGUIENTE
(`eff_entry_idx = i + 1`, portfolio_sim). En un ticker liquido eso es un minuto
de desfase. En los warrants del universo, con velas DISPERSAS (una vela por
minuto negociado, no por minuto de reloj), la "vela siguiente" a las 11:29
podia ser la de las 13:45.

Datos de aquella corrida, ventana 09:30-11:30: 41 entradas en el cubo de las
11:30 (casi todas las 11:31) y 5 entradas sueltas a las 12:11, 12:30, 13:01 y
13:45. Ninguna daba error ni aparecia en ningun log.

Decision de producto (Jaume, 2026-09-06): ventana ESTRICTA. Si el limite esta
en 11:30 y la senal salta en la vela de 11:30, la compra caeria en la de 11:31
y por tanto NO se coge.
"""
import numpy as np

from app.services.strategy_engine import (
    apply_entry_fill_window, build_entry_time_mask,
)


VENTANA = [{"from_time": "09:30", "to_time": "11:30"}]


def _minutos(horas):
    """['09:30', '11:31'] -> array de minutos desde medianoche."""
    return np.array([int(h[:2]) * 60 + int(h[3:]) for h in horas])


def test_la_senal_del_ultimo_minuto_de_la_ventana_no_entra():
    """EL CASO QUE PIDIO JAUME: senal a las 11:30, relleno a las 11:31 -> fuera."""
    minutos = _minutos(["11:29", "11:30", "11:31"])
    entradas = np.array([True, True, False])
    out = apply_entry_fill_window(entradas, minutos, VENTANA)
    # 11:29 sobrevive: su relleno es la vela de 11:30, dentro de la ventana.
    # 11:30 se cae: su relleno es la de 11:31, fuera.
    assert list(out) == [True, False, False]


def test_la_vela_dispersa_lejana_se_descarta():
    """El caso de los warrants: la vela siguiente esta HORAS despues."""
    minutos = _minutos(["11:28", "13:45"])
    entradas = np.array([True, False])
    out = apply_entry_fill_window(entradas, minutos, VENTANA)
    assert not out.any(), "la senal de 11:28 rellenaba a las 13:45"


def test_dentro_de_la_ventana_las_entradas_legitimas_sobreviven():
    """El arreglo no puede vaciar la estrategia."""
    minutos = _minutos(["09:30", "09:31", "10:00", "10:01"])
    entradas = np.ones(4, dtype=bool)
    out = apply_entry_fill_window(entradas, minutos, VENTANA)
    # La ultima se cae por no tener vela siguiente, no por la hora.
    assert list(out) == [True, True, True, False]


def test_sin_ventana_declarada_no_se_toca_nada():
    """Regla nº1: una definicion sin ventana se comporta igual que siempre."""
    minutos = _minutos(["09:00", "14:00", "19:00"])
    entradas = np.ones(3, dtype=bool)
    assert list(apply_entry_fill_window(entradas, minutos, [])) == [True] * 3
    assert build_entry_time_mask([], minutos) is None


def test_sin_look_ahead_prevention_manda_la_propia_vela():
    """Sin prevencion se compra al cierre de la vela de la senal: se mira `i`."""
    minutos = _minutos(["11:29", "11:30", "11:31"])
    entradas = np.ones(3, dtype=bool)
    out = apply_entry_fill_window(entradas, minutos, VENTANA,
                                  look_ahead_prevention=False)
    assert list(out) == [True, True, False]


def test_la_ultima_vela_del_dia_nunca_entra():
    """No tiene vela siguiente. El simulador ya la descarta (`i < n - 1`)."""
    minutos = _minutos(["10:00"])
    assert not apply_entry_fill_window(np.array([True]), minutos, VENTANA).any()


def test_longitudes_distintas_no_filtran_a_medias():
    """Un desajuste es un bug de alineacion: se avisa, no se recorta al azar."""
    minutos = _minutos(["10:00", "10:01"])
    entradas = np.ones(5, dtype=bool)
    out = apply_entry_fill_window(entradas, minutos, VENTANA)
    assert list(out) == [True] * 5


def test_varias_ventanas_se_suman():
    """Dos franjas: la mascara es la union, y el relleno se mira igual."""
    ventanas = [{"from_time": "09:30", "to_time": "10:00"},
                {"from_time": "14:00", "to_time": "15:00"}]
    minutos = _minutos(["09:45", "09:46", "12:00", "14:30", "14:31"])
    entradas = np.ones(5, dtype=bool)
    out = apply_entry_fill_window(entradas, minutos, ventanas)
    assert list(out) == [True, False, False, True, False]
