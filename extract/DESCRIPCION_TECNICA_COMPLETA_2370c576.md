### 7. Capa de API

### 7.1 Superficie de endpoints (15 rutas)

<table><tr><td>Método</td><td>Ruta</td><td>Descripción</td><td>Render</td><td>Auth</td></tr><tr><td>GET</td><td>/</td><td>Redirige a /kanban (303)</td><td>—</td><td>No</td></tr><tr><td>GET</td><td>/health</td><td>Health check textual (0K)</td><td>HTML</td><td>No</td></tr><tr><td>GET</td><td>/salud</td><td>Health check en JSON</td><td>JSON</td><td>No</td></tr><tr><td>GET</td><td>/auth/login</td><td>Formulario de acceso</td><td>HTML</td><td>No</td></tr><tr><td>POST</td><td>/auth/login</td><td>Autenticación → cookie JWT + redirect (303)</td><td>—</td><td>No</td></tr><tr><td>POST</td><td>/auth/logout</td><td>Elimina cookie → redirect</td><td>—</td><td>No</td></tr><tr><td>GET</td><td>/auth/me</td><td>Perfil del usuario autenticado</td><td>JSON</td><td>Sí</td></tr><tr><td>GET</td><td>/kanban</td><td>Tablero completo</td><td>HTML</td><td>Sí</td></tr><tr><td>POST</td><td>/api/v1/kanban/tickets/{id}/mover</td><td>Movimiento de tarjeta (endpoint HTMX)</td><td>HTML</td><td>Sí</td></tr><tr><td>GET</td><td>/api/v1/kanban/columnas</td><td>Columnas en JSON para refresco</td><td>JSON</td><td>Sí</td></tr><tr><td>POST</td><td>/tickets/nuevo</td><td>Alta de ticket + auditoría CREADO</td><td>—</td><td>Sí</td></tr><tr><td>GET</td><td>/tickets/{id}/auditoria</td><td>Historial del ticket</td><td>HTML</td><td>Sí</td></tr><tr><td>GET</td><td>/api/v1/catalogos/estados</td><td>Estados + transiciones permitidas</td><td>JSON</td><td>Sí</td></tr><tr><td>GET</td><td>/api/v1/catalogos/sla</td><td>Políticas SLA activas</td><td>JSON</td><td>Sí</td></tr><tr><td>GET</td><td>/api/v1/catalogos/items?tipo=</td><td>Ítems de catálogo filtrables</td><td>JSON</td><td>Sí</td></tr></table>

Todos los endpoints salvo los tres de salud y los dos de acceso están protegidos por Depends(get_current_user).

### 7.2 El endpoint HTMX de movimiento

@router.post("/api/v1/kanban/tickets/{ticket_id}/mover", response_class=HTMLResponse)

Protocolo de éxito (2xx). Retorna exclusivamente el fragmento Jinja2 kanban/_tarjeta.html renderizado con el ticket actualizado. HTMX lo inyecta con swap: outerHTML sobre el nodo original. La interfaz se actualiza; el resto del tablero permanece intacto; no hay recarga de página.

Protocolo de fallo (403 / 422). Retorna el mensaje de error como fragmento junto con dos encabezados de control:

headers={
    "HX-Reswap": "none",
    "HX-Trigger": "kanban-error",
}

# instruye a HTMX: NO intercambies el DOM
# dispara un evento para la interfaz

HX-Reswap: none es el mecanismo que cumple el requisito funcional de «la tarjeta vuelve a su origen»: sin intercambio, el nodo que HTMX iba a reemplazar permanece donde el navegador lo dejó. Combinado con el evento kanban-error, que muestra el mensaje en una barra temporal, el usuario recibe el motivo del rechazo sin ruido visual ni recargas de página.

Códigos de estado propagados: el endpoint preserva el código del error (403 o 422) en lugar de normalizarlo a 200, de modo que cualquier monitoreo externo puede distinguir causas.

### 7.3 Autenticación y sesión

