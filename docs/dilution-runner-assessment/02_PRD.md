# 02 — Product Requirement Document (PRD)

Este documento detalla los requerimientos funcionales de producto para la **Versión 2.0 de la Evaluación de Dilución y Runner**.

---

## 1. Visión del Producto
Proporcionar al trader de short-selling un análisis táctico instantáneo y libre de ruido sobre el riesgo de dilución extrema, la estructura accionarial y el estado regulatorio Nasdaq de una acción, permitiendo tomar decisiones rápidas basadas en niveles de precios específicos (ej. precios de ejercicio de warrants y restricciones de volumen de venta).

---

## 2. Requerimientos de Funcionalidad y UI

### 2.1 Subpestaña "Balance" (Frente a "Latest SEC Filings")
*   **Ubicación:** Al lado del encabezado "Latest SEC Filings", agregar una barra de navegación por pestañas (*Tabs*) con dos opciones:
    1.  **Filings (Pestaña por defecto):** Muestra el listado categorizado actual de formularios SEC.
    2.  **Balance:** Muestra una tabla compacta con el histórico trimestral de métricas clave obtenidas de los formularios 10-K y 10-Q.
*   **Columnas de la Tabla "Balance":**
    *   `Periodo (Fecha)`
    *   `Efectivo (Cash)`
    *   `Deuda Total (Total Debt)`
    *   `Capital Circulante (Working Capital)`
    *   `Patrimonio Neto (Stockholders' Equity)`
    *   `Acciones en Circulación (Shares Outstanding)` -> Muestra la cifra exacta para contrastar incrementos drásticos entre trimestres (indicativo directo de dilución histórica).

### 2.2 Tabla de Participaciones y Transacciones (Ownership)
*   **Ubicación:** Dentro del reporte generado por Edgie, se debe renderizar una tabla dedicada llamada **Estructura Accionarial y Transacciones (Ownership)**.
*   **Orígenes de Datos (Formularios SEC):**
    *   **Form 14A:** Accionistas con más del 5% de participación.
    *   **Form 4:** Transacciones recientes de insiders (compras/ventas).
    *   **Form 3:** Declaraciones de propiedad inicial de insiders (incluyendo la fecha oficial de la declaración).
    *   **Schedule 13D / 13G:** Participaciones de fondos de inversión y grandes bloques institucionales.
    *   **Form 20-F (Item 7):** Si la empresa es extranjera (**ADR**), muestra los accionistas mayoritarios.
    *   **Form 6-K:** Informes de ventas o transacciones corporativas relevantes en empresas extranjeras.
*   **Regla de Ordenación Prioritaria:**
    1.  **Personas Físicas (Insiders):** Nombres y apellidos (extraídos principalmente de los formularios 4 y 3) ordenados de mayor a menor participación/volumen transaccionado.
    2.  **Instituciones/Fondos:** Nombres de entidades financieras y corporativas (extraídos de 13G, 13D y 20-F).
*   **Detalle de Fila:** Cada fila debe especificar la acción realizada (ej: *"Compró $2M en acciones"*, *"Posee el 8.4% de la empresa"*, o *"Director Ejecutivo / CEO"*).

### 2.3 Reglas Avanzadas de Dilución Extrema
El motor de análisis de Edgie debe priorizar y estructurar la evaluación basándose en las siguientes reglas lógicas de mercado:

#### A. Identificación de Agente Colocador (Placement Agent)
*   Edgie debe buscar en la primera página o sección *Underwriting* / *Plan of Distribution* de los formularios **S-1 / F-1 / S-3 / F-3** y prospectos **424B** el nombre del banco contratado (ej: *H.C. Wainwright, Maxim Group, Aegis Capital, Roth Capital*).
*   La presencia de estos bancos específicos se contrastará con la base de datos de bancos dilusores para elevar el rating de riesgo de dilución.

#### B. Ofertas Activas "At-The-Market" (ATM)
*   El sistema debe buscar ofertas ATM aprobadas en formularios **8-K o 6-K**.
*   **Condición Crítica de Alerta:** Solo se marcará como alerta de alta peligrosidad si el ATM está declarado como **Effective** o **Active** (aprobado y listo para ejecutar). Si está como **Pending**, se mostrará una etiqueta informativa indicando que está en espera de aprobación por la SEC.
*   Mensaje sugerido en UI: *"ATM de $50M activo vía H.C. Wainwright. No mantener posiciones en largo a largo plazo"*.

#### C. Convertible Notes con Precio Variable (Dilución Tóxica)
*   Alerta máxima si en un Form **8-K, Schedule 13G** o anexos (**Exhibits 4.1 y 10.1**) se detectan cláusulas de descuento sobre VWAP futuro (ej: *"convertible at a 20% discount of the lowest VWAP of the last 5 trading days"*).
*   Se advertirá que los fondos tienen un incentivo matemático para hundir el precio en premarket y vender con ganancia inmediata.
*   Términos de búsqueda obligatorios en contratos: `Warrant Agency Agreement`, `Convertible Note`, `Securities Purchase Agreement`.

