# ITSM/Kanban MVP — Descripción Técnica Completa

Documento de referencia para evaluación e incorporación del módulo a otros proyectos

Módulo de Incidencias con gestión ITSM estricta sobre visualización Kanban ágil

Versión del módulo: 0.1.0 · Fecha: 2026-10-23

### 1. Resumen ejecutivo

Este módulo implementa un Módulo de Incidencias que reconcilia dos entidades que normalmente entran en conflicto:

• La disciplina del ITSM, que exige control formal: no cualquier cambio de estado es válido, cada movimiento tiene una justificación, un actor responsable y un rastro auditable inalterable.

• La agilidad de Kanban, que exige fluidez visual: el usuario arrastra una tarjeta y espera un resultado inmediato, sin recargas de página ni fricción.

La conciliación se logra con una idea central: la interfaz es libre, el servidor es el autoridad. El tablero permite mover la tarjeta visualmente en cualquier dirección, pero el servidor valida cada movimiento contra una matriz de reglas persistida en base de datos. Si la regla no se cumple, el cambio se rechaza y la tarjeta retorna a su posición original.

El resultado es un sistema donde el compliance no se opone a la/usabilidad, sino que la habilita: el agente mueve la tarjeta con naturalidad y, si el proceso exige justificación (por ejemplo, cerrar un ticket), el sistema la exige de forma automática y la registra.

### 1.1 Métricas verificadas del código

<table><tr><td>Capa</td><td>Archivos</td><td>líneas</td></tr><tr><td>app/models/</td><td>8</td><td>476</td></tr><tr><td>app/services/</td><td>2</td><td>189</td></tr><tr><td>app/api/</td><td>7</td><td>440</td></tr><tr><td>app/core/</td><td>4</td><td>145</td></tr><tr><td>app/db/</td><td>3</td><td>254</td></tr><tr><td>app/tasks/</td><td>2</td><td>139</td></tr><tr><td>app/templates/</td><td>5</td><td>341</td></tr><tr><td>tests/</td><td>1</td><td>179</td></tr><tr><td>Total Python</td><td>—</td><td>1.708</td></tr><tr><td>Total HTML/Jinja2</td><td>—</td><td>341</td></tr></table>

Entidades de base de datos: 7 tablas · Endpoints: 15 · Tareas asíncronas: 4 · Pruebas automatizadas: 4 (todas en verde)

### 2. Problema que resuelve

En el soporte de incidencias se observa una fricción recurrente entre dos flujos de trabajo histórico:

Flujo ITSM tradicional (formal pero rígido). El técnico llena un formulario, espera aprobación, el ticket avanza por estados predefinidos. El Kanban se pierde porque el estado real del trabajo técnico no cabe en el formulario. La información del tablero es siempre obsoleta.

Flujo Kanban puro (fluido pero anárquico). Cualquiera mueve cualquier tarjeta a cualquier columna. Nadie sabe quién cambió el estado, cuándo ni por qué. No hay control de permisos, no hay SLA verificable, y auditar qué pasó con un ticket requiere reconstruirlo desde correos y chats. Cuando hay una auditoría de cumplimiento o post mortem, el equipo no puede responder.

Este módulo adopta la postura de que la trazabilidad no puede ser un trámite posterior, sino una consecuencia estructural del diseño. La tabla de auditoría no es una funcionalidad opcional que se activa cuando alguien la necesita: es una consecuencia inevitable de mover un ticket, porque el movimiento y su registro se escriben en la misma transacción de base de datos.

### 2.1 Ejemplo del flujo resuelto

Usuario arrastra «Login falla 500» de [Pendiente] a [En revisión]

1. SortableJS detecta el soltar → lee ticket_id=42, estado_destino=4
2. HTMX envía POST /api/v1/kanban/tickets/42/mover {estado_id: 4, posicion: 0}
3. FastAPI consulta PostgreSQL por una regla Transicion(origen=1, destino=4)
4. Regla encontrada: «Enviar a revisión», requiere rol AGENTE
5. Usuario (AGENTE) cumple el rol → válido
6. UPDATE tickets SET estado_id=4 WHERE id=42
7. INSERT auditoria_eventos (tipo=ESTADO_CAMBIADO, actor='agente1', valor_anterior='{"estado":"Pendiente"}', valor_nuevo='{"estado":"En revisión"}')
8. Celery .delay() → recalcular_sla_ticket(42) + notificar_cambio_estado(...)
9. COMMIT (transacción única: paso 6 y 7 son atómicos)
10. Retorna solo el fragmento HTML de la tarjeta → HTMX reemplaza el nodo, sin recargar

