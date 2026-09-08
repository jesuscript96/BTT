"""Modo «MEJORAR» del genético: afinar UNA estrategia sin romperla.

POR QUÉ ESTE FICHERO. El modo explorador construye la estrategia entera desde
su cromosoma, así que lo que no sabe expresar simplemente no existe. El modo
mejorar parte de una estrategia REAL — hecha a mano, con su lógica de salida,
sus precondiciones y su temporalidad — y solo puede tocar lo que el usuario
haya marcado. **Lo que no se marca tiene que quedar intacto**, y eso es
exactamente lo que aquí se comprueba: si un día alguien reutiliza el traductor
del explorador para esto, la estrategia perdería la mitad de su definición sin
un solo error.
"""
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from genetico import afinar, especie  # noqa: E402
from genetico import evaluador as EV  # noqa: E402


# Una estrategia con TODO lo que el cromosoma del explorador no sabe expresar.
SEMILLA = {
    "bias": "short",
    "apply_day": "gap_day",
    "postgap_preconditions": [{"metric": "volume", "day": "gap_day", "value": 500000}],
    "entry_logic": {
        "timeframe": "5m",
        "candle_delay": 2,
        "root_condition": {"type": "group", "operator": "AND", "conditions": []},
        "entry_time_windows": [{"from_time": "09:30", "to_time": "11:30"}],
    },
    "exit_logic": {
        "timeframe": "1m",
        "root_condition": {"type": "group", "operator": "OR", "conditions": []},
    },
    "risk_management": {
        "hard_stop": {"type": "Percentage", "value": 15},
        "take_profit": {"type": "Percentage", "value": 35},
        "accept_reentries": True, "max_reentries": 5,
        "trailing_stop": {"active": False, "type": "Percentage", "buffer_pct": 0.5},
    },
    "market_sessions": ["custom"],
    "custom_start_time": "04:00",
    "custom_end_time": "12:00",
}

GENES = [
    {"id": "stop", "label": "Stop %", "path": "risk_management.hard_stop.value",
     "min": 10, "max": 20, "step": 5, "current_value": 15},
    {"id": "tp", "label": "TP %", "path": "risk_management.take_profit.value",
     "min": 25, "max": 45, "step": 10, "current_value": 35},
    {"id": "hasta", "label": "Ventana hasta", "unit": "time_of_day",
     "path": "entry_logic.entry_time_windows.0.to_time",
     "min": 630, "max": 750, "step": 30, "current_value": 690},
]


def _cfg(genes=None, **extra):
    c = {"modo": "mejorar", "estrategia_base": SEMILLA, "genes": genes or GENES}
    c.update(extra)
    return c


# ── La especie correcta ─────────────────────────────────────────────────────

def test_sin_modo_se_usa_el_explorador_de_siempre():
    """Regla nº1: una corrida antigua reanudada no lleva `modo` y no cambia."""
    assert especie.modulo({}).__name__.endswith("cromosoma")
    assert especie.modulo({"modo": "explorar"}).__name__.endswith("cromosoma")
    assert not especie.es_mejorar({})


def test_el_modo_mejorar_usa_el_cromosoma_nuevo():
    assert especie.modulo({"modo": "mejorar"}).__name__.endswith("afinar")


# ── La semilla y la rejilla ─────────────────────────────────────────────────

def test_la_semilla_es_la_estrategia_tal_cual():
    """La línea base. Sin ella no se sabe si el genético ha mejorado algo."""
    ind = afinar.desde_semilla(_cfg())
    assert ind["valores"] == {"stop": 15, "tp": 35, "hasta": 690}


def test_un_valor_fuera_de_rejilla_cae_al_escalon_mas_cercano():
    """El usuario elige el rango; el valor de hoy puede no caer en él."""
    genes = [dict(GENES[0], min=10, max=20, step=5, current_value=17)]
    ind = afinar.desde_semilla(_cfg(genes))
    assert ind["valores"]["stop"] == 15   # 17 está más cerca de 15 que de 20


