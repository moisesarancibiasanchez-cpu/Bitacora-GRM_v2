# ITSM/Kanban MVP

MVP de un **sistema híbrido** que combina la gestión estricta de un ITSM con
la visualización ágil de un tablero Kanban.

## Stack técnico

| Capa              | Tecnología                            |
| ----------------- | ------------------------------------- |
| Backend           | Python 3.12 + **FastAPI**             |
| ORM / DB          | **SQLAlchemy 2.0** + **PostgreSQL**   |
| Async / Cola      | **Celery** + **Redis**                |
| Frontend          | **Jinja2** (SSR) + **TailwindCSS** + **HTMX** + **SortableJS** |
| Auth              | JWT en cookie HttpOnly + bcrypt       |

## Arquitectura de flujo (drag → drop → BD)

```
[SortableJS]   Usuario arrastra tarjeta
       │
       ▼
[HTMX]         POST /api/v1/kanban/tickets/{id}/mover
               body: { estado_id, posicion, comentario }
       │
       ▼
[FastAPI]      Valida:
               1. Existencia de Transicion(origen, destino) en BD
               2. Rol del usuario ≥ rol_requerido
               3. Si requiere_comentario → comentario no vacío
       │
       ├──[422/403]→ Devuelve HTML con HX-Reswap:none → tarjeta vuelve
       │
       ▼
[SQLAlchemy]   UPDATE ticket
               INSERT auditoria_eventos  ◄── OBLIGATORIO
       │
       ▼
[Celery .delay]  recalcular_sla_ticket  (background)
                 notificar_cambio_estado (background)
       │
       ▼
[FastAPI]      Render fragmento _tarjeta.html
       │
       ▼
[HTMX]         swap outerHTML → nueva tarjeta en columna destino
```

## Estructura del proyecto

```
itsm_kanban_mvp/
├── app/
│   ├── main.py                  # Entry point FastAPI
│   ├── api/v1/
│   │   ├── auth.py              # /auth/login, /auth/logout
│   │   ├── deps.py              # get_current_user (cookie JWT)
│   │   ├── kanban.py            # /kanban (vista), /api/v1/kanban/...
│   │   ├── tickets.py           # /tickets/nuevo, /tickets/{id}/auditoria
│   │   └── catalogos.py         # /api/v1/catalogos/{estados,sla,items}
│   ├── core/
│   │   ├── config.py            # Pydantic Settings (.env)
│   │   ├── security.py          # bcrypt + JWT
│   │   └── celery_app.py        # Celery factory
│   ├── db/
│   │   ├── session.py           # Engine + Base SQLAlchemy
│   │   └── init_db.py           # create_all + seeds
│   ├── models/
│   │   ├── usuario.py           # Usuario, RolUsuario
│   │   ├── estado.py            # Estado, CategoriaEstado
│   │   ├── transicion.py        # Transicion, RolRequerido
│   │   ├── ticket.py            # Ticket, PrioridadTicket
│   │   ├── auditoria.py         # AuditoriaEvento, TipoEvento
│   │   ├── sla.py               # SLAPolitica
│   │   └── catalogo.py          # CatalogoItem, TipoCatalogo
│   ├── schemas/                 # (vacío - usar modelos directos)
│   ├── services/
│   │   └── kanban_service.py    # Validación ITSM + movimiento
│   ├── tasks/
│   │   └── kanban_tasks.py      # Celery: recalcular_sla, notificar
│   ├── static/                  # CSS/JS
│   └── templates/
│       ├── base.html            # Layout con Tailwind + HTMX + SortableJS
│       ├── auth/login.html
│       └── kanban/
│           ├── tablero.html     # Tablero Kanban
│           ├── _tarjeta.html    # Fragmento HTMX de una tarjeta
│           └── _auditoria.html  # Fragmento HTMX de auditoría
├── tests/
│   └── test_kanban_service.py   # Tests pytest
├── docs/
│   └── ARQUITECTURA.md
├── requirements.txt
├── .env.example
└── README.md
```