Si en el paso 3 no existiera la regla 1→4, el servidor responde 422 con el encabezado HX-Reswap: none. HTMX no ejecuta el intercambio, la tarjeta permanece visible en su columna original y una barra de error explica por qué.

### 3. Arquitectura

### 3.1 Vista de componentes

![](extract/viewrange_chunk_1_1_5_0622e6bd/images/page_4_img_in_image_box_115_258_704_718.jpg)

### 3.2 Patrón de flujo de datos

El sistema implementa un flujo de validate-then-persist-then-notify donde la validación precede siempre a la persistencia y ambas ocurren dentro de la misma transacción:

Validación (read-only)
- ¿Existe el ticket? → 404
- ¿Existe y está activo el destino? → 422
- ¿Existe regla Transicion(origen, destino)? → 422
- ¿El rol del usuario satisface el mínimo? → 403
- ¿Si requiere_comentario, viene texto? → 422
- (si algo falla: NADA se escribe)

Persistencia (transacción atómica)
- UPDATE tickets (estado_id, posicion, updated_at)
- INSERT auditoria_eventos → OBLIGATORIO

Notificación asícnona (fuera de la transacción)
- Celery .delay() → recálculo SLA + notificación

Respuesta (fragmento HTML, no página completa)

Esta separación garantiza que un rechazo nunca deja efectos secundarios parciales: si la validación falla, no hay escritura de ningún tipo.

### 4. Modelo de datos

El modelo se organiza alrededor de siete tablas que permanecen conformas a tres capas de responsabilidad.

### 4.1 Capa de identidad y permisos

Tabla usuarios

<table><tr><td>Columna</td><td>Tipo</td><td>Restricciones</td></tr><tr><td>id</td><td>INTEGER</td><td>PK, autoincrement</td></tr><tr><td>username</td><td>VARCHAR(64)</td><td>UNIQUE, INDEX, NOT NULL</td></tr><tr><td>email</td><td>VARCHAR(128)</td><td>UNIQUE, INDEX, NOT NULL</td></tr><tr><td>nombre_completo</td><td>VARCHAR(128)</td><td>NOT NULL, default ''</td></tr><tr><td>password_hash</td><td>VARCHAR(255)</td><td>NOT NULL (hash bcrypt, nunca texto plano)</td></tr><tr><td>rol</td><td>ENUM(20)</td><td>NOT NULL, default SOLICITANTE</td></tr><tr><td>activo</td><td>BOOLEAN</td><td>NOT NULL, default true</td></tr><tr><td>created_at / updated_at</td><td>TIMESTAMPTZ</td><td>NOT NULL, server default / ON UPDATE</td></tr></table>

Enum RolUsuario — cinco roles con jerarquía implícita de privilegio:

<table><tr><td>Rol</td><td>Nivel</td><td>Descripción funcional</td></tr><tr><td>OBSERVADOR</td><td>0</td><td>Solo lectura. No puede transicionar nada.</td></tr><tr><td>SOLICITANTE</td><td>1</td><td>Crea tickets. No avanza el flujo de trabajo.</td></tr><tr><td>AGENTE</td><td>2</td><td>Ejecuta el trabajo: iniciar, bloquear, resolver.</td></tr><tr><td>AGENTE_SENIOR</td><td>3</td><td>Operaciones de cierre y cancelación, que requieren justificación.</td></tr><tr><td>ADMINISTRADOR</td><td>4</td><td>Acceso total. Única figura con autoridad para cerrar.</td></tr></table>

La jerarquía no está codificada en el esquema sino resuelta en tiempo de ejecución por el método Transición.usuario_tiene_permiso(), que compara el nivel del rol del usuario contra el mínimo requerido por la transición. Esto permite subir o bajar el privilegio de una transición editando una fila de base de datos, sin tocar código.

Propiedades de conveniencia en el modelo: Usuario.es_admin y Usuario.puede_cerrar_ticket encapsulan las dos consultas de permiso más frecuentes.

### 4.2 Capa de ciclo de vida

## Tabla estados

Representa simultáneamente el estado ITSM y la columna del tablero Kanban. No hay dos conceptos separados: cada estado es una columna con un orden, un color y una posición.

