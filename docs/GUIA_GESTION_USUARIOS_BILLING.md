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

## Preguntas frecuentes

- **¿Cuándo lo nota el usuario?** En su **próximo login**. Si ya está dentro,
  que recargue o vuelva a entrar.
- **¿Y si ya empezó su prueba de 7 días?** El cambio a "preferencial" aplica en su
  **próximo checkout**; no alarga una prueba que Stripe ya arrancó. Para gratis
  (cortesía) sí aplica siempre (le quita el muro).
- **¿Puedo poner varios de golpe?** Sí: `--add a@x.com,b@y.com,c@z.com`.
- **¿Se puede probar sin escribir?** Sí, añade `--dry-run` al final.
- **¿Dónde se guarda?** En la base de datos de billing de producción
  (`/data/btt_prod_billing/edgecute_billing.sqlite`, en disco persistente).