def test_la_rejilla_de_una_hora_va_en_minutos_enteros():
    rej = afinar._rejilla(GENES[2])
    assert rej == [630, 660, 690, 720, 750]


# ── Lo que NO se marca, no se toca ──────────────────────────────────────────

def test_la_definicion_conserva_todo_lo_que_no_es_gen():
    """EL PUNTO DE TODO ESTE MODO.

    Salida, precondiciones, temporalidad y retardo de velas sobreviven. El
    cromosoma del explorador los pondría a None y nadie se enteraría.
    """
    d = afinar.a_definicion(afinar.desde_semilla(_cfg()), _cfg())
    assert d["exit_logic"]["root_condition"]["operator"] == "OR"
    assert d["postgap_preconditions"][0]["metric"] == "volume"
    assert d["entry_logic"]["timeframe"] == "5m"
    assert d["entry_logic"]["candle_delay"] == 2
    assert d["risk_management"]["max_reentries"] == 5


def test_la_semilla_original_no_se_modifica():
    """`a_definicion` trabaja sobre una copia: si mutara la semilla, el segundo
    individuo partiría del primero y la corrida entera iría a la deriva."""
    afinar.a_definicion({"valores": {"stop": 20, "tp": 25, "hasta": 750}}, _cfg())
    assert SEMILLA["risk_management"]["hard_stop"]["value"] == 15


def test_una_hora_se_escribe_como_texto():
    """El gen viaja en minutos; la definición guarda «HH:MM». Si esto falla, el
    motor recibe `to_time = 750.0`, la ventana se descarta entera y la corrida
    sale como si no hubiera límite horario — sin error."""
    d = afinar.a_definicion({"valores": {"stop": 15, "tp": 35, "hasta": 750}}, _cfg())
    assert d["entry_logic"]["entry_time_windows"][0]["to_time"] == "12:30"
    assert d["entry_logic"]["entry_time_windows"][0]["from_time"] == "09:30"


def test_una_ruta_que_ya_no_existe_no_tumba_la_evaluacion():
    """La estrategia se editó después de configurar la corrida."""
    genes = GENES + [{"id": "fantasma", "label": "?", "path": "no.existe.nada",
                      "min": 1, "max": 3, "step": 1, "current_value": 1}]
    d = afinar.a_definicion(afinar.desde_semilla(_cfg(genes)), _cfg(genes))
    assert d["risk_management"]["hard_stop"]["value"] == 15


# ── La sesión: tipo + dos horas, barribles ─────────────────────────────────

def _cfg_ses(*genes):
    return {"modo": "mejorar", "estrategia_base": SEMILLA, "genes": list(genes)}


G_TIPO = {"id": "tipo", "label": "Tipo", "path": afinar.GEN_SESION_TIPO,
          "opciones": ["custom", "rth", "pre+rth"], "current_value": "custom"}
G_DESDE = {"id": "desde", "label": "Abre", "path": afinar.GEN_SESION_DESDE,
           "unit": "time_of_day", "min": 240, "max": 660, "step": 15, "current_value": 240}
G_HASTA = {"id": "hasta", "label": "Cierra", "path": afinar.GEN_SESION_HASTA,
           "unit": "time_of_day", "min": 600, "max": 780, "step": 15, "current_value": 720}


def test_se_puede_barrer_la_hora_de_cierre():
    """EL CASO QUE PIDIO JAUME: «ver si cerrando a las 11 es mejor que a las 12».
    Con un solo gen categórico de sesión esto no se podía."""
    cfg = _cfg_ses(G_HASTA)
    d11 = afinar.a_definicion({"valores": {"hasta": 660}}, cfg)
    d12 = afinar.a_definicion({"valores": {"hasta": 720}}, cfg)
    assert d11["custom_end_time"] == "11:00"
    assert d12["custom_end_time"] == "12:00"
    # La otra punta se queda en la que tenía la estrategia.
    assert d11["custom_start_time"] == "04:00"