Mecanismo. Login por formulario tradicional. El servidor verifica bcrypt, genera un JWT firmado con HS256 e incluye tres claims: sub (id del usuario), iat, exp, más claims extra (rol, username). El token se almacena en cookie access token con atributos:

<table><tr><td>Atributo</td><td>Valor</td><td>Justificación</td></tr><tr><td>httponly</td><td>true</td><td>Inaccesible desde JavaScript → mitiga XSS</td></tr><tr><td>samesite</td><td>lax</td><td>(csrf básico) previene envío en navegación cruzada</td></tr><tr><td>secure</td><td>false *(hardcoded)*</td><td>Debe ser true bajo HTTPS en producción</td></tr><tr><td>max_age</td><td>jwt_expiration_minutes × 60</td><td>480 min por defecto (8 horas)</td></tr></table>

Resolución del usuario (get_current_user): acepta indistintamente la cookie o el encabezado Authorization: Bearer, lo que habilita el mismo backend tanto para sesión de navegador como para clientes API. Tras decodificar el token, revalida contra la base de datos que el usuario exista y esté activo. Esto permite revocar el acceso de una cuenta desactivada sin esperar a que expire el token.

### 7.4 Hash de contraseñas

def _to_bcrypt_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:72]

bcrypt trunca silenciosamente su entrada a 72 bytes; en versiones recientes esto lanza excepción en lugar de truncar. El módulo trunca explícitamente para conservar compatibilidad y evitar un fallo en runtime al registrar contraseñas largas o con caracteres multibyte. Coste: 12 rondas (bcrypt.gensalt(rounds=12)).

### 8. Capa de presentación

### 8.1 Filosofía de renderizado

Arquitectura Renderizado en el servidor con respuesta parcial. Jinja2 produce HTML completo en la navegación y fragmentos en las interacciones. No hay cliente SPA, ni bundler, ni package.json, ni paso de compilación.

Consecuencia operativa relevante: no existe artefacto de build. Un despliegue es un git pull y un reinicio de proceso. Esto elimina una categoría completa de fallos de despliegue y reduce el tiempo de reconstrucción a segundos.

<div>Dependencies de frontend (todas por CDN):</div>

<table><tr><td>Librería</td><td>Versión</td><td>Origen</td></tr><tr><td>TailwindCSS</td><td>CDN (JIT en navegador)</td><td>cdn.tailwindcss.com</td></tr><tr><td>HTMX</td><td>1.9.10</td><td>unpkg.com</td></tr><tr><td>SortableJS</td><td>1.15.2</td><td>cdn.jsdelivr.net</td></tr></table>

### 8.2 Integración SortableJS + HTMX

La integración de las dos librerías es donde reside la pieza más delicada del diseño, porque cada una cubre un aspecto distinto del problema:

• SortableJS resuelve el mecanismo físico del arrastre: hover, reordenamiento, animaciones, clases visuales durante el drag.

• HTMX resuelve el ciclo de red: emitir la petición y reemplazar el DOM con la respuesta del servidor.

El puente es el evento onEnd de SortableJS, que entrega evt.item (la tarjeta) y evt.to (la columna destino):

// 肃动

Los datos viajan por atributos data- $ * $ , no por inspeccionar el DOM: data-ticket-id en cada tarjeta y data-estado-id en cada columna. Esto mantiene la lógica JavaScript desacoplada de la estructura visual y permite reordenar columnas o cambiar el diseño sin tocar el código de arrastre.

Optimización de tráfico: el reordenamiento dentro de la misma columna se resuelve con una guarda if (evt.from === evt.to && evt.oldIndex === evt.newIndex) return;. Priorizar el orden manual de tarjetas no es un cambio de estado, no requiere validación ITSM, y se descarta en el cliente sin generar tráfico de red.

### 8.3 Manejo de errores en cliente

