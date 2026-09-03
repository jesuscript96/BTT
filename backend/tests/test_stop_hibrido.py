"""STOP HÍBRIDO: por distancia al stop, pero con techo de exposición.

DE DÓNDE SALE. Los dos modos clásicos fallan en extremos opuestos:

* **Por SL** escala muy bien y gestiona el riesgo cuando el stop queda lejos,
  pero si el stop cae MUY cerca de la entrada el tamaño se dispara. Con un
  hueco brutal en contra —el precio se va un 5.000 %— no pierdes tu riesgo:
  puedes acabar debiendo dinero.
* **Por valor de mercado** acota ese desastre (sabes cuánto tienes puesto) pero
  no escala igual de bien.

El híbrido va SIEMPRE por SL salvo que el tamaño resultante exponga más de lo
que aceptas perder ante un evento de cola. Entonces **recorta hasta el techo**,
no anula la operación.

    techo en dólares = (% de cuenta que aceptas perder × capital) / % del evento

EL ERROR FÁCIL, y por eso hay un test dedicado: **el techo es de VALOR, no de
acciones**. Con 100 $ de techo compras 100 acciones a 1 $, pero 200 a 0,50 $.
Confundirlo multiplica la exposición real por el precio.
"""
import numpy as np

from app.services.portfolio_sim import simulate, tope_hibrido


# ── El cálculo, aislado ──────────────────────────────────────────────────

def test_el_ejemplo_de_jaume():
    """10.000 de capital, acepta perder la mitad ante un evento del 5.000 %."""
    # (0,5 × 10.000) / 50 = 100 $ de posición. A 1 $/acción, 100 acciones.
    assert tope_hibrido(10_000, 5_000, 50, 1.0) == 100.0


def test_el_techo_es_de_valor_no_de_acciones():
    """El mismo techo en dólares son MÁS acciones si la acción vale menos."""
    assert tope_hibrido(10_000, 5_000, 50, 0.50) == 200.0
    assert tope_hibrido(10_000, 5_000, 50, 2.00) == 50.0
    # …y en los tres casos la exposición es la misma: 100 $.
    for precio in (0.50, 1.0, 2.0):
        assert tope_hibrido(10_000, 5_000, 50, precio) * precio == 100.0


def test_la_perdida_ante_el_evento_es_la_que_se_acepto():
    """La comprobación que da sentido a la fórmula."""
    capital, bs, perdida_max = 10_000.0, 5_000.0, 50.0
    precio = 3.7
    acciones = tope_hibrido(capital, bs, perdida_max, precio)
    valor = acciones * precio
    # Un movimiento del 5.000 % en contra cuesta 50 veces el valor de la posición.
    perdida = valor * (bs / 100.0)
    assert abs(perdida - capital * perdida_max / 100.0) < 1e-6


def test_sin_datos_no_se_inventa_un_techo():
    """Falta un dato -> None. Un techo inventado es peor que ninguno."""
    assert tope_hibrido(0, 5_000, 50, 1.0) is None          # sin capital
    assert tope_hibrido(10_000, None, 50, 1.0) is None      # sin evento
    assert tope_hibrido(10_000, 5_000, None, 1.0) is None   # sin % de pérdida
    assert tope_hibrido(10_000, 5_000, 50, 0) is None       # sin precio


# ── Dentro del simulador ─────────────────────────────────────────────────

def _correr(**extra):
    """Un caso con el stop MUY ceñido: por SL pediría un tamaño enorme."""
    n = 10
    base = dict(
        close=np.array([100.0] * n), open_=np.array([100.0] * n),
        high=np.array([101.0] * n), low=np.array([99.0] * n),
        entries=np.array([False, True] + [False] * (n - 2)),
        exits=np.array([False] * (n - 2) + [True, False]),
        direction="longonly", init_cash=10_000.0,
        risk_r=100.0, risk_type="FIXED", accumulate=True,
        size_by_sl=True, sl_stop=0.001,   # stop al 0,1 % -> 1.000 acciones
    )
    base.update(extra)
    return simulate(**base)


def test_sin_hibrido_manda_el_tope_de_caja():
    """Control: por SL pide 1.000 acciones y la caja lo deja en 100."""
    t = _correr()["trades"]
    assert t, "debería haber una operación"
    # 10.000 de caja / 100 de precio = 100 acciones.
    assert abs(t[0]["size"] - 100.0) < 1e-6


def test_con_hibrido_se_recorta_al_techo():
    """EL CASO QUE MOTIVA TODO: stop ceñido, exposición acotada.

    Evento del 1.000 % y media cuenta: (0,5 × 10.000) / 10 = 500 $ -> a 100 $
    la acción, 5 acciones. Muy por debajo de las 100 que dejaba la caja.
    """
    t = _correr(hybrid_stop=True, hybrid_black_swan_pct=1_000,
                hybrid_max_loss_pct=50)["trades"]
    assert t, "el híbrido RECORTA, no anula la operación"
    assert abs(t[0]["size"] - 5.0) < 1e-6


def test_el_hibrido_no_toca_lo_que_ya_estaba_por_debajo():
    """Si el tamaño por SL ya cabe en el techo, no se recorta nada."""
    # Techo enorme: (0,5 × 10.000) / 0,1 = 500.000 $ -> 5.000 acciones.
    t = _correr(hybrid_stop=True, hybrid_black_swan_pct=10,
                hybrid_max_loss_pct=50)["trades"]
    assert abs(t[0]["size"] - 100.0) < 1e-6   # manda la caja, como sin híbrido


def test_sin_size_by_sl_el_hibrido_no_se_aplica():
    """Por valor de mercado ya sabes lo que tienes puesto: nada que topar."""
    t = _correr(size_by_sl=False, hybrid_stop=True,
                hybrid_black_swan_pct=1_000, hybrid_max_loss_pct=50)["trades"]
    # 100 de riesgo / 100 de precio = 1 acción, y el híbrido no la toca.
    assert abs(t[0]["size"] - 1.0) < 1e-6


def test_hibrido_sin_parametros_se_comporta_como_size_by_sl():
    """Regla nº1: encender el modo sin rellenar los números no cambia nada."""
    con = _correr(hybrid_stop=True)["trades"]
    sin = _correr()["trades"]
    assert abs(con[0]["size"] - sin[0]["size"]) < 1e-9