def test_marcar_solo_una_hora_pasa_la_sesion_a_personalizada():
    """Si se quedara en RTH, el barrido no cambiaría nada: N corridas dando el
    mismo número, sin error."""
    semilla_rth = {**SEMILLA, "market_sessions": ["rth"]}
    semilla_rth.pop("custom_start_time", None)
    semilla_rth.pop("custom_end_time", None)
    cfg = {"modo": "mejorar", "estrategia_base": semilla_rth, "genes": [G_HASTA]}
    d = afinar.a_definicion({"valores": {"hasta": 660}}, cfg)
    assert d["market_sessions"] == ["custom"]
    assert d["custom_start_time"] == "09:30"   # la apertura de RTH, sin tocar
    assert d["custom_end_time"] == "11:00"


def test_el_tipo_manda_sobre_las_horas():
    cfg = _cfg_ses(G_TIPO, G_DESDE, G_HASTA)
    d = afinar.a_definicion({"valores": {"tipo": "pre+rth", "desde": 300, "hasta": 660}}, cfg)
    assert d["market_sessions"] == ["pre", "rth"]
    assert "custom_start_time" not in d, "fuera de personalizada las horas se borran"


def test_una_sesion_invertida_no_se_escribe():
    """Cierre antes de la apertura recorta el día a cero velas. El genético lo
    descarta solo (0 operaciones = nota 0), pero no se guarda un imposible."""
    cfg = _cfg_ses(G_DESDE, G_HASTA)
    d = afinar.a_definicion({"valores": {"desde": 660, "hasta": 600}}, cfg)
    assert d["custom_start_time"] < d["custom_end_time"]


def test_sin_genes_de_sesion_la_estrategia_conserva_la_suya():
    d = afinar.a_definicion(afinar.desde_semilla(_cfg()), _cfg())
    assert d["market_sessions"] == ["custom"]
    assert d["custom_start_time"] == "04:00" and d["custom_end_time"] == "12:00"


# ── Operadores ──────────────────────────────────────────────────────────────

def test_mutar_siempre_cambia_algo():
    """Si devolviera un clon, ya está en la caché y la generación se queda sin
    individuos nuevos que evaluar."""
    cfg = _cfg()
    base = afinar.desde_semilla(cfg)
    rng = random.Random(7)
    for _ in range(40):
        assert afinar.mutar(base, cfg, rng)["valores"] != base["valores"]


def test_mutar_se_queda_dentro_de_la_rejilla():
    cfg = _cfg()
    ind = afinar.desde_semilla(cfg)
    rng = random.Random(1)
    rejillas = {g["id"]: g["_rejilla"] for g in afinar.genes(cfg)}
    for _ in range(200):
        ind = afinar.mutar(ind, cfg, rng)
        for k, v in ind["valores"].items():
            assert v in rejillas[k], f"{k}={v} fuera de {rejillas[k]}"


def test_cruzar_solo_mezcla_valores_de_los_padres():
    cfg = _cfg()
    a = {"valores": {"stop": 10, "tp": 25, "hasta": 630}}
    b = {"valores": {"stop": 20, "tp": 45, "hasta": 750}}
    rng = random.Random(3)
    for _ in range(50):
        h = afinar.cruzar(a, b, cfg, rng)
        for k, v in h["valores"].items():
            assert v in (a["valores"][k], b["valores"][k])


def test_la_huella_no_depende_del_orden_de_los_genes():
    x = {"valores": {"stop": 15, "tp": 35, "hasta": 690}}
    y = {"valores": {"hasta": 690, "tp": 35, "stop": 15}}
    assert afinar.huella(x) == afinar.huella(y)


def test_los_indices_miden_escalones_de_rejilla():
    """Es lo que permite puntuar por vecindario: la distancia entre individuos."""
    cfg = _cfg()
    a = afinar.indices({"valores": {"stop": 10, "tp": 25, "hasta": 630}}, cfg)
    b = afinar.indices({"valores": {"stop": 15, "tp": 25, "hasta": 630}}, cfg)
    assert sum(abs(x - y) for x, y in zip(a, b)) == 1


def test_la_receta_lee_las_horas_como_horas():
    txt = afinar.receta({"valores": {"stop": 15, "tp": 35, "hasta": 690}}, _cfg())
    assert "11:30" in txt and "Stop %" in txt