<table><tr><td>Columna</td><td>Tipo</td><td>Función</td></tr><tr><td>nombre</td><td>VARCHAR(64) UNIQUE</td><td>Identificador legible</td></tr><tr><td>orden</td><td>INTEGER</td><td>Posición izquierda → derecha en el tablero</td></tr><tr><td>categoria</td><td>ENUM(20)</td><td>Semántica funcional del estado</td></tr><tr><td>color</td><td>VARCHAR(7)</td><td>Color HEX de la cabecera de columna</td></tr><tr><td>es_inicial / es_final</td><td>BOOLEAN</td><td>Marcadores del ciclo de vida</td></tr></table>

<div>Enum CategoriiaEstado — agrupa estados que comparten comportamiento aunque su nombre varíe:</div>

<table><tr><td>Categoría</td><td>Significado</td></tr><tr><td>PENDIENTE</td><td>Backlog, trabajo no iniciado</td></tr><tr><td>EN_PROGRESO</td><td>Trabajo activo en curso</td></tr><tr><td>BLOQUEADO</td><td>En espera por dependencia externa</td></tr><tr><td>RESUELTO</td><td>Trabajo terminado, pendiente de verificación</td></tr><tr><td>CERRADO</td><td>Terminal. Ciclo de vida concluido</td></tr><tr><td>CANCELADO</td><td>Terminal. Desestimado</td></tr></table>

El campo es final tiene consecuencias funcionales reales: las tareas de Celery lo consultan para marcar el SLA como cumplido automáticamente (recalcular sla ticket línea 49) sin necesidad de esperar al vencimiento.

Tabla transiciones — el corazón del control ITSM

Esta tabla es la pieza que distingue este módulo de un Kanban convencional. Cada fila declara qué movimiento es legal.

<table><tr><td>Columna</td><td>Tipo</td><td>Función</td></tr><tr><td>origen_id</td><td>FK → estados.id ON DELETE CASCADE</td><td>Estado de partida</td></tr><tr><td>destino_id</td><td>FK → estados.id ON DELETE CASCADE</td><td>Estado de llegada</td></tr><tr><td>nombre</td><td>VARCHAR(64)</td><td>Etiqueta de la acción ("Iniciar", "Cerrar")</td></tr><tr><td>rol_requerido</td><td>ENUM(20)</td><td>Privilegio mínimo exigido</td></tr><tr><td>requiere_comentario</td><td>BOOLEAN</td><td>Si exige justificación escrita</td></tr><tr><td>dispara_recalculo_sla</td><td>BOOLEAN</td><td>Si debe encolar tarea asíncrona</td></tr><tr><td>activo</td><td>BOOLEAN</td><td>Interruptor para desactivar sin borrar</td></tr></table>

Restricción de unicidad: UNIQUE (origen_id, destino_id) garantiza que no existan reglas duplicadas ni ambiguas para el mismo par de estados. Esto es relevante porque mover_ticket() usa .first() para localizar la regla; sin la restricción, el comportamiento sería no determinista.

Matriz de transiciones sembrada por defecto (10 reglas):

<table><tr><td>Origen</td><td>→ Destino</td><td>Rol mínimo</td><td>Comentario</td><td>Nombre</td></tr><tr><td>Pendiente</td><td>En curso</td><td>AGENTE</td><td>No</td><td>Iniciar</td></tr><tr><td>Pendiente</td><td>Cancelado</td><td>AGENTE</td><td>Sí</td><td>Cancelar</td></tr><tr><td>En curso</td><td>Bloqueado</td><td>AGENTE</td><td>Sí</td><td>Bloquear</td></tr><tr><td>En curso</td><td>En revisión</td><td>AGENTE</td><td>No</td><td>Enviar a revisión</td></tr><tr><td>En curso</td><td>Pendiente</td><td>AGENTE</td><td>Sí</td><td>Devolver</td></tr><tr><td>Bloqueado</td><td>En curso</td><td>AGENTE</td><td>No</td><td>Desbloquear</td></tr><tr><td>Bloqueado</td><td>Cancelado</td><td>AGENTE_SENIOR</td><td>Sí</td><td>Cancelar (bloq.)</td></tr><tr><td>En revisión</td><td>En curso</td><td>AGENTE</td><td>Sí</td><td>Devolver a curso</td></tr><tr><td>En revisión</td><td>Cerrado</td><td>AGENTE_SENIOR</td><td>Sí</td><td>Cerrar</td></tr><tr><td>En revisión</td><td>Cancelado</td><td>AGENTE_SENIOR</td><td>Sí</td><td>Cancelar (rev.)</td></tr></table>