document.body.addEventListener('htmx:beforeSwap', function(evt) {
    if (evt.detail.xhr.status >= 400) {
        evt.detail.shouldSwap = false; //  $ \equiv $  HX-Reswap: none
        var bar = document.getElementById('kanban-error-bar');
        bar. 内容；
        bar.textContent = 'Error ' + evt.detail.xhr.status + '：' + evt.detail.xhr.responseText;
        bar.宫殿内容；
        setTimeout(function() {
            bar.classList.add('hidden');
            setTimeout(function() {
                location.reload();
            });
            // resincroniza estado
        });
    });
});

La recarga diferida 1,5 segundos no es un accidente: la tarjeta *visualmente* permanece en su columna de destino durante esa ventana, dando al usuario la percepción de que el movimiento funcionó, antes de que el servidor restaure la verdad. Es una compensación deliberada de la latencia percibida, aunque implica que el requisito «sin recargar» se cumple parcialmente en el camino de error.

### 8.4 Fragmentos reutilizables

<table><tr><td>Plantilla</td><td>Propósito</td></tr><tr><td>base.html</td><td>Layout, navegación, CDN, sistema de diseño</td></tr><tr><td>auth/login.html</td><td>Pantalla de acceso (centrada, sin navbar)</td></tr><tr><td>kanban/tablero.html</td><td>Tablero: columnas, modal de alta, inicialización Sortable</td></tr><tr><td>kanban/_tarjeta.html</td><td>Fragmento de tarjeta. Usado en el render inicial *y* devuelto por el endpoint HTMX</td></tr><tr><td>kanban/_auditoria.html</td><td>Historial del ticket, cargado bajo demanda</td></tr></table>

kanban/_tarjeta.html cumple doble función: se incluye con {% include %} durante el render del tablero y se devuelve como respuesta del endpoint de movimiento. Una sola definición de la tarjeta garantiza que lo que el usuario ve tras arrastrar sea idéntico a lo que habría visto en una carga completa de página. Cualquier cambio futuro en el diseño de la tarjeta se propaga automáticamente a ambos contextos.

### 8.5 Componentes de la tarjeta

<table><tr><td>Elemento</td><td>Comportamiento</td></tr><tr><td>Código (TKT-00001)</td><td>Monoespaciado, gris, referencia de negocio</td></tr><tr><td>Badge de prioridad</td><td>Color por nivel: Crítica (rojo) • Alta (naranja) • Media (azul) • Baja (gris)</td></tr><tr><td>Título</td><td>Dos líneas como máximo (line-clamp-2)</td></tr><tr><td>Indicador SLA</td><td>Punto de color con tres estados: *Sin calcular* (gris) • *En plazo* (verde) • *Vencido* (rojo)</td></tr><tr><td>Botón de auditoría</td><td>Carga el historical bajo demanda vía hx-get sin salir de la tarjeta</td></tr></table>

El color de cada columna proviene del campo color de la tabla estados y se aplica con style="background-color: {col.color;}". Reordenar columnas, renombrarlas o cambiar su color es una operación de base de datos, no una modificación de plantilla.

### 9. Seguridad

### 9.1 Controles implementados

<table><tr><td>Capa</td><td>Control</td><td>Implementación</td></tr><tr><td>Contraseñas</td><td>Hash bcrypt con sal, 12 rondas</td><td>app/core/security.py</td></tr><tr><td>Contraseñas</td><td>Truncado defensivo a 72 bytes</td><td>Evita excepción en bcrypt ≥ 4</td></tr><tr><td>Sesión</td><td>JWT HS256 con expiración de 8 h</td><td>Claims sub, iat, exp</td></tr><tr><td>Sesión</td><td>Cookie HttpOnly + SameSite=Lax</td><td>Inaccesible a JS, resistente a CSRF básico</td></tr><tr><td>Autorización</td><td>Matriz rol → privilegio por transición</td><td>usuario_tiene_permiso()</td></tr><tr><td>Autorización</td><td>Verificación de activo en cada request</td><td>Revocación inmediata</td></tr><tr><td>Entrada</td><td>Validación de enums con HTTPException 422</td><td>Prioridad, estado destino</td></tr><tr><td>Entrada</td><td>Recorte de cadenas a longitudes de columna</td><td>titulo.strip()[:255]</td></tr><tr><td>SQL</td><td>Consultas parametrizadas por el ORM</td><td>Sin concatenación de SQL en todo el código</td></tr><tr><td>Auditoría</td><td>Registro inmutable de toda mutación</td><td>Tabla append-only</td></tr><tr><td>Fuga de información</td><td>Mensajes de error sin detalle interno</td><td>Stack traces no expuestos</td></tr></table>

