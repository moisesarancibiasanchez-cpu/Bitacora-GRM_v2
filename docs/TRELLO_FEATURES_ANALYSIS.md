# Análisis Exhaustivo de Funcionalidades de Trello

**Proyecto:** Bitácora GRM — Sistema Híbrido ITSM + Kanban
**Versión:** 1.0 — Auditoría completa de features estilo Trello
**Fecha:** 2026-09-09

---

## 1. Funcionalidades Básicas (Trello Free)

### 1.1 Tableros y Tarjetas
| # | Funcionalidad | Estado en Bitácora | Implementación |
|---|---|---|---|
| 1.1.1 | Crear tableros | ✅ Implementado | `POST /api/v1/tableros` con nombre, descripción, espacio, visibilidad, color |
| 1.1.2 | Editar/archivar/restaurar tableros | ✅ Implementado | `PATCH /api/v1/tableros/{id}`, `POST /archivar`, `POST /restaurar` |
| 1.1.3 | Eliminar tableros | ⚠️ Soft delete vía archivado | Solo archivado (mejor práctica) |
| 1.1.4 | Listas/Columnas (estados) por tablero | ✅ Implementado | Cada `Estado` tiene `tablero_id` |
| 1.1.5 | Crear/editar/eliminar listas | ⚠️ Solo vía catálogo | Estados se gestionan en catálogo, no inline |
| 1.1.6 | Arrastrar y soltar tarjetas entre columnas | ✅ Implementado | SortableJS + `PATCH /tickets/{id}/estado` |
| 1.1.7 | Reordenar tarjetas dentro de columna | ✅ Implementado | SortableJS + `orden` field |
| 1.1.8 | Crear tarjetas (tickets) | ✅ Implementado | `POST /tickets/crear` |
| 1.1.9 | Editar tarjetas (título, descripción) | ✅ Implementado | Modal detalle + `PATCH /tickets/{id}` |
| 1.1.10 | Archivar/restaurar tickets | ✅ Implementado | `archivado` field en modelo Ticket |
| 1.1.11 | Duplicar tarjeta | ❌ **FALTA** | Endpoint no existe |
| 1.1.12 | Mover tarjeta a otro tablero | ⚠️ Parcial | Existe `tablero_id` pero no endpoint público |
| 1.1.13 | Suscribirse a tarjeta (Watch) | ✅ Implementado | `POST /api/v1/watch` |
| 1.1.14 | Etiquetas (Labels) | ✅ Implementado | Modelo `Etiqueta` + `POST /tickets/{id}/etiquetas/{et}` |
| 1.1.15 | Filtros por etiqueta | ❌ **FALTA UI** | Endpoint existe, falta panel en Kanban |
| 1.1.16 | Filtros por asignado | ❌ **FALTA UI** | Falta panel en Kanban |
| 1.1.17 | Filtros por fecha de vencimiento | ❌ **FALTA UI** | Falta panel en Kanban |
| 1.1.18 | Búsqueda de tarjetas | ❌ **FALTA** | No hay endpoint de búsqueda global |

### 1.2 Miembros y Asignaciones
| # | Funcionalidad | Estado | Implementación |
|---|---|---|---|
| 1.2.1 | Asignar miembros a tarjeta | ✅ Implementado | `asignado_id` en Ticket |
| 1.2.2 | Asignar múltiples miembros | ⚠️ Solo uno | Solo `asignado_id` (no hay tabla de muchos-a-muchos) |
| 1.2.3 | Invitar miembros a espacio | ✅ Implementado | `POST /api/v1/espacios/{id}/miembros/{uid}` |
| 1.2.4 | Roles de usuario (admin/editor/lector) | ✅ Implementado | `RolUsuario` enum |
| 1.2.5 | Avatar / iniciales del usuario | ❌ **FALTA** | No hay componente de avatar |
| 1.2.6 | @menciones en comentarios | ⚠️ Schema existe | Falta parser y notificación |

### 1.3 Comentarios y Actividad
| # | Funcionalidad | Estado | Implementación |
|---|---|---|---|
| 1.3.1 | Comentarios en tarjeta | ✅ Implementado | `POST /tickets/{id}/comentarios` |
| 1.3.2 | Editar/eliminar comentarios | ✅ Implementado | `PATCH /comentarios/{id}`, `DELETE` |
| 1.3.3 | Comentarios internos (privados) | ✅ Implementado | `es_interno` field |
| 1.3.4 | Markdown en comentarios | ✅ Implementado | `MarkdownParser` + `POST /api/v1/markdown/renderizar` |
| 1.3.5 | Reacciones emoji | ✅ Implementado | `POST /api/v1/reacciones/toggle` |
| 1.3.6 | Historial de actividad | ✅ Implementado | Tabla `auditoria` |
| 1.3.7 | Menciones @usuario | ⚠️ Parcial | Schema existe, parser no automático |