Lectura de negocio de la matriz: el flujo happy-path es Pendiente → En curso → En revisión → Cerrado. Cerrar y cancelar exigen siempre justificación escrita y privilegio AGENTE_SENIOR. Las flechas de retroceso (Devolver, Desbloquear) existen deliberadamente: un ITSM rígido que solo permite avanzar obliga a los técnicos a "hackear" el sistema. Aquí el retroceso es una transición de primera clase, auditada como cualquier otra.

<div>Tabla tickets</div>

<table><tr><td>Columna</td><td>Tipo</td><td>Notas</td></tr><tr><td>codigo</td><td>VARCHAR(32) UNIQUE INDEX</td><td>Identificador de negocio legible (TKT-00001)</td></tr><tr><td>titulo</td><td>VARCHAR(255) NOT NULL</td><td>Resumen en una línea</td></tr><tr><td>descripción</td><td>TEXT</td><td>Detalle libre</td></tr><tr><td>estado_id</td><td>FK → estados.id RESTRICT</td><td>La columna actual del Kanban</td></tr><tr><td>prioridad</td><td>ENUM(10)</td><td>BAJA · MEDIA · ALTA · CRITICA</td></tr><tr><td>creador_id</td><td>FK → usuarios.id RESTRICT</td><td>Quién reporta</td></tr><tr><td>asignado_id</td><td>FK → usuarios.id SET NULL</td><td>Quién atiende. NULL si desasignado</td></tr><tr><td>posición</td><td>INTEGER</td><td>Orden manual dentro de la columna</td></tr><tr><td>fecha_vencimiento_sla</td><td>TIMESTAMPTZ NULL</td><td>Calculado por Celery</td></tr><tr><td>sla_cumplido</td><td>BOOLEAN NULL</td><td>Ternario: NULL = sin calcular, TRUE = en plazo, FALSE = vencido</td></tr><tr><td>metadata_json</td><td>TEXT default '{}'</td><td>Extensibilidad sin migración</td></tr></table>

## Decisiones de integridad relevantes:

• estado_id usa ON DELETE RESTRICT: es imposible borrar un estado que tenga tickets asociados. Esto protege la integridad del historical.

• asignado_id usa ON DELETE SET NULL: desasignar un usuario no destruye tickets. Se prefiere perder la asignación antes que el registro.

• Índice compuesto ix tickets estado orden (estado id, posicion): está calibrado exactamente para la consulta del tablero, que siempre pide "los tickets de esta columna ordenados por posición". Sin este índice, cada renderizado del Kanban degrada a un escaneo secuencial conforme crece el histórico.

El ternario de sla_cumplido merece atención: NULL no significa "cumplió", significa "aún no se ha calculado". Esta distinción entre "no sabemos" y "sabemos que no cumplió" es fundamental en la gestión de SLA y se refleja directamente en la interfaz, donde la tarjeta muestra tres estados visuales distintos: *Sin calcular* (gris), *En plazo* (verde), *Vencido* (rojo).

### 4.3 Capa de trazabilidad y soporte

<div>Tabla auditoria_eventos — registro append-only</div>

<table><tr><td>Columna</td><td>Tipo</td><td>función</td></tr><tr><td>ticket_id</td><td>FK → tickets.id ON DELETE CASCADE</td><td>Ticket afectado</td></tr><tr><td>tipo</td><td>ENUM(30) INDEX</td><td>Naturaleza del evento</td></tr><tr><td>actor_id</td><td>FK → usuarios.id SET NULL</td><td>Autor (NULL si fue un proceso automático)</td></tr><tr><td>actor_username</td><td>VARCHAR(64)</td><td>Desnormalizado deliberadamente</td></tr><tr><td>valor_anterior</td><td>TEXT</td><td>Estado previo, JSON serializado</td></tr><tr><td>valor_nuevo</td><td>TEXT</td><td>Estado nuevo, JSON serializado</td></tr><tr><td>comentario</td><td>TEXT</td><td>Justificación escrita</td></tr><tr><td>created_at</td><td>TIMESTAMPTZ INDEX</td><td>Marca temporal</td></tr></table>

