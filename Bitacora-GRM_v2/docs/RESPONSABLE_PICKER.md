# Asignar responsable a columnas y notificación por email

## Resumen

Cuando un ticket cae en una columna (estado) que tiene un **responsable** asignado,
ese usuario recibe automáticamente:

1. Una **notificación in-app** (visible en su bandeja /campana).
2. Un **email** (si hay transporte configurado: Resend o SMTP).
3. Un registro en la **bitácora de auditoría**.

## Cómo asignar un responsable a una columna

1. Entra al tablero Kanban con rol **Administrador**.
2. En el header de la columna, haz clic en el botón `+ responsable`.
3. Se desplegará un `<select>` con todos los usuarios **activos** del sistema.
4. Selecciona uno — el cambio se guarda automáticamente (`onchange`).
5. Verás el avatar/nombre del responsable en el header de la columna.

### ¿Por qué el combo aparece vacío?

Si el combo solo muestra "— Sin responsable —", abre en el navegador:

```
GET /api/v1/estados/diagnostico/responsables
```

Este endpoint (requiere login) devuelve:

```json
{
  "usuarios": {
    "total": 6,
    "activos": 5,
    "inactivos": 1,
    "alerta": "OK"
  },
  "estados": {
    "total": 12,
    "con_responsable": 3,
    "sin_responsable": 9
  },
  "email": {
    "RESEND_API_KEY_configured": true,
    "SMTP_HOST": null,
    "SMTP_FROM": "no-reply@tudominio.cl",
    "transporte_activo": "resend"
  },
  "solicitado_por": "admin"
}
```

Posibles causas del combo vacío:

| Caso | Solución |
|------|----------|
| `usuarios.activos = 0` pero `total > 0` | Activa al menos un usuario en `/usuarios` |
| `usuarios.total = 0` | Crea el primer usuario (desde CLI o seed) |
| No eres Administrador | El sistema rechaza con 403 ("Solo el rol Administrador puede asignar responsables de columna") |
| `alerta = "OK"` y aun así vacío | Probable caché de HTMX: refresca la página |

**Fallback implementado (v2):** si NO hay usuarios activos pero SÍ hay inactivos,
el combo ahora muestra los inactivos con la etiqueta `(inactivo)` y un banner
ámbar indicando que deben activarse.

## Configurar envío de emails

El servicio `app/services/email_service.py` soporta 3 transportes en cadena
de prioridad:

### 1) Resend HTTP API (recomendado en Railway/Render/Heroku)

```bash
# En tu .env o variables de Railway
RESEND_API_KEY=re_XXXXXXXXXXXXXXXXXXXXXXXXXX
SMTP_FROM=no-reply@tudominio.com
```

- Puerto 443 (HTTPS), sin problemas de firewall.
- Requiere dominio verificado en [resend.com](https://resend.com).

### 2) SMTP clásico

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu_cuenta@gmail.com
SMTP_PASSWORD=tu_app_password
SMTP_FROM=tu_cuenta@gmail.com
SMTP_USE_TLS=true
```

### 3) Log local / Dev Inbox (fallback)

Si **ninguna** de las anteriores está configurada, los correos se persisten en:

- `tmp/app.email.log` (1 línea JSON por correo)
- `/dev/inbox` (consultable desde el navegador con HTMX)

Esta cadena garantiza que el flujo NUNCA rompa por falta de SMTP.

## Verificar el flujo end-to-end

Hay 3 scripts de prueba incluidos en la raíz del repo:

| Script | Qué valida |
|--------|------------|
| `test_responsable_flow.py` | Picker + PATCH + notificación directa |
| `test_responsable_flow_v2.py` | Picker (caso normal), PATCH, endpoint diagnóstico, fallback a inactivos |
| `test_picker_fallback.py` | Picker cuando solo hay inactivos |
| `test_end_to_end_flow.py` | Flujo completo: login → diagnóstico → cambiar_estado → in-app → email log |

Para ejecutar:

```bash
source .venv-test/bin/activate
python test_end_to_end_flow.py
```

## Cambios realizados en este commit

### `app/api/v1/estados.py`

1. **Picker defensivo**: si no hay usuarios activos pero sí inactivos,
   ahora se muestran los inactivos con sufijo `(inactivo)` y un banner
   ámbar de ayuda.
2. **Banner de ayuda** cuando NO hay usuarios en el sistema, con un
   link directo a `/usuarios` para crear el primero.
3. **Nuevo endpoint de diagnóstico**:
   `GET /api/v1/estados/diagnostico/responsables` —
   devuelve el estado de usuarios, columnas y configuración de email.
