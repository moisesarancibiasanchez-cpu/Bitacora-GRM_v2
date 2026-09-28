<genui-form-wizard title="Decisiones: Referencias Internas" action-id="referencias_internas_design">
<genui-form-page title="Paso 1: Modelo de datos (¿cómo guardar las referencias?)">
<genui-radio-group name="modelo_datos">
<genui-radio value="opcion_a_tabla_dedicada">Opción A — Tabla dedicada `ticket_referencias` (RECOMENDADA)</genui-radio>
<genui-radio value="opcion_b_json">Opción B — Campo JSON en Ticket.referencias_ids</genui-radio>
<genui-radio value="opcion_c_reusar_dependencias">Opción C — Reusar tabla ticket_dependencias con nuevo tipo REF</genui-radio>
</genui-radio-group>
<genui-input selection-mode="radio" name="notas_modelo" placeholder="Notas o justificación de tu elección (opcional)"></genui-input>
</genui-form-page>
<genui-form-page title="Paso 2: Ubicación en la UI (¿dónde vincular?)">
<genui-radio-group name="ubicacion_ui">
<genui-radio value="tab_dedicada">Nueva pestaña 'Referencias' (7ma tab en el modal)</genui-radio>
<genui-radio value="campo_detalles">Campo multi-select dentro del tab Detalles</genui-radio>
<genui-radio value="ambbas">Ambas: tab dedicada + acceso rápido en Detalles</genui-radio>
</genui-radio-group>
<genui-input selection-mode="radio" name="notas_ui" placeholder="Notas sobre la UI (opcional)"></genui-input>
</genui-form-page>
<genui-form-page title="Paso 3: Direccionalidad (¿cómo se ven las referencias inversas?)">
<genui-radio-group name="direccionalidad">
<genui-radio value="bidireccional_auto">Bidireccional automático: si A referencia B, B muestra 'Referenciado por A'</genui-radio>
<genui-radio value="solo_origen">Solo desde el origen: A muestra 'Referencia a B', B no muestra nada</genui-radio>
<genui-radio value="bidireccional_tipo">Bidireccional solo si el tipo es simétrico (ej: 'relacionado')</genui-radio>
</genui-radio-group>
<genui-input selection-mode="radio" name="notas_direccion" placeholder="Notas adicionales (opcional)"></genui-input>
</genui-form-page>
</genui-form-wizard>

**Resumen del plan (basado en tus respuestas):**

| Componente | Entregable |
|-----------|-----------|
| **Modelo SQL** | Nueva tabla `ticket_referencias` con tipos (relacionado, duplicado, padre, hijo, bloquea, bloqueado_por) |
| **API REST** | `POST/GET/DELETE /api/v1/tickets/{id}/referencias` con búsqueda autocompletar |
| **UI** | Nueva tab "Referencias" en modal detalle + selector con búsqueda por código/título |
| **Interacción** | Click en referencia → abre modal del ticket vinculado (modal-over-modal con z-index 80) |
| **Auditoría** | Cada add/remove genera entrada en `auditoria` con accion `TICKET_REFERENCIA_AGREGADA/ELIMINADA` |
| **Migración** | Script `scripts/migrar_ticket_referencias.py` para crear tabla en PostgreSQL |

**Estimación:** ~250 líneas nuevas (modelo + service + endpoints + tab + JS) + migración.

¿Confirmás las 3 decisiones del formulario para que avance con la implementación?
