# Guía: haz tu componente "asistible"

Regla de oro: **si un humano puede hacerlo con la UI, debe existir una acción registrada equivalente — y ninguna acción debe poder hacer algo que la UI no permita.**

## Pasos

### 1. Define el schema en `lib/assistant/schemas.ts`

```ts
export const MiAccionSchema: JSONSchema = {
    type: 'object',
    description: 'Qué hace, en español.',
    properties: {
        campo: { type: 'number', minimum: 0, description: 'Unidades, rango y semántica. El LLM solo sabe lo que pongas aquí.' },
        modo: { type: 'string', enum: ['a', 'b'], description: 'Opciones con su significado.' },
    },
    required: ['campo'],
    additionalProperties: false,
};
```

Las descripciones por campo son lo que hace que el modelo rellene bien los formularios: escribe unidades, formatos (`YYYY-MM-DD`), valores por defecto y ejemplos.

### 2. Registra la acción en el componente que posee el estado

```tsx
import { useAssistantAction, useAssistantContext } from '@/lib/assistant';
import { MiAccionSchema } from '@/lib/assistant';

useAssistantAction({
    name: 'pagina.mi_accion',            // dot-namespace por página/área
    description: 'Qué hace y qué verá el usuario en pantalla. Menciona la acción siguiente si forma parte de un flujo.',
    parameters: MiAccionSchema,
    confirm: 'auto',                     // 'confirm' si ejecuta/guarda; 'danger' si borra
    handler: (args) => {
        // Aplica al estado con los MISMOS setters/funciones que usa la UI manual.
        // Devuelve errores accionables: incluye candidatos/valores válidos.
        if (algoNoResuelve) return { ok: false, error: `No existe X. Disponibles: ${lista}` };
        setCampo(Number(args.campo));
        return { ok: true, result: { applied: args } };
    },
});
```

Notas:
- El hook registra al montar y desregistra al desmontar: el manifest del LLM siempre refleja la página actual.
- El handler ve estado fresco (se guarda en un ref), pero los `parameters` se asumen estables por montaje.
- No hace falta gestionar la confirmación: el ChatBot muestra la tarjeta según `confirm` antes de llamar a tu handler.

### 3. Publica el contexto relevante

```tsx
useAssistantContext('pagina.estado', () => ({
    // Solo lo que el bot necesita para razonar (~1-2 KB máx).
    // Nada de datasets enteros ni objetos con ciclos.
    seleccion: selectedId,
    resumen: resumenLegible,
}));
```

El snapshot de todos los contextos se inyecta en el system prompt en cada turno (truncado a ~6 KB en total), así que sé selectivo.

### 4. Añade casos de eval

Añade 2-3 frases reales a `docs/assistant/evals/casos.json` con las tool calls esperadas. Sirven como regresión manual al cambiar prompts o modelo.

## Anti-patrones

- ❌ Lógica nueva en el handler que la UI no tiene (el bot no debe poder más que el usuario).
- ❌ `confirm: 'auto'` en algo que gasta dinero/tiempo o es irreversible.
- ❌ Errores tipo `"error"` sin contexto — el LLM no puede autocorregirse con eso.
- ❌ Publicar en contexto objetos gigantes "por si acaso".
- ❌ Registrar acciones en componentes que no poseen el estado (acaban desincronizadas).