# ── Agregación de robustez ──────────────────────────────────────────────────

def test_valor_es_exactamente_la_nota_de_siempre():
    """Regla nº1: sin agregación, el explorador no nota nada."""
    m = {"fitness_base": 12.5}
    assert EV.agregar(m, {}, {}) == 12.5
    assert EV.agregar(m, {}, {"agregacion": "valor"}) == 12.5


def test_los_trozos_parten_por_dias_de_mercado():
    fechas = [f"2026-01-{d:02d}" for d in range(1, 13)]
    trozos = EV._trozos_de_fechas(fechas, 4)
    assert len(trozos) == 4
    assert all(len(t) == 3 for t in trozos)


def test_peor_trozo_castiga_al_que_solo_funciona_un_trimestre():
    """EL PUNTO DE LA ROBUSTEZ TEMPORAL."""
    # Cuatro tramos: tres planos y uno espectacular.
    trades = []
    for d in range(1, 13):
        pnl = 100.0 if d >= 10 else 1.0
        trades.append({"date": f"2026-01-{d:02d}", "pnl": pnl})
    res = {"trades": trades, "day_results": []}
    cfg = {"fitness": "ev", "agregacion": "peor_trozo", "trozos": 4,
           "riesgo": {"risk_r": 100, "risk_type": "FIXED"}}
    m = {"fitness_base": 25.75}          # la media de todo el periodo
    nota = EV.agregar(m, res, cfg)
    assert nota == 1.0, "el peor tramo manda, no la media"


def test_media_menos_sigma_castiga_al_irregular():
    """Con tramos muy desiguales la nota puede caer POR DEBAJO del peor tramo,
    y está bien: media − σ no es una media acotada, es un castigo por
    irregularidad. Lo que importa es que ordene por debajo del regular."""
    def nota(pnl_por_dia):
        trades = [{"date": f"2026-01-{d:02d}", "pnl": pnl_por_dia(d)}
                  for d in range(1, 13)]
        cfg = {"fitness": "ev", "agregacion": "media_menos_sigma", "trozos": 4,
               "riesgo": {"risk_r": 100, "risk_type": "FIXED"}}
        return EV.agregar({"fitness_base": 1.0}, {"trades": trades, "day_results": []}, cfg)

    irregular = nota(lambda d: 100.0 if d >= 10 else 1.0)   # todo en un tramo
    regular = nota(lambda d: 25.75)                          # lo mismo, repartido
    assert regular > irregular
    assert regular == 25.75, "sin dispersión, la nota es la media"


def test_bajo_el_suelo_de_operaciones_no_hay_agregacion_que_valga():
    """`fitness_base` 0 significa que no llegó a `min_trades`."""
    assert EV.agregar({"fitness_base": 0.0}, {"trades": []},
                      {"agregacion": "peor_trozo"}) == 0.0


# ── Guardas fijas, tambien en modo mejorar ──────────────────────────────────

def test_las_guardas_se_meten_delante_de_la_entrada():
    g = {"type": "indicator_comparison", "source": {"name": "Bar Close"},
         "comparator": "GREATER_THAN", "target": 0.1}
    cfg = _cfg(guardas=[g])
    d = afinar.a_definicion(afinar.desde_semilla(cfg), cfg)
    conds = d["entry_logic"]["root_condition"]["conditions"]
    assert conds[0]["target"] == 0.1


def test_con_un_OR_la_guarda_envuelve_en_vez_de_colarse():
    """Meter una guarda DENTRO de un OR la convertiria en «o esto o la guarda»,
    que es justo lo contrario de una guarda."""
    semilla_or = {**SEMILLA, "entry_logic": {
        "timeframe": "1m",
        "root_condition": {"type": "group", "operator": "OR", "conditions": [{"x": 1}]},
        "entry_time_windows": [{"from_time": "09:30", "to_time": "11:30"}],
    }}
    g = {"type": "indicator_comparison", "source": {"name": "Bar Close"},
         "comparator": "GREATER_THAN", "target": 0.1}
    cfg = {"modo": "mejorar", "estrategia_base": semilla_or, "genes": GENES, "guardas": [g]}
    d = afinar.a_definicion({"valores": {"stop": 15, "tp": 35, "hasta": 690}}, cfg)
    raiz = d["entry_logic"]["root_condition"]
    assert raiz["operator"] == "AND"
    assert raiz["conditions"][0]["target"] == 0.1
    assert raiz["conditions"][1]["operator"] == "OR"