Ausencia total de concatenación SQL. Una revisión línea por línea del servicio y los endpoints confirma que no existe construcción dinámica de sentencias: todo acceso a datos pasa por el query builder de SQLAlchemy, que parametriza valores automáticamente.

### 9.2 Superficie de ataque conocida

<table><tr><td>Vector</td><td>Estado</td><td>Mitigación requerida en producción</td></tr><tr><td>CSRF</td><td>Parcial</td><td>SameSite=Lax mitiga el caso común. Requiere token CSRF para operaciones cross-origin</td></tr><tr><td>Cookie sobre HTTP</td><td>Abierto</td><td>secure=False hardcodeado. Debe parametrizarse</td></tr><tr><td>Fuerza bruta</td><td>No mitigada</td><td>Sin rate limiting ni bloqueo por intentos</td></tr><tr><td>SQL Injection</td><td>Cerrado</td><td>Parametrización total del ORM</td></tr><tr><td>XSS</td><td>Mitigado</td><td>Jinja2 autoescapa + HttpOnly</td></tr><tr><td>Escalada de privilegios</td><td>Cerrado</td><td>Validación por nivel de rol</td></tr><tr><td>Dependencies</td><td>Sin verificar</td><td>Ausencia de auditoría de vulnerabilidades (Dependabot/Snyk)</td></tr></table>

### 10. Configuración y despliegue

### 10.1 Variables de entorno

Gestionadas por Pydantic Settings v2 con validación en carga. El proceso falla al arrancar si falta una obligatoria, lo que impide desplegar con configuración incompleta.

<table><tr><td>Variable</td><td>Obligatoria</td><td>Default</td><td>Descripción</td></tr><tr><td>SECRET_KEY</td><td>Sí</td><td>—</td><td>Clave de firma JWT. Generar con openssl rand -hex 32</td></tr><tr><td>DATABASE_URL</td><td>Sí</td><td>—</td><td>Cadena de conexión PostgreSQL</td></tr><tr><td>REDIS_URL</td><td>No</td><td>redis://localhost:6379/0</td><td>Redis de aplicación</td></tr><tr><td>CELERY_BROKER_URL</td><td>No</td><td>redis://localhost:6379/1</td><td>Broker de Celery</td></tr><tr><td>CELERY_RESULT_BACKEND</td><td>No</td><td>redis://localhost:6379/2</td><td>Resultados de Celery</td></tr><tr><td>JWT_ALGORITHM</td><td>No</td><td>HS256</td><td>Algoritmo de firma</td></tr><tr><td>JWT_EXPIRATION_MINUTES</td><td>No</td><td>480</td><td>Duración de sesión (8 h)</td></tr><tr><td>APP_NAME</td><td>No</td><td>ITSM Kanban MVP</td><td>Nombre visible en la interfaz</td></tr><tr><td>DEBUG</td><td>No</td><td>false</td><td>Modo depuración</td></tr><tr><td>PUBLIC_BASE_URL</td><td>No</td><td>http://localhost:8000</td><td>URL pública</td></tr><tr><td>BOOTSTRAP_ADMIN_USERNAME</td><td>No</td><td>admin</td><td>Usuario inicial</td></tr><tr><td>BOOTSTRAP_ADMIN_PASSWORD</td><td>No</td><td>admin123</td><td>Cambiar en producción</td></tr><tr><td>BOOTSTRAP_ADMIN_EMAIL</td><td>No</td><td>admin@example.com</td><td>Correo inicial</td></tr></table>