<div>Enum TipoEvento — taxonomía de 8 eventos auditables:</div>

<table><tr><td>Evento</td><td>Cuándo se emite</td></tr><tr><td>CREADO</td><td>Alta del ticket</td></tr><tr><td>ESTADO_CAMBIADO</td><td>Movimiento validado en el Kanban</td></tr><tr><td>REASIGNADO</td><td>Cambio de responsable</td></tr><tr><td>PRIORIDAD_CAMBIADA</td><td>Reclasificación por severidad</td></tr><tr><td>COMENTARIO_AGREGADO</td><td>Interacción del usuario</td></tr><tr><td>ADJUNTO_AGREGADO</td><td>Carga de evidencia</td></tr><tr><td>SLA_CALCULADO</td><td>Tarea Celery recalcula el plazo</td></tr><tr><td>NOTIFICACION_ENVIADA</td><td>Proceso automático notifica</td></tr></table>

Por qué actor_username está desnormalizado. Es una decisión deliberada que merece justificación explícita. Cuando un usuario se elimina de la tabla usuarios (actor_id pasa a NULL por ON DELETE SET NULL), el registro de auditoría conserva el nombre de quien actuó. En una auditoría de cumplimiento, «el usuario #47 movió este ticket» es inservible dos años después si #47 ya no existe. La desnormalización compra integridad del registro a costa de una anomalía de actualización controlada, y es el compromiso correcto para tablas append-only.

Modelo strictly append-only. El modelo declara sus campos sin updated_at y su relación con cascada all, delete-orphan, lo que impide actualizaciones accidentales desde la capa de aplicación. No existe endpoint que modifique o elimine un evento.

<div>Tabla sla\_políticas</div>

<table><tr><td>Columna</td><td>Tipo</td><td>función</td></tr><tr><td>nombre</td><td>VARCHAR(64) UNIQUE</td><td>Identificador de la política</td></tr><tr><td>prioridad</td><td>ENUM(10) INDEX</td><td>Prioridad a la que aplica</td></tr><tr><td>minutos_resolución</td><td>INTEGER</td><td>Plazo máximo en minutos</td></tr><tr><td>es_default</td><td>BOOLEAN</td><td>Política activa para esa prioridad</td></tr><tr><td>activo</td><td>BOOLEAN</td><td>Interruptor</td></tr></table>

Políticas sembradas:

<table><tr><td>Política</td><td>Prioridad</td><td>Plazo</td></tr><tr><td>SLA Crítica</td><td>CRITICA</td><td>4 horas</td></tr><tr><td>SLA Alta</td><td>ALTA</td><td>24 horas</td></tr><tr><td>SLA Media</td><td>MEDIA</td><td>72 horas</td></tr><tr><td>SLA Baja</td><td>BAJA</td><td>168 horas (7 días)</td></tr></table>

El flag es default permite mantener múltiples políticas por prioridad (por ejemplo, por cliente o por contrato) y seleccionar cuál aplica sin duplicar código.

Tabla catalogo_items — base para mantenedores futuros

Tabla única que hospeda todos los catálogos del sistema, discriminados por la columna tipo. Este diseño evita crear una tabla nueva por cada concepto configurable.

<table><tr><td>Campo</td><td>Función</td></tr><tr><td>tipo</td><td>TIPO_TICKET · CATEGORIA · ETIQUETA · MODULO</td></tr><tr><td>codigo</td><td>Código corto de negocio (INC, HW, AUTH)</td></tr><tr><td>nombre / descripción</td><td>Etiqueta visible y glosa</td></tr><tr><td>color</td><td>Color HEX para representación visual</td></tr><tr><td>parent_id</td><td>FK autorreferenciada para jerarquías</td></tr><tr><td>orden</td><td>Posición en el mantenedor</td></tr></table>

Restricción: UNIQUE (tipo, codigo) — el mismo código puede repetirse en catálogos distintos (un HW de categoría y un HW de módulo coexisten sin conflicto).

Auto-referencia. parent_id con ON DELETE SET NULL habilita árboles de jerarquía arbitrariamente profundos (Categoría → Subcategoría → Sub-subcategoría). El campo activo en toda la tabla —presente en esta misma tabla — permite desactivar ítems sin borrarlos, preservando la integridad referencial de tickets históricos que los Marcaban.

