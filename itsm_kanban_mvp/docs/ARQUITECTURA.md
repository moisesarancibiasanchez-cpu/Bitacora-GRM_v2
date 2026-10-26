# Arquitectura — ITSM/Kanban MVP

## Diagrama de capas

```
┌────────────────────────────────────────────────────────────────────┐
│  Browser (HTML renderizado por Jinja2)                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                         │
│  │ Tailwind │  │  HTMX    │  │ Sortable │                         │
│  │  (CSS)   │  │ (fetch)  │  │   (DnD)  │                         │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                         │
│       │              │             │                              │
│       │   POST /api/v1/kanban/tickets/{id}/mover                  │
│       │   { estado_id, posicion, comentario }                      │
└───────┼──────────────┼─────────────┼───────────────────────────────┘
        │              │             │
        ▼              ▼             ▼
┌────────────────────────────────────────────────────────────────────┐
│  FastAPI                                                           │
│  ┌──────────────────┐  ┌──────────────────┐                        │
│  │  /api/v1/kanban  │  │  /api/v1/auth    │                        │
│  │  /tickets        │  │  /catalogos      │                        │
│  └────────┬─────────┘  └────────┬─────────┘                        │
│           │                     │                                  │
│           ▼                     ▼                                  │
│  ┌──────────────────────────────────────────┐                      │
│  │          Services (reglas ITSM)          │                      │
│  │   kanban_service.mover_ticket(...)       │                      │
│  └────────┬─────────────────────────────────┘                      │
│           │                                                        │
└───────────┼────────────────────────────────────────────────────────┘
            │
   ┌────────┴────────┬────────────────────┐
   ▼                 ▼                    ▼
┌────────┐    ┌──────────────┐    ┌──────────────┐
│  PG    │    │  SQLAlchemy  │    │   Celery     │
│ (BD)   │◄───┤  2.0 (ORM)   │    │  (Redis)     │
│        │    │              │───►│              │
│        │    │              │    │ recalcular   │
│        │    │              │    │  _sla_ticket │
│        │    │              │    │ notificar... │
└────────┘    └──────────────┘    └──────────────┘
```

## Modelo de datos (ER simplificado)

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│   Usuario    │ 1     * │   Ticket     │ *     1 │   Estado     │
│──────────────│◄────────│──────────────│────────►│──────────────│
│ id           │ crea    │ id           │  en     │ id           │
│ username     │         │ codigo       │         │ nombre       │
│ email        │ 1     * │ titulo       │ 1     * │ categoria    │
│ rol          │◄────────│ estado_id    │◄────────│ es_inicial   │
│ activo       │ asignado│ prioridad    │ origen  │ es_final     │
└──────────────┘         │ creador_id   │         │ color        │
                         │ asignado_id  │         │ orden        │
                         │ posicion     │         └──────┬───────┘
                         │ fecha_vto    │                │
                         └──────┬───────┘                │
                                │                        │
                                │ 1                  1   │
                                │                        │
                                ▼ *                  *   ▼
                         ┌──────────────┐         ┌──────────────┐
                         │ AuditoriaE.  │         │ Transicion   │
                         │──────────────│         │──────────────│
                         │ ticket_id    │         │ origen_id    │
                         │ tipo         │         │ destino_id   │
                         │ actor_id     │         │ rol_requerido│
                         │ valor_ant.   │         │ requiere_com │
                         │ valor_nvo    │         │ activo       │
                         │ created_at   │         └──────────────┘
                         └──────────────┘
```

## Patrón de auditoría

El sistema usa el patrón **append-only log** para auditoría:

1. Cualquier cambio que afecte al ticket (estado, asignación, prioridad,
   comentario, SLA) genera un `AuditoriaEvento`.
2. La tabla NO tiene `updated_at` y NO se borran filas jamás.
3. Cada evento guarda: `tipo`, `actor_id`, `actor_username`, `valor_anterior`,
   `valor_nuevo`, `comentario`, `created_at`.
4. Esto permite reconstruir el historial completo del ticket y detectar
   manipulaciones.
