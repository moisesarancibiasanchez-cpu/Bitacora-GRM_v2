### 13. Guía de incorporación a otros proyectos

Esta sección responde a la pregunta central: cómo incorporar este módulo a un proyecto existente.

### 13.1 Criterios de idoneidad

El módulo es adecuado si el proyecto destino cumple al menos una de estas condiciones:

• Gestiona entidades con ciclo de vida regulado por reglas (tickets, casos, órdenes, requisiciones, reportes)

• Requiere trazabilidad de cambios por auditoría o cumplimiento normativo

• Necesita control de acceso por rol con distintos niveles de privilegio

• Debe calcular plazos y detectar vencimientos (SLA)

• Busca una vista Kanban sin renunciar al control formal

### 13.2 Escenario A — Proyecto nuevo (adopción directa)

### Esforzo estimado: bajo. El módulo funciona standalone

# 1. Copiar el directorio itsm_kanban_mvp/ al proyecto
cp -r itsm_kanban_mvp/ mi-proyecto/

# 2. Instalar dependencias
cd mi-proyecto && pip install -r requirements.txt

# 3. Configurar entorno
cp .env.example .env

# Editar SECRET_KEY, DATABASE_URL, BOOTSTRAP_ADMIN_PASSWORD

# 4. Crear esquema y datos iniciales
python -m app.db.init_db

# 5. Lanzar procesos
uvicorn app.main:app --host 0.0.0.0 --port 8000
celery -A app.core.celery_app:celery_app worker --loglevel=info
celery -A app.core.celery_app:celery_app beat --loglevel=info

### 13.3 Escenario B — Proyecto existente (integración como subsistema)

Este es el escenario de mayor interés. El módulo aporta cuatro activos reutilizables con distinto grado de acoplamiento:

### B.1 Núcleo de reglas ITSM — acoplamiento medio, alto valor

Activo: el motor de máquina de estados (Transición + mover ticket).

Desacoplamiento: el motor no depende de FastAPI. mover ticket() recibe una Session de SQLAlchemy y un objeto Usuario; no importa nada del framework HTTP. Puede invocarse desde cualquier contexto.

## Pasos de integración:

1. Crear las tablas estados, transiciones, auditoría eventos en el esquema destino.

2. Sembrar el flujo de estados propio del proyecto destino.

3. Definir la matriz de transiciones según el proceso real.

4. Invocar mover ticket() desde el servicio de dominio existente.

# Integración en un servicio de orders.py del proyecto destino
from app.services.kanban_service import mover_ticket, TransicionInvalidaError

@router.post("/ordenes/{id}/transicionar")
def transicionar(id: int, destino: int, usuario: Usuario, db: Session = Depends(get_db)):
    try:
        return mover_ticket(db, id, destino, usuario, comentario=...)
    except TransicionInvalidaError as e:
        raise HTTPException(422, e.detail)

Adaptación necesaria: renombrar el vocabulario. Si el dominio destino habla de *órdenes* en lugar de *tickets*, conviene renombrar Ticket → Orden, AuditoriaEvento → keep, Transicion → keep. El motor de reglas no cambia; solo la nomenclatura.

### B.2 Patrón de auditoría append-only — acoplamiento cero, valor inmediato

Activo: el patrón de registro inmutable con taxonomía de eventos y desnormalización del actor.

Es una de las piezas más fáciles de adaptar y de mayor valor unitario. Puede aplicarse a cualquier entidad de cualquier proyecto sin modificar la estructura:

