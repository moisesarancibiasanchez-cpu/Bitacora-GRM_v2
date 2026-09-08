# Bitácora GRM v2

> Sistema híbrido que combina la **gestión estricta de un ITSM** con la **visualización ágil de un tablero Kanban**.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791)](https://www.postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D)](https://redis.io)
[![Celery](https://img.shields.io/badge/Celery-5.4-37814A)](https://docs.celeryq.dev)
[![HTMX](https://img.shields.io/badge/HTMX-1.9-3366cc)](https://htmx.org)

---

## 1. Descripción

MVP del **Módulo de Incidencias** que incluye las bases para futuros mantenedores de catálogos del sistema. Integra:

- **Validación estricta de transiciones** (matriz de estados + roles ITSM).
- **Auditoría obligatoria** de cada cambio (insert en `auditorias`).
- **Tablero Kanban con drag & drop** (SortableJS) sobre **server-rendered HTML** (Jinja2).
- **Refresco sin recarga de página** (HTMX outerHTML swap).
- **Procesamiento asíncrono** (Celery + Redis) para recálculo de SLAs y notificaciones.

## 2. Stack técnico

| Capa            | Tecnología                                         |
|-----------------|----------------------------------------------------|
| Backend         | Python 3.12 + FastAPI 0.115                        |
| ORM             | SQLAlchemy 2.0                                     |
| Base de datos   | PostgreSQL 16 (SQLite en modo demo)                |
| Async/Broker    | Redis 7 + Celery 5.4                               |
| Frontend        | Jinja2 + TailwindCSS (CDN) + HTMX 1.9 + SortableJS |
| Despliegue      | Docker Compose                                     |

## 3. Arquitectura del flujo Kanban (Drag & Drop)

```
┌──────────────┐   1. drag end      ┌────────────────────┐
│  SortableJS  │ ─────────────────▶ │  fetch PATCH /api  │
│  (frontend)  │                    │  /v1/tickets/{id}/ │
└──────────────┘                    │  estado            │
        ▲                           └────────┬───────────┘
        │ 3. outerHTML swap                  │ 2. valida
        │                                    ▼
┌──────────────┐                    ┌────────────────────┐
│  HTMX        │ ◀── fragment ──── │  FastAPI service   │
│  (respuesta) │                    │  TicketService     │
└──────────────┘                    └────────┬───────────┘
                                            │ ok
                                            ▼
                                ┌──────────────────────┐
                                │ 1. UPDATE ticket     │
                                │ 2. INSERT historial  │
                                │ 3. INSERT auditoria  │
                                │ 4. Celery.delay()    │
                                └──────────────────────┘
                                            │
                                            ▼
                                ┌──────────────────────┐
                                │  Redis               │
                                │  - recalcular_sla    │
                                │  - notificar         │
                                └──────────────────────┘
```

### Pasos detallados

1. El usuario arrastra una tarjeta con **SortableJS**.
2. Al soltarla, `kanban.js` envía un `PATCH /api/v1/tickets/{id}/estado` con `{estado_id, orden}`.
3. **FastAPI** valida la transición contra la tabla `transiciones_estado` (reglas ITSM).
4. Si la transición es válida:
   - UPDATE del ticket.
   - INSERT obligatorio en `historial_estados` y `auditorias`.
   - Se dispara una tarea **Celery** en segundo plano (no bloquea el request).
5. FastAPI devuelve el **fragmento HTML** de la tarjeta → HTMX hace `outerHTML` swap.
6. Si la validación falla (403/422), SortableJS revierte la posición y muestra un toast.

## 4. Estructura del proyecto

```
.
├── app/
│   ├── api/v1/                # Endpoints REST
│   │   ├── tickets.py         # PATCH /tickets/{id}/estado (CORE)
│   │   ├── estados.py         # CRUD de estados y transiciones
│   │   ├── catalogos.py       # Mantenedores de catálogos
│   │   ├── kanban.py          # Render HTML del tablero
│   │   └── deps.py            # Auth dependency
│   ├── core/
│   │   ├── config.py          # Settings (Pydantic)
│   │   ├── celery_app.py      # Instancia Celery + Beat schedule
│   │   └── security.py        # Hash + JWT
│   ├── db/
│   │   ├── base.py            # Base declarativa SQLAlchemy
│   │   ├── session.py         # Engine + SessionLocal
│   │   └── init_db.py         # Seed de datos
│   ├── models/                # Modelos SQLAlchemy
│   │   ├── usuario.py         # + roles
│   │   ├── estado.py          # + transiciones
│   │   ├── ticket.py          # + historial_estados
│   │   ├── auditoria.py
│   │   └── catalogo.py
│   ├── schemas/               # Pydantic schemas
│   ├── services/              # Lógica de negocio
│   │   ├── ticket_service.py  # Reglas ITSM (CORE)
│   │   ├── sla_service.py
│   │   └── auditoria_service.py
│   ├── tasks/                 # Tareas Celery
│   │   ├── sla_tasks.py
│   │   └── notification_tasks.py
│   ├── templates/             # Jinja2
│   │   ├── base.html
│   │   ├── kanban/
│   │   │   ├── index.html
│   │   │   └── partials/
│   │   │       ├── tarjeta.html
│   │   │       ├── card.py
│   │   │       └── column.py
│   │   ├── tickets/list.html
│   │   └── catalogos/index.html
│   ├── static/
│   │   ├── css/styles.css
│   │   └── js/
│   │       ├── kanban.js      # Lógica SortableJS + HTMX
│   │       └── htmx-events.js # Toasts
│   └── main.py                # Aplicación FastAPI
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

## 5. Modelo de datos (resumen)

```
usuarios ───< tickets >─── estados
   │            │              │
   │            │              └──< transiciones_estado >
   │            │                          │
   │            │                          └─ rol_requerido, requiere_comentario
   │            ├──< historial_estados >──┘
   │            └──< auditorias
catalogo_tipos ─< catalogo_items
        └─────────< tickets.datos_catalogo
```

### Reglas de validación (ITSM)

1. El usuario debe estar activo.
2. Debe existir una fila en `transiciones_estado` con el `estado_origen_id` y `estado_destino_id`.
3. El rol del usuario debe ser ≥ `rol_requerido` de la transición.
4. Si la transición tiene `requiere_comentario=True`, el body debe incluir `comentario` no vacío.
5. Estado destino ≠ estado actual.

## 6. Endpoints principales

| Método | Ruta                                        | Descripción                                        |
|--------|---------------------------------------------|----------------------------------------------------|
| GET    | `/kanban`                                   | Render del tablero (HTML)                          |
| PATCH  | `/api/v1/tickets/{id}/estado`               | **Cambio de estado desde Kanban (CORE)**          |
| POST   | `/api/v1/tickets`                           | Crear incidencia                                   |
| GET    | `/api/v1/tickets`                           | Listar tickets                                     |
| GET    | `/api/v1/estados`                           | Listar estados del flujo                           |
| GET    | `/api/v1/estados/transiciones`              | Matriz de transiciones                             |
| POST   | `/api/v1/estados`                           | Crear estado (admin)                               |
| GET    | `/api/v1/catalogos/tipos`                   | Listar tipos de catálogo                           |
| POST   | `/api/v1/catalogos/tipos`                   | Crear tipo (admin)                                 |
| GET    | `/api/v1/catalogos/{tipo_id}/items`         | Listar items                                       |
| POST   | `/api/v1/catalogos/{tipo_id}/items`         | Crear item                                         |
| GET    | `/docs`                                     | Swagger UI                                         |

## 7. Despliegue

### Producción con Docker Compose

```bash
git clone https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2.git
cd Bitacora-GRM_v2
cp .env.example .env
docker compose up -d
```

Servicios levantados:
- API: <http://localhost:8000>
- Documentación: <http://localhost:8000/docs>
- Tablero: <http://localhost:8000/kanban>
- PostgreSQL: localhost:5432
- Redis: localhost:6379

### Modo desarrollo (SQLite + Celery con eager)

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. (Opcional) Override BD a SQLite
export USE_SQLITE=true

# 3. Inicializar BD con datos semilla
python -m app.db.init_db

# 4. Arrancar FastAPI
uvicorn app.main:app --reload

# 5. (Opcional) Arrancar Celery en otra terminal
celery -A app.core.celery_app.celery_app worker --loglevel=info
celery -A app.core.celery_app.celery_app beat --loglevel=info
```

## 8. Usuarios de ejemplo (modo demo)

| Username | Password   | Rol               |
|----------|------------|-------------------|
| admin    | admin123   | Administrador     |
| lider    | lider123   | Agente Senior     |
| agente1  | agente123  | Agente            |
| usuario1 | user123    | Solicitante       |

> Pasa el header `X-User-Id: <id>` para simular la sesión en modo demo.

## 9. Roadmap

- [ ] CRUD completo de catálogos (UI)
- [ ] Comentarios en tickets
- [ ] Adjuntos / archivos
- [ ] Reportes y dashboards
- [ ] WebSockets para actualizaciones en vivo
- [ ] Notificaciones email reales
- [ ] Autenticación OAuth2

## 10. Licencia

MIT