Catálogos sembrados (11 ítems): 4 tipos de ticket (Incidencia, Requerimiento, Bug, Consulta), 4 categorías (Hardware, Software, Redes, Seguridad), 3 módulos (Autenticación, API, Interfaz).

### 4.4 Diagrama entidad-relación

![](extract/viewrange_chunk_2_6_10_446363ec/images/page_5_img_in_image_box_149_152_601_940.jpg)

### 5. Reglas de negocio ITSM

Las reglas viven en la capa de servicios (app/services/kanban_service.py), no en los endpoints ni en la interfaz. Esta separación permite invocar la misma lógica desde un futuro API REST, desde una tarea programada o desde un proceso de importación masiva.

### 5.1 Función mover ticket() — núcleo del sistema

Es la única vía por la que un ticket puede cambiar de estado. Firma:

mover_ticket(db, ticket_id, estado_destino_id, usuario, nueva_posicion=0, comentario="") -> dict

Secuencia de validación (ejecutada en orden, cortando en el primer fallo):

<table><tr><td>#</td><td>Validación</td><td>Código de error</td><td>Razón</td></tr><tr><td>1</td><td>El ticket existe</td><td>404</td><td>Recurso inexistente</td></tr><tr><td>2</td><td>El ticket tiene estado asociado</td><td>500</td><td>Integridad referencial rota</td></tr><tr><td>3</td><td>El destino existe y está activo</td><td>422</td><td>Columna inválida o desactivada</td></tr><tr><td>4</td><td>Existe regla Transicion(origen, destino)</td><td>422</td><td>Movimiento no contemplado en el flujo</td></tr><tr><td>5</td><td>El rol satisface rol requerido</td><td>403</td><td>Privilegio insuficiente</td></tr><tr><td>6</td><td>Si requiere comentario, viene texto</td><td>422</td><td>Falta justificación</td></tr></table>

Códigos HTTP diferenciados por causa: la distinción entre 403 (*no autorizado*) y 422 (*transición mal formada*) es deliberada. Un 403 indica un problema de permisos del usuario —debe mostrársele directamente. Un 422 indica que la operación no tiene sentido en el flujo de trabajo, independientemente de quién la intente.

Efectos laterales tras validación exitosa:

# 1. Mutación del ticket
ticket.estado_id = estado_destino.id
ticket.posicion = nueva_posicion
ticket.updated_at = now(UTC)

# 2. Registro de auditoría – OBLIGATORIO, misma transacción
db.add(AuditoriaEvento(
    tipo=TipoEvento.ESTADO_CAMBIADO,
    actor_username=usario.username, # desnormalizado
    valor_anterior=json.dumps({...}),
    valor_nuevo=json.dumps({...}),
    comentario=comentario,
))

# 3. Notificación asíncrona – tolerante a fallos
if transicion.dispara_recalculo_sla:
    try:
        recalcular_sla_ticket.delay(ticket.id)
        notification_cambio_estado.delay(ticket.id, nombre_origen, estado_destino.nombre)
    except Exception:
        pass  # broker caído no impide el movimiento

db.commit()  # ← pasos 1 y 2 son atómicos

Decisión de diseño sobre Celery tolerante a fallos. Las llamadas .delay() están envueltas en try/except que absorbe la excepción. Un broker Redis caído no debe impedir que un agente mueva un ticket. La degradación

preferida es perder el recálculo de SLA antes que bloquear el trabajo del equipo. La consecuencia —un SLA sin recalcular— es reversible: el job de Celery Beat reintenta cada 5 minutos.

### 5.2 Matriz de privilegios

Transicion.usuario_tiene_permiso() implementa la resolución de jerarquía:

<table><tr><td>Usuario \ Requerido</td><td>CUALQUIERA (0)</td><td>SOLICITANTE (1)</td><td>AGENTE (2)</td><td>AGENTE_SENIOR (3)</td><td>ADMINISTRADOR (4)</td></tr><tr><td>OBSERVADOR (0)</td><td>Si</td><td>No</td><td>No</td><td>No</td><td>No</td></tr><tr><td>SOLICITANTE (1)</td><td>Si</td><td>Si</td><td>No</td><td>No</td><td>No</td></tr><tr><td>AGENTE (2)</td><td>Si</td><td>Si</td><td>Si</td><td>No</td><td>No</td></tr><tr><td>AGENTE_SENIOR (3)</td><td>Si</td><td>Si</td><td>Si</td><td>Si</td><td>No</td></tr><tr><td>ADMINISTRADOR (4)</td><td>Si</td><td>Si</td><td>Si</td><td>Si</td><td>Si</td></tr></table>

