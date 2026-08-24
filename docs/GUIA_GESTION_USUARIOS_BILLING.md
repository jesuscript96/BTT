# Guía sencilla — gestionar accesos de usuarios (billing)

> Para dar/quitar **admin**, **acceso gratis (cortesía)** o **días de prueba
> preferenciales** a un usuario, **por email**. No hace falta saber su ID interno:
> el cambio se aplica solo la próxima vez que el usuario entra (login).

## Idea en 30 segundos

- Todo se controla por **email**. Añades el email a una lista y listo.
- **3 listas**:
  1. **Admin** → acceso total, sin pagar, sin muro. (Interno / equipo.)
  2. **Cortesía (gratis)** → acceso total, gratis, para siempre, sin tarjeta.
  3. **Preferencial** → prueba más larga (p. ej. **14 días** en vez de 7). El
     usuario **sí** pone tarjeta, pero no se le cobra hasta que pasen esos días.
- Se aplica en el **próximo login** del usuario (no hay que reiniciar nada).
- Es **reversible**: quitas el email de la lista y vuelve a lo normal.
- **Precedencia**: Admin gana a Cortesía, y Cortesía gana a Preferencial. Si
  alguien es "gratis", ponerlo también en "preferencial" no sirve de nada.

---

## Cómo se ejecuta

Los comandos corren **dentro del contenedor del backend de producción** (Coolify).
Cada línea empieza localizando el contenedor (su nombre cambia en cada despliegue,
por eso NO se escribe a mano):

```bash
# 1) entrar al servidor
ssh root@176.9.117.155

# 2) localizar el contenedor del backend (guardar en la variable C)
C=$(docker ps --format '{{.Names}}' | grep '^kvcfvkb' | head -1)
echo "contenedor: $C"
```

A partir de ahí, se usan estos comandos (todos aceptan varios emails separados por
coma, y `--dry-run` para previsualizar sin escribir).

### A) Dar acceso GRATIS (cortesía)
```bash
docker exec $C sh -c 'cd /app && /opt/venv/bin/python -m scripts.comp_emails --add correo@ejemplo.com --granted-by jesus'
```

### B) Dar/EXTENDER días de prueba preferenciales (p. ej. 14)
```bash
docker exec $C sh -c 'cd /app && /opt/venv/bin/python -m scripts.pref_trial_emails --add correo@ejemplo.com --days 14 --granted-by jesus'
```
> `--days` va de 1 a 30. Ese número es el que verá el usuario tanto en la pantalla
> de registro como en el primer cobro (es dinámico, no dirá 7).

### C) Hacer a alguien ADMIN
```bash
docker exec $C sh -c 'cd /app && /opt/venv/bin/python -m scripts.admin_emails --add correo@ejemplo.com --granted-by jesus'
```

### D) QUITAR de una lista (revertir)
```bash
docker exec $C sh -c 'cd /app && /opt/venv/bin/python -m scripts.comp_emails       --remove correo@ejemplo.com'
docker exec $C sh -c 'cd /app && /opt/venv/bin/python -m scripts.pref_trial_emails --remove correo@ejemplo.com'
docker exec $C sh -c 'cd /app && /opt/venv/bin/python -m scripts.admin_emails      --remove correo@ejemplo.com'
```

### E) VER quién está en cada lista
```bash
docker exec $C sh -c 'cd /app && /opt/venv/bin/python -m scripts.comp_emails       --list'
docker exec $C sh -c 'cd /app && /opt/venv/bin/python -m scripts.pref_trial_emails --list'
docker exec $C sh -c 'cd /app && /opt/venv/bin/python -m scripts.admin_emails      --list'
```

---

## Ejemplos reales (los dos casos de hoy)

**Extender la prueba de 7 a 14 días a `sebasocampo2104@gmail.com`:**
```bash
C=$(docker ps --format '{{.Names}}' | grep '^kvcfvkb' | head -1)
docker exec $C sh -c 'cd /app && /opt/venv/bin/python -m scripts.pref_trial_emails --add sebasocampo2104@gmail.com --days 14 --granted-by jesus'
```

**Dar acceso gratuito a `avalerisabate@gmail.com`:**
```bash
C=$(docker ps --format '{{.Names}}' | grep '^kvcfvkb' | head -1)
docker exec $C sh -c 'cd /app && /opt/venv/bin/python -m scripts.comp_emails --add avalerisabate@gmail.com --granted-by jesus'
```