### 1.4 Adjuntos
| # | Funcionalidad | Estado | Implementación |
|---|---|---|---|
| 1.4.1 | Subir archivos | ✅ Implementado | `POST /tickets/{id}/adjuntos` |
| 1.4.2 | Vista previa de imágenes | ❌ **FALTA** | Se guarda pero no hay preview |
| 1.4.3 | Eliminar adjuntos | ⚠️ Endpoint existe | Falta UI en modal |
| 1.4.4 | Descargar adjuntos | ✅ Implementado | `GET /tickets/{id}/adjuntos/{adj_id}/archivo` |
| 1.4.5 | Cover (imagen de portada) | ❌ **FALTA** | No hay cover de tarjeta |

### 1.5 Checklists
| # | Funcionalidad | Estado | Implementación |
|---|---|---|---|
| 1.5.1 | Crear checklists | ✅ Implementado | `POST /tickets/{id}/checklists` |
| 1.5.2 | Agregar items | ✅ Implementado | `POST /checklists/{id}/items` |
| 1.5.3 | Marcar completado | ✅ Implementado | `PATCH /checklist-items/{id}` |
| 1.5.4 | Progreso (X de Y) | ⚠️ Solo textual | Falta barra de progreso visual |
| 1.5.5 | Convertir a tarjeta | ❌ **FALTA** | No existe conversión |
| 1.5.6 | Asignar item a miembro | ✅ Implementado | `asignado_id` field |

---

## 2. Funcionalidades Premium (Trello Standard / Premium / Enterprise)

### 2.1 Vistas Multidimensionales
| # | Funcionalidad | Estado | Implementación |
|---|---|---|---|
| 2.1.1 | Vista Kanban (Board) | ✅ Implementado | `/kanban` |
| 2.1.2 | Vista Timeline (Gantt) | ✅ Implementado | `/vistas/timeline` |
| 2.1.3 | Vista Calendario | ✅ Implementado | `/vistas/calendario` |
| 2.1.4 | Vista Tabla | ✅ Implementado | `/vistas/tabla` |
| 2.1.5 | Vista Dashboard | ❌ **FALTA** | Métricas agregadas |
| 2.1.6 | Vista Mapa | ❌ **FALTA** | No hay geolocalización |
| 2.1.7 | Cambio de vista rápido | ✅ Implementado | Dropdown "Vistas" en nav |

### 2.2 Automatizaciones (Butler)
| # | Funcionalidad | Estado | Implementación |
|---|---|---|---|
| 2.2.1 | Reglas basadas en eventos | ✅ Implementado | `ReglaAutomatizacion` + disparadores |
| 2.2.2 | Botones de tarjeta/tablero | ✅ Implementado | `BotonTarjeta` |
| 2.2.3 | Comandos programados (cron) | ✅ Implementado | `ComandoProgramado` + cron |
| 2.2.4 | UI de creación de reglas | ❌ **FALTA** | Solo listado, no hay modal crear regla |
| 2.2.5 | Editor visual de reglas | ❌ **FALTA** | No hay editor drag&drop |
| 2.2.6 | Calendario de comandos | ⚠️ Solo lista | Falta vista de próximos |
| 2.2.7 | Historial de ejecuciones | ✅ Implementado | `EjecucionComando`, `EjecucionBoton` |

### 2.3 Power-Ups / Integraciones
| # | Funcionalidad | Estado | Implementación |
|---|---|---|---|
| 2.3.1 | Slack/Microsoft Teams | ❌ **FALTA** | No hay integraciones |
| 2.3.2 | Google Drive / Dropbox | ❌ **FALTA** | Solo adjuntos locales |
| 2.3.3 | GitHub / GitLab | ❌ **FALTA** | No hay links a PRs |
| 2.3.4 | Jira sync | ❌ **FALTA** | No hay sync bidireccional |
| 2.3.5 | Custom Fields | ✅ Implementado | `CampoPersonalizado` + `ValorCampo` |
| 2.3.6 | Voting | ❌ **FALTA** | No hay voting |

### 2.4 Reportes y Analytics
| # | Funcionalidad | Estado | Implementación |
|---|---|---|---|
| 2.4.1 | Reporte de tiempo por tarjeta | ❌ **FALTA** | No hay time tracking |
| 2.4.2 | Reporte de actividad por usuario | ❌ **FALTA** | Datos en auditoría, falta UI |
| 2.4.3 | Burndown / Burnup | ❌ **FALTA** | No hay gráficos |
| 2.4.4 | Cumulative Flow Diagram | ❌ **FALTA** | No hay agregación por fecha |
| 2.4.5 | SLA tracking | ✅ Implementado | `sla_cumplido` + tareas Celery |
| 2.4.6 | Export CSV/Excel | ❌ **FALTA** | Solo render HTML |
| 2.4.7 | Export PDF de tarjeta | ❌ **FALTA** | No hay generación PDF |

### 2.5 Colaboración Avanzada
| # | Funcionalidad | Estado | Implementación |
|---|---|---|---|
| 2.5.1 | Notificaciones en tiempo real | ⚠️ Solo polling | Falta WebSocket/SSE |
| 2.5.2 | Indicador "está escribiendo..." | ❌ **FALTA** | No hay WebSocket |
| 2.5.3 | Presencia (quién está conectado) | ❌ **FALTA** | No hay tracking |
| 2.5.4 | Chat por tarjeta | ❌ **FALTA** | Solo comentarios |
| 2.5.5 | Video llamadas integradas | ❌ **FALTA** | Solo enlaces externos |
| 2.5.6 | Menciones @equipo | ❌ **FALTA** | Solo @usuario |