def test_sin_guardas_la_entrada_no_se_toca():
    cfg = _cfg()
    d = afinar.a_definicion(afinar.desde_semilla(cfg), cfg)
    assert d["entry_logic"]["root_condition"]["conditions"] == []


# ── Parciales: cuantos y de que tipo (peticion de Jaume, 6-sep) ─────────────
#
# No es afinar un numero: cambia la estrategia. Se acepto a proposito — «quiero
# probar que pasa si añado 3 o 5 parciales, ya sea por hora, minutos o
# distancia». El capital se reparte a partes iguales para que sume 100 sin
# meter N dimensiones mas de sobreajuste.

GENES_PARC = [
    {"id": "n", "label": "Cuantos", "path": afinar.GEN_PARCIALES_N,
     "min": 0, "max": 3, "step": 1, "is_int": True, "current_value": 1},
    {"id": "p0", "label": "Parcial 1", "path": "__parcial__:0",
     "opciones": ["pct:3", "pct:6", "hora:10:30", "tiempo:30"], "current_value": "pct:3"},
    {"id": "p1", "label": "Parcial 2", "path": "__parcial__:1",
     "opciones": ["pct:3", "pct:6", "hora:10:30", "tiempo:30"], "current_value": "pct:6"},
    {"id": "p2", "label": "Parcial 3", "path": "__parcial__:2",
     "opciones": ["pct:3", "pct:6", "hora:10:30", "tiempo:30"], "current_value": "hora:10:30"},
]


def _cfgp(**extra):
    c = {"modo": "mejorar", "estrategia_base": SEMILLA, "genes": GENES_PARC}
    c.update(extra)
    return c


def test_puede_añadir_parciales_que_la_estrategia_no_tenia():
    """La semilla no lleva parciales; el genetico prueba con tres."""
    cfg = _cfgp()
    d = afinar.a_definicion(
        {"valores": {"n": 3, "p0": "pct:3", "p1": "pct:6", "p2": "hora:10:30"}}, cfg)
    rm = d["risk_management"]
    assert rm["take_profit_mode"] == "Partial"
    assert [p["distance_pct"] for p in rm["partial_take_profits"]] == [3.0, 6.0, "HOUR:10:30"]


def test_el_capital_de_los_parciales_suma_siempre_100():
    """Si no suma 100 el motor deja posicion sin cerrar o cierra de mas."""
    cfg = _cfgp()
    for n in (1, 2, 3):
        d = afinar.a_definicion(
            {"valores": {"n": n, "p0": "pct:3", "p1": "pct:6", "p2": "tiempo:30"}}, cfg)
        caps = [p["capital_pct"] for p in d["risk_management"]["partial_take_profits"]]
        assert len(caps) == n
        assert round(sum(caps), 6) == 100.0, f"con {n} niveles suma {sum(caps)}"


def test_cero_parciales_vuelve_a_take_profit_completo():
    """Es la comparacion contra NO ponerlos. En «Full» el motor ignora la lista
    y manda `take_profit`, que la semilla conserva intacto."""
    d = afinar.a_definicion({"valores": {"n": 0}}, _cfgp())
    rm = d["risk_management"]
    assert rm["take_profit_mode"] == "Full"
    assert rm["partial_take_profits"] == []
    assert rm["take_profit"]["value"] == 35


def test_los_tres_tipos_de_disparador_se_escriben_como_los_espera_el_motor():
    cfg = _cfgp()
    d = afinar.a_definicion(
        {"valores": {"n": 3, "p0": "pct:6", "p1": "hora:10:30", "p2": "tiempo:30"}}, cfg)
    vals = [p["distance_pct"] for p in d["risk_management"]["partial_take_profits"]]
    assert vals == [6.0, "HOUR:10:30", "TIME:30"]