---

## ⭐ Días de prueba: ¿la persona YA está suscrita o no? (los 2 casos)

Esta es la parte que más confunde. La **lista de preferenciales** solo decide los
días **en el momento en que el usuario pone su tarjeta** (el "checkout"). Por eso:

**Caso 1 — TODAVÍA no ha puesto tarjeta** (no se ha suscrito)
- Basta con **añadirlo a la lista** de preferenciales con los días que quieras.
- Cuando ponga su tarjeta, Stripe le dará esos días automáticamente.
- **En Stripe no hay que hacer nada.**
- *Ejemplo real:* `sebasocampo2104@gmail.com` no estaba suscrito → lo metimos a la
  lista de 14 días y listo.

**Caso 2 — YA se suscribió / ya está dentro de su prueba**
- La lista **ya no le sirve** (su checkout ya ocurrió con los 7 días por defecto).
- Para darle más días hay que **extender su prueba directamente en Stripe**
  (mover la fecha de fin de prueba). Esto **lo hacemos nosotros con un comando**.
- Extender = **mover hacia adelante la fecha del primer cobro**. Si le quedaban
  3 días y sumas 7, pasa a tener 10; no se reinicia, no rompe nada, la tarjeta
  sigue igual y el usuario ve la fecha nueva en su panel.
- *Ejemplo real:* `david573tapia@gmail.com` ya se había suscrito con 7 días → **le
  extendimos la prueba +7 días en Stripe** (queda en 14, hasta el 7-sep). **Ya está
  resuelto; no hay nada pendiente para él.**

**Regla rápida:** ¿aún no puso tarjeta? → **lista**. ¿ya está en la prueba? →
**extender en Stripe** (comando de abajo).

### Cómo extender una prueba EN CURSO (Caso 2)

Se hace desde el contenedor de prod, verificando SIEMPRE el email del cliente antes
de tocar su suscripción. Ejemplo (extender +7 días la sub de un usuario):
```bash
C=$(docker ps --format '{{.Names}}' | grep '^kvcfvkb' | head -1)
docker exec -i $C /opt/venv/bin/python - <<'PY'
import os, httpx
sk = os.environ['STRIPE_SECRET_KEY']; auth = (sk, '')
EMAIL = 'correo@ejemplo.com'   # <-- el usuario a extender
DIAS  = 7                       # <-- días a sumar a lo que le quede
# localizar su suscripción por email
subs = httpx.get('https://api.stripe.com/v1/subscriptions',
                 params={'limit':100,'status':'all','expand[]':'data.customer'},
                 auth=auth, timeout=30).json()['data']
match = [s for s in subs if ((s.get('customer') or {}).get('email') or '').lower() == EMAIL.lower()]
assert len(match) == 1, f'esperaba 1 sub para {EMAIL}, encontré {len(match)}'
s = match[0]; new_end = int(s['trial_end']) + DIAS*24*3600
r = httpx.post(f"https://api.stripe.com/v1/subscriptions/{s['id']}",
               data={'trial_end': str(new_end), 'proration_behavior':'none'},
               auth=auth, timeout=30); r.raise_for_status()
print('OK, nuevo trial_end (unix):', r.json()['trial_end'])
PY
```
> Solo funciona si el usuario está **en prueba** (`status = trialing`). Si ya está
> pagando (`active`), no es una prueba: habría que ofrecerle otra cosa (cupón).

## Preguntas frecuentes

- **¿Cuándo lo nota el usuario?** En su **próximo login**. Si ya está dentro,
  que recargue o vuelva a entrar.
- **¿Y si ya empezó su prueba de 7 días?** Ver el **Caso 2** de arriba: la lista no
  alarga una prueba ya arrancada; hay que **extenderla en Stripe** (comando). Para
  gratis (cortesía) sí aplica siempre en el próximo login (le quita el muro).
- **¿Puedo poner varios de golpe?** Sí: `--add a@x.com,b@y.com,c@z.com`.
- **¿Se puede probar sin escribir?** Sí, añade `--dry-run` al final.
- **¿Dónde se guarda?** En la base de datos de billing de producción
  (`/data/btt_prod_billing/edgecute_billing.sqlite`, en disco persistente).