Riesgo de configuración: BOOTSTRAP_ADMIN_PASSWORD tiene default admin123 y se aplica automáticamente en el primer arranque. Si se despliega sin sobrescribirla, existe una cuenta administrativa con credencial publicada en el repositorio.

### 10.2 Inicialización de base de datos

python -m app.db.init_db ejecuta una secuencia de pasos idempotentes (cada uno verifica si el recurso ya existe antes de crearlo):

<table><tr><td>Paso</td><td>Función</td><td>Resultado</td></tr><tr><td>1</td><td>_crear_tablas()</td><td>7 tablas vía create_all()</td></tr><tr><td>2</td><td>_seed_admin()</td><td>1 usuario administrador</td></tr><tr><td>3</td><td>_seed_estados()</td><td>6 estados del ciclo de vida</td></tr><tr><td>4</td><td>_seed_transiciones()</td><td>10 reglas de transición</td></tr><tr><td>5</td><td>_seed_sla()</td><td>4 políticas SLA</td></tr><tr><td>6</td><td>_seed_catalogos()</td><td>11 ítems de catálogo</td></tr><tr><td>7</td><td>_seed_tickets_ejemplo()</td><td>6 tickets, uno por estado</td></tr></table>

La idempotencia permite ejecutar el sembrado en cada arranque sin riesgo de duplicación —comportamiento construido en el hook lifespan de FastAPI, dentro de un try/except que registra pero no detiene el arranque.

### 10.3 Topología de despliegue

El módulo requiere cuatro procesos sobre infraestructura compartida:

![](extract/viewrange_chunk_2_20_24_4460a995/images/page_2_img_in_image_box_98_599_727_984.jpg)

Los tres procesos se lanzan con el mismo punto de entrada, que detecta su rol:

celery -A app.core.celery_app:celery_app worker --loglevel=info --concurrency=2
celery -A app.core.celery_app:celery_app beat --loglevel=info
uvicorn app.main:app --host 0.0.0.0 --port $PORT

Verificación de salud disponible en /health (texto) y /salud (JSON), útil como healthcheckPath en Railway, Fly.io o Kubernetes.

### 11. Pruebas automatizadas

4 pruebas unitarias sobre el servicio de negocio, todas en verde, ejecutadas sobre SQLite en memoria (StaticPool) para aislamiento completo y sin dependencias externas.

<table><tr><td>Prueba</td><td>Verifica</td></tr><tr><td>test_transicion_legal_admin</td><td>Un movimiento con regla existente y rol suficiente se ejecuta y genera exactamente un evento de auditoría con el actor_username correcto</td></tr><tr><td>test_transicion_legal</td><td>Saltarse una etapa del flujo (Pendiente → Cerrado sin regla) lanza HTTPException con código 422</td></tr><tr><td>test_comentario_requerido</td><td>Una transición con requiere_comentario=True falla sin comentario (422) y tiene éxito al proporcionarlo</td></tr><tr><td>test_auditoria_obligatoria</td><td>El recuento de eventos de auditoría se incrementa exactamente en uno por movimiento exitoso</td></tr></table>

## Características de la suite:

• Aislamiento: base SQLite en memoria creada y destruida por prueba (create_all / drop_all en fixture).

• Determinismo: el fixture siembra un estado mínimo conocido (3 estados, 2 transiciones, 1 ticket, 1 admin), sin dependencia del orden de ejecución.

• Cobertura focalizada: las pruebas apuntan a la lógica de negocio, no a la capa HTTP. No se prueba el renderizado de plantillas ni la integración con Celery.

Deficiencia reconocida: la suite no cubre el endpoint HTMX de extremo a extremo. El protocolo HX-Reswap / HX-Trigger, el fragmento devuelto y el flujo de reordenamiento dentro de la misma columna quedan sin verificar automáticamente. Una prueba con TestClient sobre el endpoint completo detectaría regresiones en el contrato entre backend y frontend.