def test_con_estructura_las_rutas_de_parciales_se_ignoran():
    """Dos genes por lo mismo se pelean. Y peor: `_encode_tp_value` releeria la
    forma NUEVA, asi que escribir un 6 sobre un nivel «HOUR:10:30» daria
    «HOUR:00:06» — un disparador que nadie ha pedido, sin error."""
    genes = GENES_PARC + [{"id": "dist0", "label": "Distancia 1",
                           "path": "risk_management.partial_take_profits.0.distance_pct",
                           "min": 1, "max": 9, "step": 1, "current_value": 3}]
    cfg = {"modo": "mejorar", "estrategia_base": SEMILLA, "genes": genes}
    d = afinar.a_definicion(
        {"valores": {"n": 1, "p0": "hora:10:30", "dist0": 6}}, cfg)
    assert d["risk_management"]["partial_take_profits"][0]["distance_pct"] == "HOUR:10:30"


def test_sin_genes_de_parciales_la_estrategia_no_se_toca():
    """Regla nº1: si no marcas nada de parciales, ni se miran."""
    d = afinar.a_definicion(afinar.desde_semilla(_cfg()), _cfg())
    assert "partial_take_profits" not in d["risk_management"]


# ── Piramidacion ───────────────────────────────────────────────────────────

SEMILLA_PYR = {**SEMILLA, "pyramiding": {"timeframe": "1m", "mode": "individual", "levels": [
    {"action": "add", "unit": "pct", "capital_pct": 25, "times": 2,
     "root_condition": {"type": "group", "operator": "AND", "conditions": []}}]}}


def test_la_piramide_sobrevive_aunque_no_se_toque():
    cfg = {"modo": "mejorar", "estrategia_base": SEMILLA_PYR, "genes": GENES}
    d = afinar.a_definicion(afinar.desde_semilla(cfg), cfg)
    assert d["pyramiding"]["levels"][0]["capital_pct"] == 25
    assert d["pyramiding"]["mode"] == "individual"


def test_la_piramide_se_puede_mover():
    g = [{"id": "pyr", "label": "Piramide 1 %",
          "path": "pyramiding.levels.0.capital_pct",
          "min": 10, "max": 40, "step": 5, "current_value": 25}]
    cfg = {"modo": "mejorar", "estrategia_base": SEMILLA_PYR, "genes": g}
    d = afinar.a_definicion({"valores": {"pyr": 40}}, cfg)
    assert d["pyramiding"]["levels"][0]["capital_pct"] == 40
    assert d["pyramiding"]["levels"][0]["times"] == 2   # lo no marcado, intacto


def test_el_extractor_ve_los_parametros_de_la_piramide():
    """Antes del 6-sep no los veia: ni el genetico ni el optimizador 3D podian
    mover una piramide, aunque el tamaño de un añadido pesa como el de la
    entrada."""
    from app.services.optimization_service import extract_parameters
    rutas = {p["path"] for p in extract_parameters(SEMILLA_PYR)}
    assert "pyramiding.levels.0.capital_pct" in rutas
    assert "pyramiding.levels.0.times" in rutas


def test_el_disparador_de_un_parcial_se_lee_en_cristiano():
    """Viaja codificado («pct:6») para ordenarlo como rejilla, pero en la receta
    y en la pantalla tiene que leerse. Jaume, 6-sep: «parcial 1, 2, 3 con
    disparador no sé qué significa»."""
    cfg = _cfgp()
    txt = afinar.receta({"valores": {"n": 3, "p0": "pct:6", "p1": "hora:10:30",
                                     "p2": "tiempo:30"}}, cfg)
    assert "al +6 %" in txt
    assert "a las 10:30" in txt
    assert "a los 30 min" in txt