La matriz es un producto cartesiano de niveles, no una colección de reglas exóticas: cualquier rol con nivel suficiente satisface cualquier requisito con nivel suficiente. Esto elimina la necesidad de enumerar combinaciones permitidas.

### 6. Procesamiento asíncrono

### 6.1 Configuración Celery

celery_app = Celery(
    "itsm_kanban",
    broker=settings.celery_broker_url, # Redis DB 1
    backend=settings.celery_result_backend, # Redis DB 2
    include=[app.tasks.kanban_tasks],
)

Redis usa tres bases de datos lógicas separadas (0 para aplicación, 1 para broker, 2 para resultados). Esto evita colisiones de claves entre el estado de la aplicación y los mensajes de la cola, un problema habitual cuando todo comparte el mismo namespace.

Parámetros de robustez aplicados:

<table><tr><td>Parámetro</td><td>Valor</td><td>Justificación</td></tr><tr><td>task_acks_late</td><td>true</td><td>El broker reintent si el worker muere a mitad de tarea</td></tr><tr><td>task_reject_on_worker_lost</td><td>true</td><td>Devuelve el mensaje a la cola en pérdida de worker</td></tr><tr><td>worker_prefetch_multiplier</td><td>1</td><td>Distribución justa: una tarea por worker a la vez</td></tr><tr><td>task_soft_time_limit</td><td>60 s</td><td>Interrupción limpia con excepción</td></tr><tr><td>task_time_limit</td><td>120 s</td><td>Terminación forzada del proceso colgado</td></tr><tr><td>broker_connection_retry_on_startup</td><td>true</td><td>El worker espera a Redis en despliegues en frío</td></tr><tr><td>task_track_started</td><td>true</td><td>Permite distinguir *iniciada* de *en cola*</td></tr><tr><td>timezone / enable_utc</td><td>UTC</td><td>Normalización horaria entre procesos</td></tr></table>

worker_prefetch_multiplier = 1 merece comentario: con el valor por defecto (4), un worker reserva cuatro tareas de una vez, lo que en un despliegue con varios workers produce asimetría en la distribución — un worker puede monopolizar un lote mientras otro espera vacío. Fijarlo en 1 reparte el trabajo uniformemente.

### 6.2 Tareas implementadas (4)

recalcular_sla_ticket(ticket_id) — cálculo de plazo individual

Disparada por cada movimiento de ticket. Lógica:

1. Busca la política SLA default para la prioridad actual del ticket.

2. Si el estado es terminal (es final), marca sla cumplido = True sin más cálculo.

3. Si no tiene vencimiento asignado, lo calcula como now() + minutos_resolución.

4. Compara con la hora actual para determinar cumplimiento.

5. Registra un evento SLA CALCULADO en auditoría, firmado por actor username="system".

El paso 5 cierra el ciclo de trazabilidad: los cambios de SLA hechos por procesos automáticos también quedan auditados, con el sistema identificado como actor.

recalcular_slas_vencidos() — barrido programado

Ejecutada cada 5 minutos por Celery Beat. Localiza tickets no terminales y encola un recálculo individual por cada uno, en lugar de recalcarlos todos en un único proceso. Esta decisión mantiene el trabajo paralelo y evita que un lote grande bloquee el worker durante minutos.

notificar cambio estado(ticket id, anterior, nuevo)

Registra un evento NOTIFICACION_ENVIADA. En el MVP el canal de entrega es la propia auditoría; el punto de extensión está marcado explícitamente en el docstring para conectar SMTP, Slack o webhook.

notificar cambios pendientes() — marcador de posición

Ejecutada cada hora. Actualmente es un *stub* documentado como tal.

### 6.3 Planificador Celery Beat

celery_app.conf.beat_schedule = {
    "recalcular-slas-vencidos": { "task": "...recalcular_slas_vencidos", "schedule": "crontab(minute="*/5")",
    "notification-cambios-pendientes": { "task": "...notification_cambios_pendientes", "schedule": "crontab(minute=0)}
}

Reconciliación SLA cada 5 minutos · Notificaciones cada hora en punto.