CREATE TABLE auditoria_eventos (
    id SERIAL PRIMARY KEY,
    entidad_tipo VARCHAR(50) NOT NULL,
    entidad_id INTEGER NOT NULL,
    tipo VARCHAR(30) NOT NULL,
    actor_id INTEGER,
    actor_username VARCHAR(64) NOT NULL,
    valor_anterior TEXT,
    valor_nuevo TEXT,
    comentario TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_auditoria ON auditoria_eventos (entidad_tipo, entidad_id, created_at);

El índice compuesto es indispensable: toda consulta de auditoría filtra por entidad y ordena por fecha.

Recomendación: priorizar este componente si el proyecto destino tiene requisitos de auditoría pero no ha implementado el patrón. Es una incorporación de bajo riesgo y alto retorno.

### B.3 Celery + Redis para SLA y notificaciones — acoplamiento medio

Activo: la configuración Celery robusta y las tareas de recálculo.

El valor no está en el código específico sino en los parámetros de robustez ya resueltos: acks_late, reject_on_worker_lost, prefetch_multiplier=1, soft_time_limit, time_limit, broker_connection_retry_on_startup. Son problemas operables con todo proyecto que use Celery en producción, y su valor acumulado supera el del código de negocio específico.

### B.4 Patrón Ul Kanban + HTMX — acoplamiento alto, acoplamiento de contrato

Activo: la integración SortableJS + HTMX con protocolo de error por encabezados.

Precaución: es el componente menos reutilizable tal cual, por dos razones:

1. El contrato de datos está acoplado a los nombres del MVP (data-ticket-id, data-estado-id, endpoint /api/v1/kanban/tickets/{id}/mover).

2. Contiene la limitación L1 (comentario no capturado), que debe corregirse antes de replicar el patrón.

Lo reutilizable es el patrón arquitectónico, no el código:

<table><tr><td>Decisión</td><td>Valor</td></tr><tr><td>El DOM se mueve optimísticamente; el servidor confirma</td><td>Latencia percibida nula</td></tr><tr><td>El servidor devuelve fragmentos, no JSON</td><td>Cero lógica de renderizado en el cliente</td></tr><tr><td>El error viaja por HX-Reswap: none</td><td>Sin librería de estado en el cliente</td></tr><tr><td>El cliente nunca decide si un movimiento es válido</td><td>Fuente única de verdad</td></tr></table>

Si el proyecto destino ya tiene un tablero Kanban —como ocurre con Bitácora GRM v2—, la recomendación es portar la lógica de reglas al backend existente en lugar de sustituir su frontend.

### 13.4 Matriz de esfuerzo de integración

<table><tr><td>Componente</td><td>Esfuerzo</td><td>Riesgo</td><td>Valor</td><td>Recomendación</td></tr><tr><td>Patrón de auditoría</td><td>Bajo</td><td>Bajo</td><td>Alto</td><td>Adoptar en cualquier proyecto con requisitos de trazabilidad</td></tr><tr><td>Motor de reglas ITSM</td><td>Medio</td><td>Medio</td><td>Alto</td><td>Adoptar si hay ciclo de vida regulado</td></tr><tr><td>Configuración Celery robusta</td><td>Bajo</td><td>Bajo</td><td>Medio-Alto</td><td>Adoptar si ya usa Celery</td></tr><tr><td>Patrón Ul Kanban+HTMX</td><td>Medio</td><td>Medio</td><td>Medio</td><td>Portar el patrón, no el código</td></tr><tr><td>Modelos completos</td><td>Bajo</td><td>Bajo</td><td>Variable</td><td>Referencia de diseño de esquema</td></tr></table>

### 13.5 Verificaciones previas a la incorporación

Antes de integrar, comprobar:

• [] ¿El proyecto destino tiene entidades con ciclo de vida regulado? *(si no, B.1 no aporta valor)*

• [] ¿Existe conflicto de nombres de tabla? usuarios, estados, tickets son nombres genéricos

• [] ¿Se usa SQLAlchemy 2.0? Requisito para reutilizar los modelos sin reescritura

• [] ¿Existe ya un sistema de auditoría? Evaluar duplicación antes de añadir otro

• [] ¿El proyecto tiene proceso de migraciones? Alembic vs. create_all() es una decisión de arquitectura

• [] ¿Se acepta el coste de dos procesos Celery adicionales? (worker + beat)

### 14. Sincronización con el proyecto anfitrión

En el caso específico de Bitácora GRM v2 (repositorio anfitrión), coexisten dos tableros Kanban:

<table><tr><td>Aspecto</td><td>Tablero de Bitácora (app/templates/kanban/)</td><td>Tablero ITSM MVP (itsm kanban mvp/)</td></tr><tr><td>Madurez</td><td>En producción, historical extenso de correcciones</td><td>MVP, 4 pruebas</td></tr><tr><td>Lógica de transición</td><td>En el tablero principal</td><td>Aislada y testada en kanban_service</td></tr><tr><td>Matriz de reglas</td><td>No externalizada</td><td>Tabla transiciones</td></tr><tr><td>Auditoría</td><td>Parcial</td><td>Append-only garantizada</td></tr><tr><td>Dependencias</td><td>fastapi 0.115.0, pydantic 2.9.2</td><td>fastapi 0.115.5, pydantic 2.10.3</td></tr></table>

Recomendación de convergencia: portar el motor de reglas ITSM al tablero existente, en lugar de mantener dos tableros. El tablero de Bitácora tiene la experiencia de producción —manejo de errores, estados terminales post-Cerrado, casos límite de producción— que el MVP no posee. El MVP aporta la disciplina de reglas y la separación servicio/endpoint que el tablero existente no tiene.

## Pasos sugeridos para la convergencia:

1. Extraer kanban service.mover ticket() como módulo independiente sin dependencias de FastAPI.

2. Mapear las reglas ITSM sobre los estados reales de Bitácora (que incluye estados como «Producción OK» no contemplados en el MVP).

3. Sustituir la lógica de drag-drop actual del tablero de Bitácora por la llamada al servicio.

4. Unificar versiones de dependencias (fastapi, pydantic, httpx) en un solo archivo.

### 15. Resumen ejecutivo para decisión de incorporación

Qué es: un módulo de incidencias de ~2.000 líneas que implementa gestión ITSM sobre Kanban, con máquina de estados persistida, auditoría inmutable y procesamiento asíncrono de SLAs.

## Lo que aporta con mayor valor:

1. La tabla transiciones. Externalizar las reglas de flujo a la base de datos —con rol requerido, comentario obligatorio y banderas de control— convierte el flujo de trabajo en dato configurable en lugar de código. Modificar el proceso no requiere desplgar.

1. El patrón de auditoría append-only con taxonomía de eventos y actor desnormalizado. Simple de adoptar, aplicable a cualquier entidad, e independiente de FastAPI.

1. La separación validación-persistencia-notificación, donde la notificación asíncrona es tolerante a fallos y la escritura es atómica con su rastro.

Lo que requiere trabajo antes de producción:

<table><tr><td>Prioridad</td><td>Item</td></tr><tr><td>1</td><td>Captura del comentario obligatorio en el tablero (L1)</td></tr><tr><td>2</td><td>Pruebas del endpoint HTMX</td></tr><tr><td>3</td><td>Migraciones Alembic</td></tr><tr><td>4</td><td>Parametrizar cookie.secure y añadir rate limiting</td></tr><tr><td>5</td><td>Modelos Pydantic en app/schemas/</td></tr></table>

Conclusion: el módulo es adoptable como núcleo de gestión de ciclo de vida. La mayor parte de su valor —motor de reglas, patrón de auditoría, configuración Celery— es código foundational reutilizable en proyectos con dominios distintos. El componente de interfaz requiere adaptación del contrato de datos y corrección de la limitación L1 antes de replicarse.

*Documento generado tras verificación directa del código fuente. Las cifras de líneas, los conteos de entidades, endpoints y tareas, y todas las afirmaciones sobre comportamiento reflejan el estado verificado del código en el commit 678ff274.*