def test_en_modo_mejorar_el_riesgo_del_panel_no_pisa_a_la_estrategia():
    """Reentradas, «shares por SL» y stop hibrido salen de la DEFINICION.

    `run_backtest` los recibe por argumento y el argumento gana. Si se cogieran
    del panel del explorador, la corrida evaluaria una gestion de riesgo que el
    usuario no ha pedido, sin ningun error. Por eso en la pagina esos tres
    controles no se pintan en modo mejorar: serian ajustes fantasma.
    """
    from genetico import evaluador as EV
    definicion = {"market_sessions": ["rth"], "risk_management": {
        "size_by_sl": True, "hybrid_stop": True,
        "hybrid_black_swan_pct": 500, "hybrid_max_loss_pct": 2,
    }}
    # El config del panel dice lo CONTRARIO de la estrategia.
    cfg = {"riesgo": {"size_by_sl": False, "hybrid_stop": False,
                      "accept_reentries": True, "max_reentries": 99}}
    p = EV.parametros_backtest(cfg, definicion)
    assert p["size_by_sl"] is True
    assert p["hybrid_stop"] is True
    assert p["hybrid_black_swan_pct"] == 500
    # Y las reentradas NO viajan como argumento: las lleva la definicion.
    assert "accept_reentries" not in p and "max_reentries" not in p


# ── El usuario elige QUE disparadores puede probar cada parcial ──────────────
# Jaume, 6-sep-2026: «no me deja elegir esos baremos el programa, solo me deja
# elegir si quiero 1, 2, 3... hasta 5 parciales». La pagina ya deja recortar la
# lista de `opciones` de un gen categorico; lo que se comprueba aqui es que ese
# recorte MANDA de verdad. Si `aleatorio` o `mutar` se saltaran la lista, la
# corrida probaria valores que el usuario ha quitado y no habria ningun error:
# solo resultados con un parcial que dijo que no queria.

def _cfg_recortado():
    """Igual que GENES_PARC pero con el parcial 1 limitado a DOS opciones, y
    ninguna de ellas es la que tiene hoy la estrategia."""
    genes = [dict(g) for g in GENES_PARC]
    genes[1] = {**genes[1], "opciones": ["hora:10:30", "tiempo:30"]}
    return {"modo": "mejorar", "estrategia_base": SEMILLA, "genes": genes}


def test_recortar_las_opciones_recorta_la_rejilla():
    cfg = _cfg_recortado()
    rej = {g["id"]: g["_rejilla"] for g in afinar.genes(cfg)}
    assert rej["p0"] == ["hora:10:30", "tiempo:30"]
    assert rej["p1"] == ["pct:3", "pct:6", "hora:10:30", "tiempo:30"], (
        "recortar un parcial no puede tocar a los demas")


def test_ni_el_azar_ni_la_mutacion_se_salen_de_lo_elegido():
    cfg = _cfg_recortado()
    permitidas = {"hora:10:30", "tiempo:30"}
    rng = random.Random(11)
    ind = afinar.desde_semilla(cfg)
    assert ind["valores"]["p0"] in permitidas, (
        "la semilla tenia 'pct:3', que el usuario ha quitado: hay que caer "
        "dentro de la rejilla, no colar el valor de hoy")
    for _ in range(300):
        assert afinar.aleatorio(cfg, rng)["valores"]["p0"] in permitidas
        ind = afinar.mutar(ind, cfg, rng)
        assert ind["valores"]["p0"] in permitidas


def test_una_sola_opcion_deja_el_gen_clavado():
    """Dejar UN valor es legitimo: fija ese parcial sin que el genetico lo
    mueva. La pagina lo permite a proposito (vaciarlo del todo, no)."""
    genes = [dict(g) for g in GENES_PARC]
    genes[1] = {**genes[1], "opciones": ["pct:6"]}
    cfg = {"modo": "mejorar", "estrategia_base": SEMILLA, "genes": genes}
    rng = random.Random(3)
    ind = afinar.desde_semilla(cfg)
    for _ in range(100):
        ind = afinar.mutar(ind, cfg, rng)
        assert ind["valores"]["p0"] == "pct:6"
    d = afinar.a_definicion({"valores": {"n": 1, "p0": "pct:6"}}, cfg)
    assert d["risk_management"]["partial_take_profits"][0]["distance_pct"] == 6.0
