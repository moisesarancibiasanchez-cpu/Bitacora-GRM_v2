# Bitácora GRM v2 — Guía de Onboarding para Usuarios

## Navegación principal
- [Bitácora GRM](#top)
- [Inicio](#sec-1)
- [Tablero](#sec-4)
- [Drag & Drop](#sec-7)
- [Roles](#sec-11)
- [Admin](#sec-12)
- [Vistas](#sec-15)
- [Errores](#sec-21)
- [Soporte](#sec-24)
- [★ GitHub](https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2)

## Contenido (Tabla de secciones)
1. ¿Qué es Bitácora GRM? (#sec-1)
2. Registrarse e iniciar sesión (#sec-2)
3. Cambiar contraseña (#sec-3)
4. Conocer la interfaz (#sec-4)
5. Crear incidencia (#sec-5)
6. Detalle del ticket (#sec-6)
7. Mover tickets (#sec-7)
8. Filtrar el tablero (#sec-8)
9. Tickets archivados (#sec-9)
10. Búsqueda global ⌘K (#sec-10)
11. Roles y permisos (#sec-11)
12. Tareas de Administrador (#sec-12)
13. Colaborar en los comentarios (#sec-13)
14. Referenciar otros tickets (#sec-14)
15. Vistas alternativas del tablero (#sec-15)
16. Automatizaciones Butler (#sec-16)
17. Pruebas de calidad y garantías (#sec-17)
18. Seguridad y sesiones (#sec-18)
19. Cerrar sesión (#sec-19)
20. Atajos de teclado (#sec-20)
21. Errores frecuentes (#sec-21)
22. Buenas prácticas (#sec-22)
23. Glosario (#sec-23)
24. Soporte y contacto (#sec-24)

---

## Guía de Onboarding — Bitácora GRM v2

Para usuarios finales del sistema. Esta guía explica paso a paso cómo usar Bitácora GRM para registrar, gestionar y resolver incidencias, combinando la formalidad de un ITSM con la agilidad de un tablero Kanban.

---

## 01 ¿Qué es Bitácora GRM?

**Bitácora GRM** es una plataforma web de *gestión de incidencias* que combina dos enfoques:

- **ITSM (gestión estricta):** cada cambio de estado de un ticket se valida contra reglas de negocio, queda registrado en una auditoría inalterable y se mide contra Acuerdos de Nivel de Servicio (SLA).
- **Kanban (visualización ágil):** el tablero principal muestra los tickets como tarjetas que se arrastran entre columnas para cambiar su estado.

Todo funciona desde el navegador, sin instalar nada. La URL de acceso te la entrega el equipo de soporte de tu organización (ej.: `https://bitacora.tuempresa.com`).

*Arquitectura del flujo de datos: la tarjeta se arrastra en el frontend, el backend valida la transición, registra auditoría y recalcula los SLA.*

---

## 02 Tu primera vez: registrarse e iniciar sesión

### 2.1. Si tu cuenta ya existe

1. Abre el navegador y entra a la URL del sistema.
2. En la pantalla de **Iniciar sesión** escribe tu **usuario o email** y tu **contraseña**.
3. Haz clic en **Entrar**. Quedas autenticado por 8 horas (luego te pedirá volver a iniciar sesión).

*Pantalla de login con campos usuario/email y contraseña.*

### 2.2. Si NO tienes cuenta aún

1. En la pantalla de login, haz clic en el enlace **"Regístrate aquí"**.
2. Completa:
   - **Usuario** (3–64 caracteres, sin espacios; ej. `jperez`)
   - **Email** corporativo
   - **Nombre completo**
   - **Contraseña** (mínimo 6 caracteres, máximo 128)
   - **Confirmar contraseña**
3. Haz clic en **Registrarme**. Tu cuenta queda creada con rol **Solicitante** por defecto; un Administrador la elevará de rol si corresponde.
4. El sistema te autentica de forma automática y te redirige al tablero.

*Formulario de alta de cuenta — el rol inicial es Solicitante.*

**Tip:** si el registro está deshabilitado en tu organización, contacta al Administrador para que te cree la cuenta (ver [sección 12 · Tareas de Administrador](#sec-12)).

---

## 03 Cambiar tu contraseña

Recomendado hacerlo apenas ingreses por primera vez.

1. En la barra superior, haz clic en el ícono de **llave** con el texto **"Cambiar contraseña"** (esquina superior derecha).
2. En el modal que aparece, completa:
   - **Contraseña actual**
   - **Nueva contraseña** (6–128 caracteres, distinta de la actual)
   - **Confirmar nueva contraseña**
3. Haz clic en **Actualizar contraseña**.
4. Al guardar, el modal se cierra y aparece un toast verde confirmando. Tu sesión sigue activa.

Si la nueva clave es igual a la actual, el sistema rechaza con un mensaje de error y mantiene el modal abierto.

---

## 04 Conocer la interfaz principal

```
┌────────────────────────────────────────────────────────────────┐
│  Bitácora GRM     Tablero  Tickets  Usuarios [Buscar ⌘K]      │
│                                              ●Online  Juan    │
├────────────────────────────────────────────────────────────────┤
│ [Filtros 1] [Archivados]                    [+ Nueva Inc.]    │
├────────────────────────────────────────────────────────────────┤
│  NUEVO   ║  EN CURSO   ║  EN ESPERA  ║  RESUELTO  ║ CERRADO  │
│  (2)     ║  (1)        ║  (1)        ║  (1)       ║ (12)     │
│  ┌─────┐ ║  ┌─────┐    ║  ┌─────┐    ║  ┌─────┐   ║          │
│  │Tarj.│ ║  │Tarj.│    ║  │Tarj.│    ║  │Tarj.│   ║          │
│  └─────┘ ║  └─────┘    ║  └─────┘    ║  └─────┘   ║          │
│  ┌─────┐ ║             ║             ║             ║          │
│  │Tarj.│ ║             ║             ║             ║          │
│  └─────┘ ║             ║             ║             ║          │
└────────────────────────────────────────────────────────────────┘
```

- **Columnas:** cada columna representa un **estado** del flujo de trabajo. El nombre, color y orden los define el Administrador.
- **Tarjetas:** cada tarjeta es un **ticket** (incidencia). Tiene un código (ej. `INC-0042`), título, prioridad, asignado, etiquetas y un indicador de SLA.

*Vista general del tablero Kanban con cinco columnas en distintos colores.*

### Indicador de SLA

Es la esquina inferior derecha de cada tarjeta:

🟢 Verde → SLA cumplido, dentro de plazo · 🟡 Ámbar → próximo a vencer · 🔴 Rojo → vencido.

---

## 05 Crear una nueva incidencia

1. Haz clic en el botón **"+ Nueva Incidencia"** (esquina superior derecha del tablero).
2. Se abre un modal con un formulario. Completa:
   - **Título** *(obligatorio)*: resumen breve (ej. "No puedo acceder al sistema SAP").
   - **Descripción detallada**: acepta **Markdown** — puedes usar `**negrita**`, `*itálica*`, ``código``, `[link](url)`, listas y saltos de línea.
   - **Tipo**: Incidencia, Solicitud, Problema o Cambio.
   - **Prioridad**: Crítica, Alta, Media o Baja.
   - **Fecha de vencimiento (SLA)**: opcional, deadline esperado.
   - **Adjuntos**: arrastra archivos al cuadro punteado o haz clic para seleccionar.
   - **Checklist inicial** *(opcional)*: ítems a verificar al trabajar el ticket.
3. Haz clic en **Crear Incidencia**.
4. El modal se cierra, aparece un toast verde y **la tarjeta aparece en la primera columna** del tablero (estado "Nuevo") sin recargar la página.

*Modal de creación con título, descripción Markdown, tipo, prioridad, vencimiento y dropzone de adjuntos.*

**Atajo:** el botón **"Crear y abrir detalle"** (si está habilitado) crea el ticket y abre el modal de detalle para empezar a editar de inmediato.

---

## 06 Ver y editar el detalle de un ticket

1. Haz clic en cualquier parte de la tarjeta (o en el ícono de ojo 👁 en su esquina).
2. Se abre un modal con **7 pestañas**:

   | Pestaña | Qué contiene | editable en línea |
   | --- | --- | --- |
   | **Detalles** | Código, título, descripción (Markdown), prioridad, asignado, solicitante, fechas, SLA, etiquetas | Título y descripción, con botón **Guardar cambios** |
   | **Comentarios** | Hilo en orden cronológico, con adjuntos, menciones y reacciones (ver sección 13) | Sí, cada comentario |
   | **Adjuntos** | Imágenes con vista previa ampliable (lightbox), archivos descargables | Sí, con permisos |
   | **Checklist** | Ítems a marcar / desmarcar | Sí, cada ítem |
   | **Etapas** | Subtareas del módulo de garantía (UAT) | Sí |
   | **Trazabilidad** | Auditoría: quién, cuándo y qué cambió | No, solo lectura |
   | **Referencias** | Relaciones con otros tickets (ver sección 14) | Sí, se agregan y quitan |

3. Para **editar un campo en línea**: haz clic en el valor (ej. la prioridad) y elige otro. El cambio se guarda de forma automática (HTMX) y aparece un toast confirmando.
4. Para **editar el título o la descripción**: escribe en el campo y pulsa **Guardar cambios**.

   > ⚠️ **El título y la descripción NO se guardan solos.** Si cierras el modal (X, fondo oscuro o `Esc`) sin pulsar el botón, los cambios se pierden. Los campos de la cabecera (prioridad, asignado, etiquetas) sí se guardan al instante.

5. Para **agregar un comentario**: escribe en el cuadro "Escribir un comentario…" (admite Markdown) y haz clic en **Enviar**.
6. Para **subir un adjunto**: arrastra un archivo al cuadro de dropzone, o haz clic para elegir. Las imágenes se previsualizan y se pueden ampliar con un clic (lightbox).
7. Para **cerrar el modal**: clic en la X, en el fondo oscuro, o tecla `Esc`.

*Detalle del ticket con 7 pestañas (Detalles, Comentarios, Adjuntos, Checklist, Etapas, Trazabilidad, Referencias).*

---

## 07 Mover un ticket entre columnas (cambiar su estado)

**Esta es la acción principal del flujo Kanban.**

> ℹ️ **El tablero funciona en "modo libre".** No hay una matriz de transiciones: puedes mover un ticket a cualquier columna existente. El sistema valida **únicamente** que tu rol tenga permiso para mover tarjetas.

1. Haz clic y mantén presionada una tarjeta.
2. **Arrastra** la tarjeta a otra columna y suéltala encima.
3. Si tu rol tiene permiso:
   - El backend valida, actualiza el ticket, registra en auditoría y **devuelve el HTML actualizado**.
   - La tarjeta aparece en la nueva columna sin recargar la página.
   - Toast verde: "Ticket movido".
4. Si tu rol **no tiene permiso** (Solicitante u Observador):
   - La tarjeta **vuelve sola a su columna original** (rollback visual de SortableJS).
   - Toast rojo indicando que no tienes permisos.

*Drag & drop: la tarjeta se arrastra, el backend valida el permiso y la nueva ubicación queda confirmada con un toast verde.*

**Qué se valida y qué no:**

| Se valida | No se valida |
| --- | --- |
| Que tu rol tenga permiso para mover tarjetas | Que el destino sea una transición "correcta" |
| Que la columna de destino exista | Que el estado final tenga sentido con el historial del ticket |
| Que el ticket no esté archivado | Que debas dejar un comentario de justificación |

**Buenas prácticas:**

- Cada movimiento queda asentado en la pestaña **Trazabilidad** del ticket con timestamp y usuario que lo hizo.
- Como no hay bloqueos, **mantén la disciplina tú mismo**: no muevas un ticket a "Resuelto" si el trabajo no está terminado.

> ⚠️ **No hay deshacer.** Si mueves mal una tarjeta, corrígela moviéndola de vuelta y deja un comentario explicando.

---

## 08 Filtrar el tablero

El tablero puede tener cientos de tarjetas. Para encontrar lo que buscas:

1. Haz clic en **"Filtros"** en la barra superior (esquina izquierda del tablero). Aparece un panel plegable.
2. Puedes combinar:
   - **Búsqueda** por texto (título, código o descripción).
   - **Prioridad** (Crítica / Alta / Media / Baja).
   - **Asignado** (un agente específico).
   - **Etiqueta** (un color / categoría).
   - **Solo mis tickets** (casilla) → filtra a los asignados a ti.
   - **Solo críticos** (casilla).
3. El contador en el chip **"Filtros N"** muestra cuántos filtros tienes activos.
4. Haz clic en **Limpiar** para borrar todos los filtros.

*Panel de filtros con búsqueda, prioridad, asignado, etiqueta y toggles.*

Los filtros son **client-side**: aplican de forma instantánea, sin recargar.

---

## 09 Tickets archivados

Los tickets cerrados (o cancelados) se mueven al archivo:

1. Haz clic en **"Archivados"** en la barra superior.
2. Se abre un modal con todos los tickets archivados.
3. Desde ahí puedes buscar, filtrar y **reabrir** un ticket si necesitas volver a trabajarlo.

*Listado de tickets cerrados con búsqueda y acción de reabrir.*

Los archivados no ocupan espacio visual en el tablero principal.

---

## 10 Búsqueda global (atajo ⌘K / Ctrl+K)

1. Haz clic en el cuadro **"Buscar…"** en la barra superior, o presiona `Ctrl`+`K` (Windows/Linux) o `⌘`+`K` (Mac).
2. Se abre un **Command Palette**: empieza a escribir.
3. La búsqueda recorre: tickets (código / título / descripción), usuarios (solo si eres admin) y comandos rápidos (ej. "crear ticket", "ir a usuarios").
4. Navega con ↑/↓ y presiona `Enter` para abrir el resultado.

*Paleta de comandos con resultados de tickets y comandos rápidos.*

---

## 11 Roles y permisos

El sistema tiene **5 roles** con permisos crecientes:

*Pirámide de roles: cada nivel hereda los permisos del inferior.*

### 11.1. Uso esperado por rol

| Rol | Puede | No debería |
| --- | --- | --- |
| **Solicitante** | Crear tickets, comentar en los suyos, agregar adjuntos. | Cambiar estado, asignar, cerrar tickets ajenos, ver tablero global. |
| **Observador** | Ver el tablero y la auditoría en modo lectura. | Crear, editar, comentar o mover nada. |
| **Agente** | Atender tickets asignados: cambiar estado, comentar, adjuntar, marcar checklist. | Reasignar, cerrar tickets no asignados, ver auditoría global. |
| **Agente Senior** | Todo lo anterior + reasignar, cerrar tickets, editar la mayoría de campos. | Gestionar usuarios ni crear columnas. |
| **Administrador** | Acceso total: gestionar usuarios, columnas, catálogos, ver toda la auditoría y reportes. | — |

Tu rol aparece como un chip de color en la barra superior, al lado de tu nombre.

### 11.2. Qué valida el sistema de verdad

> ⚠️ **Sé honesto con esto:** la tabla anterior describe la política de uso esperada. El sistema **solo aplica de forma automática unas pocas restricciones**. Conocer la diferencia te evita sorpresas.

**Permisos que el sistema comprueba de verdad:**

| Permiso | Dónde se comprueba |
| --- | --- |
| `cambiar_estado` | Al arrastrar una tarjeta a otra columna, y en la API al cambiar el estado |
| `crear_ticket` | Al crear una incidencia |
| `comentar` | Al enviar un comentario |
| `adjuntar_archivos` | Al subir un archivo |
| `ver_auditoria` | Al abrir la vista de auditoría |
| `gestionar_usuarios` | Al entrar a la sección de Usuarios |
| `gestionar_columnas` | Al crear, editar o eliminar columnas |

**Lo que NO está restringido por el sistema (lo controla la disciplina del equipo):**

- No hay matriz de transiciones: puedes mover un ticket a cualquier columna si tienes permiso de mover (ver sección 07).
- No es obligatorio dejar un comentario al cerrar, cancelar o reabrir un ticket.
- Un Agente puede abrir tickets que no tiene asignados, siempre que su rol permita crearlos.
- No se comprueba que un ticket esté realmente resuelto antes de pasarlo a "Resuelto".

> **En la práctica:** el único control de acceso que se activa sin que tú hagas nada es el del **movimiento de tarjetas**. El resto depende de que respetes las convenciones del equipo.

---

## 12 Si eres Administrador: tareas adicionales

### 12.1. Crear / editar usuarios

1. En la barra superior, haz clic en **"Usuarios"** (solo visible para administradores).
2. Acciones por fila:
   - ✉️ **Email**: previsualizar y enviar credenciales por correo al usuario (genera una contraseña provisoria aleatoria).
   - ✏️ **Editar**: cambiar nombre, email, departamento, rol o estado activo/inactivo.
   - 🔑 **Cambiar contraseña**: resetear la contraseña de otro usuario (tú defines el valor; no necesitas conocer la actual).
   - 🟢/🔴 **Activar / Desactivar**: soft-delete del usuario.
3. **Crear un usuario nuevo**: haz clic en **"+ Nuevo Usuario"**, completa el formulario y haz clic en **Crear**.

*Tabla de usuarios con columnas: usuario, nombre, rol, estado y acciones (email, editar, reset, activar).*

*Modal de reset de contraseña: el admin define el nuevo valor, sin necesidad de conocer la actual.*

### 12.2. Gestionar el flujo (columnas)

1. En el tablero, haz clic en el botón **"+ Añadir columna"** (esquina derecha). Completa nombre y color.
2. Para **renombrar** una columna: clic en el título o en el ícono de lápiz.
3. Para **asignar un responsable** a una columna: clic en "responsable" dentro del header; elige un agente. A partir de ese momento, **todos los tickets que caigan en esa columna disparan un correo electrónico automático** al responsable.
4. Para **reordenar** columnas: arrastra de forma horizontal por el body de la columna. El nuevo orden se guarda de manera automática. Si la API falla, el tablero se recarga para volver al estado real de la BD.

*Configuración de columnas: color, responsable y acciones (editar, eliminar).*

### 12.3. Eliminar / desactivar una columna

Antes de eliminar una columna, **mueve todos sus tickets a otra columna**. Si la columna aún tiene tickets, el sistema te advertirá al intentar eliminarla.

### 12.4. Ver la auditoría

La auditoría está disponible en cada ticket (pestaña **"Trazabilidad"**). Cada cambio registra: timestamp, usuario, acción, valor anterior y valor nuevo.

---

## 13 Colaborar en los comentarios de un ticket

La pestaña **Comentarios** es el canal de trabajo del equipo. No es solo un registro: se puede usar casi como un chat interno.

*Comentario con mención, adjuntos, reacciones, ventana de edición y comentario interno.*

### 13.1. Qué puedes hacer en un comentario

| Acción | Cómo | Límite |
| --- | --- | --- |
| Escribir en Markdown | Escribe con normalidad: `**negrita**`, listas, código | 5000 caracteres |
| Adjuntar archivos | Arrastra o haz clic; también puedes **pegar una captura con `Ctrl+V`** | Tamaño máximo del archivo |
| Mencionar a alguien | Escribe `@usuario` y elige del desplegable | Avisa al mentioned |
| Editar | Pulsa el ícono de editar sobre tu comentario | Solo durante **30 minutos** |
| Marcar como interno | Casilla "Interno" al escribir | Solo el equipo lo ve |
| Reaccionar | Pulsa una reacción bajo el comentario | Sustituye escribir un "OK" |

### 13.2. La ventana de 30 minutos

Después de escribir un comentario tienes **30 minutos** para editarlo. El botón muestra el tiempo restante en cuenta atrás.

Superados los 30 minutos el comentario queda **fijo**: no se puede modificar ni borrar. La forma correcta de corregirlo es escribir un comentario nuevo indicando qué cambió.

### 13.3. Comentarios internos

Un comentario marcado como **interno** es visible solo para el equipo. **El solicitante nunca lo ve.**

Úsalo para debates técnicos, decisiones internas o notas de coordinación. Todo lo que el solicitante deba leer, va en un comentario normal.

---

## 14 Referenciar otros tickets

La pestaña **Referencias** conecta un ticket con otros, para que las dependencias queden explícitas y no solo en tu memoria.

*Tres tickets unidos por referencias de tipo bloquea, duplicado de y padre.*

### 14.1. Los seis tipos de referencia

| Tipo | Qué significa | ¿Es simétrico? |
| --- | --- | --- |
| **Relacionado** | Tiene relación con este ticket | Sí |
| **Duplicado** | Es el mismo problema reportado dos veces | Sí |
| **Padre** | Este ticket es parte de uno mayor | No → genera **Hijo** |
| **Hijo** | Es parte de este ticket mayor | No → genera **Padre** |
| **Bloquea** | Este ticket impide que el otro avance | No → genera **Bloqueado por** |
| **Bloqueado por** | Este ticket no puede avanzar hasta que el otro se resuelva | No → genera **Bloquea** |

Cuando creas una referencia, el sistema guarda **la inversa automáticamente**. Si dices "A bloquea a B", en B aparecerá "bloqueado por A" sin que tengas que hacer nada.

### 14.2. Cómo agregarlas

1. Abre el ticket y ve a la pestaña **Referencias**.
2. Selecciona el tipo de relación.
3. Busca el ticket destino por código o título.
4. Pulsa **Agregar**.

Para quitar una referencia, haz clic en la **X** a su lado.

### 14.3. Cómo usarlas bien

- **¿Es duplicado?** Enlaza ambos y cierra uno como duplicado, en lugar de dejar dos tickets vivos.
- **¿Hay dependencia real?** Usa *bloquea* en lugar de un comentario que diga "esperando a…". La dependencia queda consultable desde las dos partes.
- **¿Es un caso grande?** Usa *padre / hijo* para agrupar los subttrabajos sin crear un ticket gigante.

---

## 15 Vistas alternativas del tablero

El mismo conjunto de tickets se puede leer de **siete maneras**. Cambiar de vista no crea ni modifica ningún dato.

*Selector de vistas con los siete modos disponibles.*

| Vista | Para qué sirve |
| --- | --- |
| **Tablero** | El flujo visual por columnas, con arrastrar y soltar |
| **Tabla** | Ver y ordenar muchos tickets de un vistazo; permite ordenar por cualquier columna |
| **Calendario** | Programación por fecha de vencimiento, semana a semana |
| **Línea de tiempo** | Encadena tickets que dependen unos de otros (#95 → #128 → #131) |
| **Gantt** | Las etapas de un caso, en barras por fecha |
| **Planificador** | Capacidad por sprint: lo comprometido frente a lo posible |
| **Panel** | Indicadores agrupados, solo lectura, para informes rápidos |

Los **filtros** de la sección 8 se mantienen al cambiar de vista: si estás filtrando por "solo los míos", ese filtro sigue activo en las siete.

---

## 16 Automatizaciones Butler

**Butler** es el motor de automatizaciones. Una regla reacciona a un disparador, comprueba sus condiciones y ejecuta sus acciones.

*Regla de automatización con disparador, condiciones, acciones y registro de ejecuciones.*

### 16.1. Disparadores

Una regla empieza a evaluarse cuando ocurre uno de estos seis eventos:

| Disparador | Se dispara cuando |
| --- | --- |
| `ticket_creado` | Se crea un ticket |
| `ticket_asignado` | Se asigna un responsable |
| `ticket_etiquetado` | Se le pone o quita una etiqueta |
| `ticket_estado_cambiado` | Un ticket entra en una columna nueva |
| `cada_dia` | Llega la ejecución programada diaria |
| `cada_semana` | Llega la ejecución programada semanal |

### 16.2. Condiciones

Cada condición compara un campo del ticket con un valor. Si **todas** se cumplen, la regla corre; si alguna falla, no hace nada.

Ejemplo: `prioridad` **igual a** `critica` **y** `columna` **igual a** `nuevo`.

### 16.3. Acciones

Se ejecutan **en el orden en que las definiste**, de arriba abajo:

`set_estado` · `set_asignado` · `add_etiqueta` · `remove_etiqueta` · `add_comentario` · `notify` · `archive` · `backup_database` · `backup_cleanup`

### 16.4. Prioridad entre reglas

Cuando varias reglas son aplicables al mismo evento, se ejecutan **de menor a mayor número de prioridad**. La prioridad por defecto es `100`.

Ejemplo: una regla con prioridad `10` corre antes que otra con `50`.

### 16.5. Registro de ejecuciones

Cada ejecución queda guardada indicando la regla, el ticket afectado, si terminó correctamente y el detalle. Puedes consultarlo para auditar qué hizo la regla y por qué.

> **Una regla desactivada no se ejecuta, pero conserva toda su configuración.** Actívala cuando vuelva a hacer falta.

---

## 17 Datos de pruebas y expedientes de garantía

Los tickets del módulo de garantía llevan datos de pruebas de calidad y un código de expediente.

*Campos de pruebas de calidad y construcción del código GAR.*

### 17.1. Campos de pruebas

| Campo | Valores |
| --- | --- |
| **Módulo** | 11 valores (Control ERM, Gobierno, Incidencias, Validación, Auditoría, Filiales, Información Inventario, Registro de Información, Documentación, Mejoras Transversales, Seguimiento y Control) |
| **Ambiente** | `QA` · `PRODUCCION` |
| **Ítem a probar** | `Portal WEB APEX` · `Email` · `Base de Datos` |
| **Resultado de pruebas** | `OK` · `N/A` · `OK CON OBS.` · `NOK` · `POSTERGADA` · `DESESTIMADA` |
| **QA Tester** | Se guarda como `Nombre <email>` para que quede trazable quién probó |

> El resultado de pruebas es **una marca de seguimiento, no un bloqueo.** Marcar `NOK` no impide mover el ticket a "Resuelto": esa decisión sigue siendo del agente responsable.

### 17.2. El código GAR

Cada caso de prueba tiene un código con el formato:

```
GAR_<código del caso>-<correlativo de 3 dígitos>
```

Por ejemplo, `GAR_HU128-003`.

- El **código del caso** se toma del archivo de carga.
- El **correlativo** avanza con cada fila importada.
- Si el caso **no trae código**, el sistema genera `GAR_SIN-00042`.
- Si el código completo **supera los 20 caracteres**, se trunca.

---

## 18 Seguridad y sesiones

*Cabeceras de seguridad de la respuesta HTTP, modelo de sesión y almacenamiento de la contraseña.*

### 18.1. Tu sesión

1. Al iniciar sesión, el servidor crea una sesión firmada y la devuelve en una **cookie**.
2. En cada petición posterior, esa cookie identifica tu sesión y el servidor la valida.
3. Al cerrar sesión, la sesión se **invalida** y la cookie deja de servir.

La sesión expira automáticamente después de **8 horas de inactividad**.

### 18.2. Tu contraseña

Las contraseñas **nunca se guardan en texto plano**: se almacena su *hash* con una *sal* por usuario. Dos personas con la misma contraseña tienen hashes distintos, así que no se puede deducir una de la otra.

> **Consecuencia práctica:** si alguien te pide tu contraseña, ni siquiera un administrador puede leerla.

### 18.3. Cabeceras de seguridad

Cada respuesta del servidor incluye:

| Cabecera | Qué hace |
| --- | --- |
| `X-Frame-Options: DENY` | Impide que la página se incruste en un iframe de otro sitio (clickjacking) |
| `X-Content-Type-Options: nosniff` | Evita que el navegador interprete un archivo con un tipo distinto al declarado |
| `Referrer-Policy: strict-origin-when-cross-origin` | Limita qué URL se comparte al saltar a otro sitio |
| `Cache-Control: max-age=300` | Las páginas se guardan en caché 5 minutos y luego se vuelven a pedir |

### 18.4. Buenas prácticas de seguridad

- **No compartas tu cuenta.** Cada persona debe tener la suya: así la auditoría registra de verdad quién hizo cada cambio (ver sección 11).
- **Cierra sesión** al terminar, sobre todo si usas un equipo compartido.
- **No pegues contraseñas ni datos sensibles** en los comentarios: quedan visibles para todo el equipo.

---

## 19 Cerrar sesión

1. Haz clic en **"Salir"** (esquina superior derecha).
2. El sistema invalida tu sesión y te redirige a la pantalla de login.

La sesión también expira de forma automática después de **8 horas de inactividad**.

---

## 20 Atajos de teclado útiles

*Resumen visual de los atajos principales.*

| Atajo | Acción |
| --- | --- |
| `Ctrl` + `K` / `⌘` + `K` | Abre la búsqueda global |
| `Esc` | Cierra cualquier modal abierto |
| `Enter` en un input | Confirma el formulario del modal |
| Clic + arrastrar en tarjeta | Mueve el ticket a otra columna |
| Clic + arrastrar en columna *(admin)* | Reordena columnas |
| Clic en tarjeta | Abre el detalle |

---

## 21 Errores frecuentes y cómo resolverlos

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| Toast rojo "No tienes permisos para realizar esta acción" | Tu rol no permite esa acción | Pide a un administrador que te otorgue el rol correspondiente |
| Toast rojo al arrastrar una tarjeta | Tu rol no tiene permiso para mover tarjetas en el tablero (Solicitante u Observador) | Si debes moverlas, pídele a un administrador que eleve tu rol a Agente |
| La tarjeta vuelve a su columna original al soltarla | El backend rechazó el movimiento | Revisa el toast para ver el motivo exacto |
| Editaste el título o la descripción y no se guardó | Cerraste el modal sin pulsar **Guardar cambios** | Vuelve a abrir el ticket y guarda antes de cerrar |
| El comentario dice "ventana de edición cerrada" | Pasaron más de 30 minutos desde que lo escribiste | Escribe un comentario nuevo indicando la corrección |
| "Sesión expirada — Recarga la página" | Pasaron 8 horas sin actividad | Recarga la página y vuelve a iniciar sesión |
| La pantalla se queda en "Cargando…" | Fallo de red transitorio | Espera unos segundos; si persiste, recarga |
| Las imágenes de los adjuntos no se ven | Tu navegador bloqueó el lightbox (cookies/storage) | Habilita almacenamiento local para el dominio |
| No puedes crear columnas / usuarios | No eres Administrador | Pide a un Admin que haga el cambio, o solicita elevación de rol |

---

## 22 Buenas prácticas

- **Título claro y específico:** evita "Ayuda" o "No anda"; prefiere "Error 500 al guardar pedido en módulo ventas".
- **Descripción reproducible:** incluye pasos para reproducir el problema, mensajes de error textuales, capturas y URLs afectadas.
- **Prioridad correcta:** Crítica = negocio detenido. Alta = bloqueo importante. Media = afecta, pero hay workaround. Baja = mejora o consulta.
- **Asignación temprana:** si sabes quién debe resolver, asigna directamente al soltarlo en su columna.
- **Comentarios contextuales:** cada vez que avances en el ticket, deja un comentario (incluso para "sigo investigando"). Eso permite a tu equipo y al solicitante ver el avance.
- **Usa las menciones:** si necesitas la respuesta de alguien, escribe `@usuario` en lugar de esperar a que lea el hilo.
- **Enlaza las dependencias:** si un ticket espera a otro, usa la pestaña Referencias en lugar de decirlo solo en un comentario.
- **Checklist para tareas complejas:** si el ticket tiene varios pasos, usa el checklist. Cada ítem es una subtarea clara.
- **Cierra tickets cuando corresponda:** un ticket "resuelto" sin cerrar termina ocupando capacidad del tablero.

---

## 23 Glosario

| Término | Definición |
| --- | --- |
| **Ticket / Incidencia** | Unidad de trabajo. Representa un problema, solicitud, cambio o problema conocido. |
| **Estado** | Columna del Kanban. Define en qué fase está el ticket. |
| **Prioridad** | Urgencia del ticket (Crítica / Alta / Media / Baja). |
| **SLA** | Service Level Agreement — tiempo objetivo de resolución. Si vence, el indicador se pone rojo. |
| **Asignado** | Agente responsable de resolver el ticket. |
| **Solicitante** | Quien reporta la incidencia. |
| **Auditoría / Trazabilidad** | Registro inalterable de todos los cambios (quién, cuándo, qué). |
| **Columna con responsable** | Cada vez que un ticket cae en esa columna, se notifica por correo electrónico al responsable. |
| **Archivado** | Ticket cerrado que ya no aparece en el tablero principal. |
| **Command Palette** | Buscador global (`⌘`+`K` / `Ctrl`+`K`). |
| **Referencia** | Relación entre dos tickets: bloquea, duplicado, padre/hijo, etc. (ver sección 14). |
| **Butler** | Motor de automatizaciones que ejecuta reglas según un disparador y sus condiciones (ver sección 16). |
| **GAR** | Código del expediente de un caso de prueba del módulo de garantía (ver sección 17). |

---

## 24 Soporte y contacto

- **Soporte de primer nivel:** equipo de Mesa de Ayuda de tu organización.
- **Errores del sistema / solicitudes de mejora:** crear un ticket en Bitácora GRM con prioridad "Media" o "Baja".
- **Problemas críticos del propio sistema:** contacta directamente al equipo de desarrollo (ver [README en GitHub](https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2)).

**Bitácora GRM v2** — Sistema híbrido ITSM + Kanban.

*Hecho con FastAPI · PostgreSQL · Redis/Celery · HTMX.*

---

## Footer

### Bitácora GRM v2
Sistema híbrido de gestión de incidencias que combina la formalidad de un ITSM con la agilidad de un tablero Kanban. Desplegado en Railway.

### Documentación
- [¿Qué es?](#sec-1)
- [Interfaz](#sec-4)
- [Roles](#sec-11)
- [Glosario](#sec-23)

### Proyecto
- [Repositorio en GitHub](https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2)
- [Soporte](#sec-24)
- [Errores frecuentes](#sec-21)

© Bitácora GRM v2 · Documentación generada por MiniMax Agent · Última actualización: octubre 2026