## Modelo de datos (entidades principales)

- **Usuario**: cuenta con rol (`SOLICITANTE`, `AGENTE`, `AGENTE_SENIOR`,
  `ADMINISTRADOR`, `OBSERVADOR`).
- **Estado**: columna del Kanban. Tiene `orden`, `categoria`, `color`, flags
  `es_inicial` y `es_final`.
- **Transicion**: regla `(origen_id, destino_id) → rol_requerido`.
  Implementa la matriz legal de cambios de estado.
- **Ticket**: la incidencia. Tiene `codigo`, `titulo`, `estado_id`, `prioridad`,
  `posicion` (dentro de la columna), `creador_id`, `asignado_id`.
- **AuditoriaEvento**: append-only. **Obligatorio** en cada cambio de estado,
  reasignación, comentario, etc.
- **SLAPolitica**: `prioridad → minutos_resolucion`.
- **CatalogoItem**: base extensible para futuros mantenedores (TipoTicket,
  Categoría, Módulo, Etiqueta).

## Instalación local

```bash
cd itsm_kanban_mvp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1) Crear la BD PostgreSQL
createdb itsm_kanban

# 2) Configurar variables de entorno
cp .env.example .env
# editar .env con tus valores reales

# 3) Inicializar esquema + sembrar datos
python -m app.db.init_db

# 4) Levantar el backend (FastAPI)
uvicorn app.main:app --reload --port 8000

# 5) En otra terminal: Celery worker
celery -A app.core.celery_app worker --loglevel=info

# 6) En otra terminal: Celery beat (cron)
celery -A app.core.celery_app beat --loglevel=info

# 7) (Opcional) Redis local
redis-server
```

Abrir <http://localhost:8000/kanban> y autenticarse con `admin / admin123`.

## Pruebas

```bash
pytest tests/ -v
```

Los tests usan SQLite en memoria, no requieren PostgreSQL.

## Endpoints principales

| Método | Path                                            | Descripción                              |
| ------ | ----------------------------------------------- | ---------------------------------------- |
| GET    | `/auth/login`                                   | Formulario de login                      |
| POST   | `/auth/login`                                   | Autentica, setea cookie JWT, redirige    |
| POST   | `/auth/logout`                                  | Limpia cookie                            |
| GET    | `/`                                             | Redirige a `/kanban`                     |
| GET    | `/kanban`                                       | Vista HTML del tablero                   |
| POST   | `/api/v1/kanban/tickets/{id}/mover`             | **Mueve ticket** (HTMX + validación ITSM) |
| GET    | `/api/v1/kanban/columnas`                       | JSON con todas las columnas              |
| POST   | `/tickets/nuevo`                                | Crea un ticket nuevo                     |
| GET    | `/tickets/{id}/auditoria`                       | Fragmento HTML de auditoría              |
| GET    | `/api/v1/catalogos/estados`                     | Estados + transiciones permitidas        |
| GET    | `/api/v1/catalogos/sla`                         | Políticas SLA                            |
| GET    | `/api/v1/catalogos/items?tipo=MODULO`           | Catálogo de módulos                      |

## Reglas ITSM (núcleo del sistema)

1. **No toda transición es legal**: la tabla `transiciones` define las reglas.
2. **El rol importa**: cada transición exige un `rol_requerido` mínimo
   (`AGENTE`, `AGENTE_SENIOR`, `ADMINISTRADOR`).
3. **Ciertas transiciones exigen comentario**: ej. cerrar un ticket, cancelar
   uno bloqueado.
4. **Auditoría obligatoria**: cada cambio de estado inserta un evento
   `AuditoriaEvento` inmutable.
5. **Cálculo de SLA asíncrono**: al cambiar de estado se encola una tarea
   Celery que recalcula el SLA del ticket según la política de su prioridad.

## Licencia

MIT