#### D. Techos de Peligro y Zonas de Volatilidad por Warrants
*   **Exercise Price (Techo del Peligro):** Si la acción cotiza a $2.00 pero en el formulario **424B4** se estipula que hay warrants con un precio de ejercicio a $5.00, se avisará de que los fondos buscarán presionar el precio hacia $5.00 para ejercer y dumpear.
*   **Redemption Price (Zona de Volatilidad Extrema):** Si el contrato estipula una cláusula del tipo *"Company may call the Warrants for redemption if the closing price exceeds $7.50 for 10 consecutive days"*, marcar el precio de $7.50 como zona de inminente dumping.

#### E. Filtros de Riesgo Regulatorio y Estructural
*   **Filtro de Jurisdicción:** Si una empresa tiene su incorporación en **Cayman Islands** o **British Virgin Islands (BVI)** pero opera en **China, Israel o cualquier país de Asia**, activar alerta de riesgo alto por gobernanza deficiente.
*   **Filtro Public Float:** Si el float público es menor al 5% de las acciones totales en circulación (`float_shares / shares_outstanding < 0.05`), se debe categorizar el ticker como **"Extremadamente manipulable"** debido a la propensión a subidas del +5000% sin volumen sustancial.
*   **Baby Shelf Rule (SEC General Instruction I.B.6 of S-3/F-3):** 
    *   Si el float público de la empresa es **< $75 millones de dólares**, legalmente solo puede diluir mediante Shelf (ATM) un máximo de un tercio (33.3%) de su float público en un periodo móvil de 12 meses.
    *   El cálculo del Float Público para esta regla se basa en el precio de cierre más alto de los últimos 60 días.
    *   Edgie debe alertar si la empresa está buscando empujar el precio al alza de forma artificial únicamente para cruzar el umbral de los $75M de float y desbloquear la capacidad de dilución masiva.

#### F. Cumplimiento Nasdaq y Alertas de Deslistado
*   **Regla clásica de $1.00:** Deficiencia si cierra por debajo de $1.00 durante 30 días hábiles seguidos. Otorga 180 días de gracia. Requiere cerrar > $1.00 durante al menos 10 días seguidos para curar.
*   **Límite de Muerte Súbita ($0.10):** Si la acción cae por debajo de $0.10 durante 10 días hábiles consecutivos, entra en suspensión y deslistado inmediato sin derecho a apelación.
*   **Resto de Condiciones Nasdaq:**
    *   *Market Cap mínimo (MVLS):* Mantener al menos $35M.
    *   *Capital Social:* Stockholders' Equity mínimo de $2.5M.
    *   *Mínimo Float:* Valor de mercado de acciones públicas (MVPHS) por encima de $1M.
    *   *Volumen Float:* Al menos 500,000 acciones en el flotante de forma permanente.
    *   *Barrera de Entrada (Uplist/IPOs recientes):* Float requerido de $15M (antes $5M).

---

## 3. Comportamiento y Reglas de Edgie (Asistente Chat)

### 3.1 Carga del Ticker (Manejo del Loader)
*   **Problema actual:** El frontend genera mensajes repetitivos *"Edgie ha cargado exitosamente la base de conocimiento..."* más de 6 veces en el panel del chatbot porque las llamadas de carga de datos son progresivas y disparan eventos duplicados.
*   **Solución:** Modificar la lógica para que solo se muestre un indicador de carga en ejecución en el chat, y una única confirmación final cuando todo el conjunto de datos (Profile, Balance Sheet, Filings, News) haya resuelto completamente para ese ticker, o realizar un control por ID de ticker para no duplicar el mensaje si el ticker activo ya es el cargado.

### 3.2 Exclusión de Predicción por Acción del Precio
*   **Regla de Negocio:** Edgie no debe interpretar patrones de velas (ej: *Martillo invertido con gap alcista es distribución*) como señales de dilución directa.
*   **Permitido:** Estructuras de soporte/resistencia técnicos en relación con warrants, precios de ejercicio, techos de volatilidad o límites regulatorios de Nasdaq (ej: precio de cura del dólar).

### 3.3 Acceso Global de Edgie a Ticker Analysis (Siempre Disponible)
*   **Requerimiento:** Edgie debe poder realizar búsquedas y análisis de cualquier ticker en cualquier momento, independientemente de la página en la que se encuentre el usuario (ej: Backtester o Screener).
*   **Comportamiento:**
    1.  Se define una herramienta/acción global del asistente llamada `ticker.get_analysis`.
    2.  Si el usuario le solicita en el chat: *"Edgie, analiza MULN"* o *"Edgie, ¿cuál es el riesgo de dilución de AAPL?"* desde cualquier sección de la app, el asistente invocará automáticamente la herramienta `ticker.get_analysis`.
    3.  El manejador de la herramienta realizará consultas en segundo plano a las APIs del backend para recopilar Profile, Balance Sheet, Filings y News del ticker solicitado.
    4.  Los datos recuperados se inyectarán inmediatamente en el contexto conversacional del LLM, permitiendo a Edgie realizar el reporte completo de dilución y runner como si el usuario hubiera buscado el ticker en la vista principal de Ticker Analysis.