### 2.6 Seguridad y Compliance
| # | Funcionalidad | Estado | Implementación |
|---|---|---|---|
| 2.6.1 | Permisos por tablero | ✅ Implementado | `PermisoTablero` |
| 2.6.2 | Visibilidad de tablero | ✅ Implementado | privado/espacio/publico |
| 2.6.3 | 2FA | ❌ **FALTA** | No hay auth avanzado |
| 2.6.4 | SSO (Google/Microsoft) | ❌ **FALTA** | No hay OAuth |
| 2.6.5 | Audit log detallado | ✅ Implementado | Tabla `auditoria` |
| 2.6.6 | Enlace público a tablero | ⚠️ Schema existe | Falta endpoint `/p/{slug}` |

### 2.7 Productividad
| # | Funcionalidad | Estado | Implementación |
|---|---|---|---|
| 2.7.1 | Atajos de teclado | ❌ **FALTA** | No hay shortcuts |
| 2.7.2 | Command palette (Ctrl+K) | ❌ **FALTA** | No hay búsqueda rápida |
| 2.7.3 | Plantillas de tablero | ❌ **FALTA** | No hay templates |
| 2.7.4 | Importar desde JSON/CSV | ❌ **FALTA** | No hay import |
| 2.7.5 | Bulk actions (mover múltiples) | ❌ **FALTA** | No hay selección múltiple |
| 2.7.6 | Card mirror / linked cards | ❌ **FALTA** | No hay relaciones |
| 2.7.7 | Card aging (decoración visual) | ❌ **FALTA** | No hay indicator de edad |
| 2.7.8 | Undo / redo | ⚠️ Solo toast | No hay stack de undo |

---

## 3. Funcionalidades ITSM Específicas (ya implementadas)

| # | Funcionalidad | Estado | Notas |
|---|---|---|---|
| 3.1 | Tipos de incidencia (enum) | ✅ | Incidencia, Requerimiento, Problema, Cambio |
| 3.2 | Prioridad (enum) | ✅ | Baja, Media, Alta, Crítica |
| 3.3 | SLA con cumplimiento | ✅ | `sla_cumplido` y `fecha_vencimiento_sla` |
| 3.4 | Transiciones de estado controladas | ✅ | Tabla `transiciones` con validaciones |
| 3.5 | Comentario obligatorio en transición | ✅ | `requiere_comentario` en transición |
| 3.6 | Asignación a agente | ✅ | `asignado_id` |
| 3.7 | Departamento del usuario | ✅ | `departamento` field |
| 3.8 | Catálogos (tipos configurables) | ✅ | Modelo `CatalogoTipo`/`CatalogoItem` |
| 3.9 | Auditoría completa | ✅ | Tabla `auditoria` con valores antes/después |
| 3.10 | Códigos correlativos | ✅ | Formato `GRM-INC-2026-NNNNNN` |

---

## 4. Resumen de Brechas (Gap Analysis)

### 4.1 Brechas Críticas (alta prioridad)
1. **Filtros en Kanban** — El botón "Filtros" no hace nada
2. **Búsqueda global** — No hay forma de buscar tickets
3. **Duplicar tarjeta** — Feature básica de Trello
4. **Avatar/iniciales** — Sin esto el UI se ve incompleto
5. **Dashboard con métricas** — Falta vista agregada
6. **Export CSV** — Necesario para reportes
7. **Modal de crear regla Butler** — El botón no lleva a nada

### 4.2 Brechas Importantes (media prioridad)
8. **Vista previa de imágenes** — Los adjuntos no se ven
9. **Eliminar adjuntos UI** — Endpoint existe pero UI no
10. **Card cover** — Falta imagen de portada
11. **Asignar múltiples miembros** — Solo uno por tarjeta
12. **Templates de tableros** — Catálogo de plantillas
13. **Time tracking** — Crítico para ITSM

### 4.3 Mejoras (baja prioridad)
14. Atajos de teclado
15. Command palette
16. Card aging visual
17. Bulk actions
18. WebSocket para tiempo real
19. SSO / OAuth

---

## 5. Plan de Implementación Priorizado

### Sprint 1 (esta entrega)
- [x] Filtros en Kanban (etiqueta, asignado, prioridad, búsqueda)
- [x] Búsqueda global con command palette (Ctrl+K)
- [x] Duplicar tarjeta
- [x] Vista previa de imágenes adjuntas
- [x] Avatar con iniciales en comentarios y tarjetas
- [x] Dashboard con métricas (vista resumen)
- [x] Export CSV de tickets
- [x] Modal crear regla Butler

### Sprint 2 (futuro)
- Templates de tableros
- Time tracking
- Card cover
- Asignar múltiples miembros
- Atajos de teclado
- Card aging

---

**Documento vivo.** Se actualizará con cada sprint.
