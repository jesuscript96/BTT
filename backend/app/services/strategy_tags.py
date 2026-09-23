"""Tags de organizacion de estrategias (2026-09-23, peticion de Alvaro).

Etiquetas libres que el usuario pone a sus estrategias guardadas para
encontrarlas y agruparlas en el selector del backtester y en el Baul de
Portfolio. Son SOLO metadato: no forman parte de la definicion, no cambian
ningun backtest y viven en la columna `tags` de la tabla `strategies`
(JSON-array en VARCHAR, misma filosofia que `definition`).

Los tags 'premarket' / 'rth' / 'scalping' / 'piramidacion' NO se guardan
nunca: el frontend los deriva de la propia definicion (market_sessions,
scalping, pyramiding), asi que no pueden quedar desactualizados al editar
la estrategia. Aqui solo vive lo que el usuario escribe a mano.
"""
import json
from typing import List, Optional

MAX_TAGS = 10
MAX_TAG_LEN = 24


def parse_tags_column(raw: Optional[object]) -> List[str]:
    """VARCHAR con un JSON-array -> lista de strings.

    Tolerante a proposito: NULL, basura de una instalacion vieja o un tipo
    inesperado devuelven [] — lo peor que puede pasar es que la estrategia
    aparezca sin etiquetas, nunca que el listado entero reviente.
    """
    if isinstance(raw, list):
        return [t for t in raw if isinstance(t, str)]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if isinstance(parsed, list):
            return [t for t in parsed if isinstance(t, str)]
    return []


def sanitize_tags(raw: List[str]) -> List[str]:
    """Normaliza lo que llega al PATCH /{id}/tags.

    Trim, sin vacios, dedupe case-insistente conservando la primera
    aparicion, tope de MAX_TAGS etiquetas de MAX_TAG_LEN caracteres. El
    primer problema levanta ValueError con mensaje claro, para que la
    frontera del API lo convierta en un 400 explicito — nada de recortar en
    silencio lo que el usuario creo que habia guardado.
    """
    out: List[str] = []
    seen = set()
    for t in raw:
        if not isinstance(t, str):
            raise ValueError("Cada tag debe ser un texto")
        t = t.strip()
        if not t:
            continue
        if len(t) > MAX_TAG_LEN:
            raise ValueError(
                f"El tag «{t}» pasa de {MAX_TAG_LEN} caracteres"
            )
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
        if len(out) == MAX_TAGS:
            break
    return out


def tags_to_column(tags: List[str]) -> str:
    """Lista -> VARCHAR para la columna. ensure_ascii=False: 'piramidación'
    debe poder vivir en un tag sin escaparse."""
    return json.dumps(tags, ensure_ascii=False)