### 12. Limitaciones técnicas

Esta sección documenta honestamente las restricciones del módulo en su estado actual. Cada una debe considerarse antes de la incorporación.

### 12.1 Limitaciones funcionales

<table><tr><td>#</td><td>Limitación</td><td>Impacto</td><td>Mitigación</td></tr><tr><td>L1</td><td>El tablero no captura el comentario obligatorio. tablero.html envía comentario: '' de forma fija. Toda transición con requiere_comentario=True (cerrar, cancelar, bloquear, devolver) siempre falla desde la interfaz</td><td>Alto</td><td>Implementar diálogo prompt() o modal antes del htmx.ajax, condicionando si la transición de destino lo exige</td></tr><tr><td>L2</td><td>La recarga en error recarga la página. El rechazo usa HX-Reswap: none correctamente, pero el setTimeout(location.reload, 1500) recarga la página completa</td><td>Medio</td><td>Eliminar el reload si la reversión visual del DOM es fiable</td></tr><tr><td>L3</td><td>Sin CRUD completo de tickets</td><td>Bajo</td><td>Solo alta y movimiento; falta edición, borrado, búsqueda y filtrado</td></tr><tr><td>L4</td><td>Sin adjuntos ni comentarios</td><td>Bajo</td><td>Los tipos de evento ADJUNTO_AGREGADO y COMENTARIO_AGREGADO están declarados pero no emitidos</td></tr><tr><td>L5</td><td>Sin notificaciones reales</td><td>Bajo</td><td>notificar cambio estado solo escribe en auditoría</td></tr><tr><td>L6</td><td>Sin i18n</td><td>Bajo</td><td>Interfaz íntegramente en español</td></tr></table>

### 12.2 Limitaciones técnicas

<table><tr><td>#</td><td>Limitación</td><td>Impacto</td></tr><tr><td>T1</td><td>Sin Alembic efectivo. alembic está en dependencias pero el esquema se crea con create_all(), que no altera tablas existentes</td><td>Cambios de esquema requieren recrear la base</td></tr><tr><td>T2</td><td>app/schemas/ está vacío. No hay modelos Pydantic de validación; los endpoints usan Form y diccionarios</td><td>Contratos de API no documentados automáticamente en OpenAPI</td></tr><tr><td>T3</td><td>_generar_codigo_ticket tiene condición de carrera. Lee max(id)+1 sin bloqueo</td><td>Dos altas concurrentes pueden colisionar; la restricción UNIQUE hace fallar la segunda</td></tr><tr><td>T4</td><td>Importaciones dinámicas con __import__() en auth.py:63 y init_db.py:160</td><td>Frágil ante refactorización; debería ser import directo</td></tr><tr><td>T5</td><td>cookie.secure hardcodeado en false</td><td>Inseguro bajo HTTPS</td></tr><tr><td>T6</td><td>La suite de pruebas tarda ~154 s. Celery intenta conectar a Redis y reintenta 20 veces por prueba</td><td>Requiere un fixture que desactive el broker en entorno de test</td></tr><tr><td>T7</td><td>app/static/js/ existe pero está vacío</td><td>Todo el JS se sirve por CDN; sin activos propios</td></tr><tr><td>T8</td><td>Dependencias de frontend por CDN sin integrity (SRI)</td><td>Riesgo de compromiso de cadena de suministro</td></tr></table>

### 12.3 Hoja de ruta de maduración

Ordenado por relación esfuerzo/beneficio:

1. Resolver L1 (captura de comentario) — desbloquea el flujo completo de cierre y cancelación

2. Añadir pruebas del endpoint HTMX — cierra el hueco de cobertura más importante

3. Introducir Alembic — requisito previo para cualquier evolución de esquema

4. Parametrizar cookie.secure y añadir rate limiting en login

5. Migrar import() a imports directos

6. Modelos Pydantic en app/schemas/ — validación y documentación automática

7. Notificaciones reales (SMTP/webhook) sobre la base ya existente

8. Internacionalización de plantillas

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