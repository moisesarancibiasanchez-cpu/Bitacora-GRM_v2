"""
Renderizador Jinja2 para el modal de detalle de un ticket.

El endpoint ``GET /api/v1/tickets/{id}/detalle-html`` invoca
``render_detalle_modal`` y devuelve el HTML al frontend, donde HTMX lo
inserta en ``#modal-root``.

El modal contiene 4 pestañas:
  1. Detalles      -> datos del ticket + cambio de estado / asignación
  2. Comentarios   -> listado + formulario para agregar
  3. Adjuntos      -> lista + dropzone para subir archivos
  4. Checklist     -> tareas con checkboxes

Los formularios internos usan ``hx-post`` y ``hx-target`` configurados
para recargar solo el modal tras cada acción, sin recargar la página
completa.
"""
from datetime import datetime
from typing import Iterable

from jinja2 import Template


# ---------------------------------------------------------------------------
#  Sub-renderers (cada bloque del modal)
# ---------------------------------------------------------------------------

DETALLE_TEMPLATE = Template(r"""
<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop"
     data-modal="detalle-ticket" data-ticket-id="{{ ticket.id }}">
  <div class="bg-white rounded-xl shadow-2xl w-full max-w-3xl mx-4 overflow-hidden flex flex-col max-h-[92vh]">

    <!-- ============== HEADER ============== -->
    <div class="px-5 py-4 border-b border-slate-200 flex items-start justify-between gap-3 flex-shrink-0">
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 mb-1">
          <span class="font-mono text-xs text-slate-500">{{ ticket.codigo }}</span>
          <span class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold
                       {% if ticket.prioridad.value == 'critica' %}bg-red-100 text-red-700
                       {% elif ticket.prioridad.value == 'alta' %}bg-orange-100 text-orange-700
                       {% elif ticket.prioridad.value == 'media' %}bg-yellow-100 text-yellow-700
                       {% else %}bg-slate-100 text-slate-600{% endif %}">
            {{ ticket.prioridad.value|upper }}
          </span>
          <span class="inline-flex items-center gap-1 text-[10px] text-slate-500">
            <span class="inline-block w-2 h-2 rounded-full" style="background-color: {{ ticket.estado.color }}"></span>
            {{ ticket.estado.nombre }}
          </span>
        </div>
        {# Título editable: input que auto-guarda con HTMX al perder foco o presionar Enter #}
        <form hx-patch="/api/v1/tickets/{{ ticket.id }}"
              hx-target="#modal-root" hx-swap="innerHTML"
              hx-trigger="blur changed delay:800ms from:input[name='valor_titulo']"
              class="m-0 p-0">
          <input type="hidden" name="campo" value="titulo">
          <input type="hidden" name="active_tab" value="{{ _active }}">
          <input type="text" name="valor_titulo" value="{{ ticket.titulo }}"
                 aria-label="Título del ticket"
                 class="w-full text-base font-semibold text-slate-800 leading-snug bg-transparent border-0 border-b border-transparent
                        hover:border-slate-200 focus:border-indigo-400 focus:ring-0 px-0 py-0.5 transition-colors" />
        </form>
      </div>
      <button data-close-modal
              class="w-8 h-8 rounded-md flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100 flex-shrink-0">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
        </svg>
      </button>
    </div>

    <!-- ============== TABS ============== -->
    {% set _active = active_tab or 'detalles' %}
    <div class="border-b border-slate-200 px-5 flex items-center gap-1 flex-shrink-0" role="tablist">
      <button class="tab-btn px-3 py-2.5 text-xs font-medium border-b-2 {% if _active == 'detalles' %}border-indigo-600 text-indigo-700{% else %}border-transparent text-slate-500 hover:text-slate-700{% endif %}"
              data-tab="detalles">Detalles</button>
      <button class="tab-btn px-3 py-2.5 text-xs font-medium border-b-2 {% if _active == 'comentarios' %}border-indigo-600 text-indigo-700{% else %}border-transparent text-slate-500 hover:text-slate-700{% endif %}"
              data-tab="comentarios">
        Comentarios
        <span class="ml-1 px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10px]">{{ comentarios|length }}</span>
      </button>
      <button class="tab-btn px-3 py-2.5 text-xs font-medium border-b-2 {% if _active == 'adjuntos' %}border-indigo-600 text-indigo-700{% else %}border-transparent text-slate-500 hover:text-slate-700{% endif %}"
              data-tab="adjuntos">
        Adjuntos
        <span class="ml-1 px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10px]">{{ adjuntos|length }}</span>
      </button>
      <button class="tab-btn px-3 py-2.5 text-xs font-medium border-b-2 {% if _active == 'checklist' %}border-indigo-600 text-indigo-700{% else %}border-transparent text-slate-500 hover:text-slate-700{% endif %}"
              data-tab="checklist">
        Checklist
        <span class="ml-1 px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10px]">{{ checklists|length }}</span>
      </button>
      <button class="tab-btn px-3 py-2.5 text-xs font-medium border-b-2 {% if _active == 'trazabilidad' %}border-indigo-600 text-indigo-700{% else %}border-transparent text-slate-500 hover:text-slate-700{% endif %}"
              data-tab="trazabilidad">
        Trazabilidad
        <span class="ml-1 px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10px]">{{ auditorias|length }}</span>
      </button>
    </div>

    <!-- ============== BODY ============== -->
    <div class="flex-1 overflow-y-auto">

      <!-- Tab: Detalles -->
      <div class="tab-panel {% if _active != 'detalles' %}hidden{% endif %} p-5 space-y-4" data-panel="detalles">

        {# ----- Descripción editable ----- #}
        <div>
          <h4 class="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Descripción</h4>
          <form hx-patch="/api/v1/tickets/{{ ticket.id }}"
                hx-target="#modal-root" hx-swap="innerHTML"
                hx-trigger="blur changed delay:800ms from:textarea[name='valor_descripcion']"
                class="m-0 p-0">
            <input type="hidden" name="campo" value="descripcion">
            <input type="hidden" name="active_tab" value="{{ _active }}">
            <textarea name="valor_descripcion" rows="3"
                      placeholder="Sin descripción..."
                      class="w-full text-sm text-slate-700 bg-transparent border-0 border-b border-transparent
                             hover:border-slate-200 focus:border-indigo-400 focus:ring-0 px-0 py-1 transition-colors resize-y whitespace-pre-wrap">{{ ticket.descripcion or '' }}</textarea>
          </form>
        </div>

        {# ----- Grid de campos ----- #}
        <div class="grid grid-cols-2 gap-3 text-xs">

          <div>
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Tipo</span>
            <span class="text-slate-700">{{ ticket.tipo.value }}</span>
          </div>

          {# Prioridad editable #}
          <div>
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-0.5">Prioridad</span>
            <form hx-patch="/api/v1/tickets/{{ ticket.id }}"
                  hx-target="#modal-root" hx-swap="innerHTML"
                  hx-trigger="change from:select[name='valor_prioridad']"
                  class="m-0 p-0">
              <input type="hidden" name="campo" value="prioridad">
              <input type="hidden" name="active_tab" value="{{ _active }}">
              <select name="valor_prioridad"
                      class="text-xs bg-transparent border-0 border-b border-transparent hover:border-slate-200 focus:border-indigo-400 focus:ring-0 px-0 py-0.5 w-full">
                {% for p in ['baja','media','alta','critica'] %}
                <option value="{{ p }}" {% if ticket.prioridad.value == p %}selected{% endif %}>{{ p|capitalize }}</option>
                {% endfor %}
              </select>
            </form>
          </div>

          <div>
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Creador</span>
            <span class="text-slate-700">{{ ticket.creador.nombre_completo if ticket.creador else '—' }}</span>
          </div>

          {# Asignado editable #}
          <div>
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-0.5">Asignado</span>
            <form hx-patch="/api/v1/tickets/{{ ticket.id }}"
                  hx-target="#modal-root" hx-swap="innerHTML"
                  hx-trigger="change from:select[name='valor_asignado_id']"
                  class="m-0 p-0">
              <input type="hidden" name="campo" value="asignado_id">
              <input type="hidden" name="active_tab" value="{{ _active }}">
              <select name="valor_asignado_id"
                      class="text-xs bg-transparent border-0 border-b border-transparent hover:border-slate-200 focus:border-indigo-400 focus:ring-0 px-0 py-0.5 w-full">
                <option value="0">— sin asignar —</option>
                {% for u in usuarios %}
                <option value="{{ u.id }}" {% if ticket.asignado_id == u.id %}selected{% endif %}>{{ u.nombre_completo }}</option>
                {% endfor %}
              </select>
            </form>
          </div>

          {# Fecha de vencimiento editable #}
          <div>
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-0.5">Fecha de vencimiento</span>
            <form hx-patch="/api/v1/tickets/{{ ticket.id }}"
                  hx-target="#modal-root" hx-swap="innerHTML"
                  hx-trigger="change from:input[name='valor_fecha_vencimiento']"
                  class="m-0 p-0">
              <input type="hidden" name="campo" value="fecha_vencimiento">
              <input type="hidden" name="active_tab" value="{{ _active }}">
              <input type="date" name="valor_fecha_vencimiento"
                     value="{{ ticket.fecha_vencimiento_sla.strftime('%Y-%m-%d') if ticket.fecha_vencimiento_sla else '' }}"
                     class="text-xs bg-transparent border-0 border-b border-transparent hover:border-slate-200 focus:border-indigo-400 focus:ring-0 px-0 py-0.5 w-full" />
            </form>
          </div>

          <div>
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Creado</span>
            <span class="text-slate-700">{{ ticket.created_at.strftime('%Y-%m-%d %H:%M') if ticket.created_at else '—' }}</span>
          </div>
        </div>

        {# ----- Etiquetas editables ----- #}
        <div>
          <div class="flex items-center justify-between mb-1.5">
            <h4 class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Etiquetas</h4>
            {% if etiquetas_disponibles %}
            <details class="relative">
              <summary class="list-none cursor-pointer text-[10px] text-indigo-600 hover:text-indigo-800 font-medium inline-flex items-center gap-0.5">
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                Gestionar
              </summary>
              <div class="absolute right-0 mt-1 w-64 max-h-48 overflow-y-auto bg-white border border-slate-200 rounded-md shadow-lg z-10 p-1.5 space-y-1">
                {% set _etiquetas_actuales_ids = ticket.etiquetas|map(attribute='id')|list %}
                {% for et in etiquetas_disponibles %}
                <div class="flex items-center justify-between gap-2 px-2 py-1 hover:bg-slate-50 rounded">
                  <div class="flex items-center gap-1.5 min-w-0">
                    <span class="inline-block w-2 h-2 rounded-full flex-shrink-0" style="background-color: {{ et.color }}"></span>
                    <span class="text-xs text-slate-700 truncate">{{ et.nombre }}</span>
                  </div>
                  {% if et.id in _etiquetas_actuales_ids %}
                    <button class="text-[10px] text-red-600 hover:text-red-800 font-medium"
                            hx-delete="/api/v1/tickets/{{ ticket.id }}/etiquetas/{{ et.id }}"
                            hx-target="#modal-root" hx-swap="innerHTML"
                            hx-trigger="click"
                            onclick="event.stopPropagation()">
                      Quitar
                    </button>
                  {% else %}
                    <button class="text-[10px] text-emerald-600 hover:text-emerald-800 font-medium"
                            hx-post="/api/v1/tickets/{{ ticket.id }}/etiquetas/{{ et.id }}"
                            hx-target="#modal-root" hx-swap="innerHTML"
                            hx-trigger="click"
                            onclick="event.stopPropagation()">
                      Agregar
                    </button>
                  {% endif %}
                </div>
                {% endfor %}
              </div>
            </details>
            {% endif %}
          </div>
          <div class="flex flex-wrap gap-1.5">
            {% if ticket.etiquetas %}
              {% for et in ticket.etiquetas %}
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium"
                      style="background-color: {{ et.color }}20; color: {{ et.color }};">
                  <span class="inline-block w-1.5 h-1.5 rounded-full" style="background-color: {{ et.color }}"></span>
                  {{ et.nombre }}
                  <button class="ml-0.5 text-slate-400 hover:text-red-500"
                          hx-delete="/api/v1/tickets/{{ ticket.id }}/etiquetas/{{ et.id }}"
                          hx-target="#modal-root" hx-swap="innerHTML"
                          title="Quitar etiqueta">×</button>
                </span>
              {% endfor %}
            {% else %}
              <span class="text-[11px] text-slate-400 italic">Sin etiquetas</span>
            {% endif %}
          </div>
        </div>

        {# ----- Campos personalizados ----- #}
        {% if campos_personalizados %}
        <div class="pt-3 border-t border-slate-100">
          <h4 class="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-2">Campos personalizados</h4>
          <div class="space-y-2">
            {% for cp in campos_personalizados %}
              <div class="flex items-center gap-2 text-xs">
                <span class="text-slate-600 font-medium min-w-[120px] flex items-center gap-1">
                  <span class="inline-block w-1.5 h-1.5 rounded-full" style="background-color: {{ cp.color or '#6366f1' }}"></span>
                  {{ cp.nombre }}
                  {% if cp.requerido %}<span class="text-red-500">*</span>{% endif %}
                </span>
                <form hx-patch="/api/v1/tickets/{{ ticket.id }}/campos/{{ cp.id }}"
                      hx-target="#modal-root" hx-swap="innerHTML"
                      hx-trigger="change from:select[name='valor_campo'], input delay:600ms from:input[name='valor_campo'], change from:input[type='checkbox'][name='valor_campo']"
                      class="m-0 p-0 flex-1">
                  <input type="hidden" name="active_tab" value="{{ _active }}">
                  {% if cp.tipo == 'texto' or cp.tipo == 'url' %}
                    <input type="{{ 'url' if cp.tipo == 'url' else 'text' }}"
                           name="valor_campo"
                           value="{{ cp.valor_texto or '' }}"
                           placeholder="{{ (cp.configuracion or {}).get('placeholder', '') }}"
                           {% if cp.requerido %}required{% endif %}
                           class="w-full text-xs bg-transparent border-0 border-b border-transparent hover:border-slate-200 focus:border-indigo-400 focus:ring-0 px-0 py-0.5" />
                  {% elif cp.tipo == 'numero' %}
                    <input type="number"
                           name="valor_campo"
                           value="{{ cp.valor_numero if cp.valor_numero is not none else '' }}"
                           {% if (cp.configuracion or {}).get('min') is not none %}min="{{ (cp.configuracion or {}).get('min') }}"{% endif %}
                           {% if (cp.configuracion or {}).get('max') is not none %}max="{{ (cp.configuracion or {}).get('max') }}"{% endif %}
                           step="{{ (cp.configuracion or {}).get('decimales', 1) }}"
                           {% if cp.requerido %}required{% endif %}
                           class="w-full text-xs bg-transparent border-0 border-b border-transparent hover:border-slate-200 focus:border-indigo-400 focus:ring-0 px-0 py-0.5" />
                  {% elif cp.tipo == 'dropdown' %}
                    <select name="valor_campo"
                            class="w-full text-xs bg-transparent border-0 border-b border-transparent hover:border-slate-200 focus:border-indigo-400 focus:ring-0 px-0 py-0.5">
                      <option value="">— Seleccionar —</option>
                      {% for opcion in (cp.configuracion or {}).get('opciones', []) %}
                        <option value="{{ opcion }}" {% if cp.valor_texto == opcion %}selected{% endif %}>{{ opcion }}</option>
                      {% endfor %}
                    </select>
                  {% elif cp.tipo == 'checkbox' %}
                    <label class="inline-flex items-center gap-1.5 cursor-pointer">
                      <input type="checkbox" name="valor_campo" value="true"
                             {% if cp.valor_booleano %}checked{% endif %}
                             class="h-3.5 w-3.5 text-indigo-600 focus:ring-indigo-500 border-slate-300 rounded" />
                      <span class="text-xs text-slate-600">Sí</span>
                    </label>
                  {% elif cp.tipo == 'fecha' %}
                    <input type="date"
                           name="valor_campo"
                           value="{{ cp.valor_fecha[:10] if cp.valor_fecha else '' }}"
                           {% if cp.requerido %}required{% endif %}
                           class="w-full text-xs bg-transparent border-0 border-b border-transparent hover:border-slate-200 focus:border-indigo-400 focus:ring-0 px-0 py-0.5" />
                  {% endif %}
                </form>
              </div>
            {% endfor %}
          </div>
        </div>
        {% endif %}

        <!-- Cambio de estado rápido -->
        <div class="pt-3 border-t border-slate-100">
          <h4 class="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-2">Cambiar estado</h4>
          <div class="flex flex-wrap gap-1.5">
            {% for e in estados %}
              {% if e.id != ticket.estado_id %}
                <button class="px-2.5 py-1 rounded-md text-[11px] font-medium border border-slate-200 bg-white hover:bg-slate-50 text-slate-700"
                        hx-get="/api/v1/tickets/{{ ticket.id }}/transicion-info/{{ e.id }}"
                        hx-trigger="click"
                        hx-vals='{"estado_id": "{{ e.id }}"}'
                        onclick="window.cambiarEstadoRapido && window.cambiarEstadoRapido({{ ticket.id }}, {{ e.id }})">
                  <span class="inline-block w-1.5 h-1.5 rounded-full mr-1" style="background-color: {{ e.color }}"></span>
                  {{ e.nombre }}
                </button>
              {% endif %}
            {% endfor %}
          </div>
        </div>
      </div>

      <!-- Tab: Comentarios -->
      <div class="tab-panel {% if _active != 'comentarios' %}hidden{% endif %} p-5 space-y-3" data-panel="comentarios">
        <!-- Listado -->
        <div class="space-y-2.5 max-h-72 overflow-y-auto pr-1">
          {% if comentarios %}
            {% for c in comentarios %}
              {% set nc = (c.usuario.nombre_completo if c.usuario else '') %}
              {% set ini = (nc.split(' ')[:2]|map('first')|join|upper) if nc else '?' %}
              <div class="rounded-lg border border-slate-200 bg-slate-50/40 p-3">
                <div class="flex items-center justify-between mb-1">
                  <div class="flex items-center gap-1.5">
                    <span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-semibold" title="{{ nc or 'Anónimo' }}">
                      {{ ini }}
                    </span>
                    <span class="text-xs font-medium text-slate-700">{{ nc or 'Anónimo' }}</span>
                    {% if c.es_interno %}
                      <span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 font-semibold">INTERNO</span>
                    {% endif %}
                  </div>
                  <span class="text-[10px] text-slate-400">{{ c.created_at.strftime('%Y-%m-%d %H:%M') if c.created_at else '' }}</span>
                </div>
                <p class="text-xs text-slate-700 whitespace-pre-wrap">{{ c.texto }}</p>
              </div>
            {% endfor %}
          {% else %}
            <div class="text-center text-xs text-slate-400 italic py-6">No hay comentarios aún.</div>
          {% endif %}
        </div>

        <!-- Form nuevo comentario -->
        <form hx-post="/api/v1/tickets/{{ ticket.id }}/comentarios"
              hx-target="#modal-root" hx-swap="innerHTML"
              class="pt-3 border-t border-slate-100 space-y-2">
          <input type="hidden" name="active_tab" value="comentarios">
          <textarea name="texto" rows="3" required
                    placeholder="Escribe un comentario..."
                    class="w-full text-sm border border-slate-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"></textarea>
          <div class="flex items-center justify-between">
            <label class="inline-flex items-center gap-1.5 text-[11px] text-slate-600">
              <input type="checkbox" name="es_interno" value="true"
                     class="h-3 w-3 text-indigo-600 focus:ring-indigo-500">
              Marcar como comentario interno
            </label>
            <button type="submit"
                    class="px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-600 hover:bg-indigo-700 text-white">
              Agregar comentario
            </button>
          </div>
        </form>
      </div>

      <!-- Tab: Adjuntos -->
      <div class="tab-panel {% if _active != 'adjuntos' %}hidden{% endif %} p-5 space-y-3" data-panel="adjuntos">
        <div class="space-y-1.5 max-h-72 overflow-y-auto pr-1">
          {% if adjuntos %}
            {% for a in adjuntos %}
              {% set ext = (a.nombre_original or a.filename or a.nombre or '').split('.')[-1].lower() if (a.nombre_original or a.filename or a.nombre) else '' %}
              {% set es_imagen = ext in ['png','jpg','jpeg','gif','webp','bmp','svg'] %}
              <div class="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50/40 p-2.5">
                <div class="flex items-center gap-2 min-w-0">
                  {% if es_imagen %}
                    <a href="/api/v1/adjuntos/{{ a.id }}/descargar" target="_blank" title="Vista previa">
                      <img src="/api/v1/adjuntos/{{ a.id }}/descargar"
                           alt="{{ a.nombre_original or a.filename or a.nombre }}"
                           class="w-10 h-10 object-cover rounded border border-slate-200 hover:ring-2 hover:ring-indigo-400 transition-shadow" />
                    </a>
                  {% else %}
                    <svg class="w-4 h-4 text-slate-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path>
                    </svg>
                  {% endif %}
                  <span class="text-xs text-slate-700 truncate">{{ a.nombre_original or a.filename or a.nombre }}</span>
                </div>
                <div class="flex items-center gap-2 flex-shrink-0">
                  <span class="text-[10px] text-slate-400">{{ a.tamano_legible }}</span>
                  <a href="/api/v1/adjuntos/{{ a.id }}/descargar"
                     class="text-[11px] text-indigo-600 hover:text-indigo-800 font-medium">Descargar</a>
                </div>
              </div>
            {% endfor %}
          {% else %}
            <div class="text-center text-xs text-slate-400 italic py-6">No hay archivos adjuntos.</div>
          {% endif %}
        </div>

        <form hx-post="/api/v1/tickets/{{ ticket.id }}/adjuntos"
              hx-target="#modal-root" hx-swap="innerHTML"
              hx-encoding="multipart/form-data"
              class="pt-3 border-t border-slate-100 space-y-2">
          <input type="hidden" name="active_tab" value="adjuntos">
          <label for="adjunto-file-{{ ticket.id }}"
                 class="flex flex-col items-center justify-center w-full h-24 border-2 border-dashed border-slate-300 rounded-lg cursor-pointer hover:border-indigo-400 hover:bg-indigo-50/30 transition-colors">
            <svg class="w-6 h-6 text-slate-400 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path>
            </svg>
            <span class="text-xs text-slate-500">Click para seleccionar archivo o arrastra aquí</span>
            <input id="adjunto-file-{{ ticket.id }}" name="archivo" type="file" class="hidden" required>
          </label>
          <div class="flex justify-end">
            <button type="submit"
                    class="px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-600 hover:bg-indigo-700 text-white">
              Subir archivo
            </button>
          </div>
        </form>
      </div>

      <!-- Tab: Checklist -->
      <div class="tab-panel {% if _active != 'checklist' %}hidden{% endif %} p-5 space-y-3" data-panel="checklist">
        <div class="space-y-2 max-h-72 overflow-y-auto pr-1">
          {% if checklists %}
            {% for cl in checklists %}
              <div class="rounded-lg border border-slate-200 bg-slate-50/40 p-3">
                <h5 class="text-xs font-semibold text-slate-700 mb-2">{{ cl.titulo }}</h5>
                <ul class="space-y-1.5">
                  {% for item in cl.items %}
                    <li class="flex items-center gap-2 text-xs text-slate-700">
                      <input type="checkbox"
                             class="h-3.5 w-3.5 text-indigo-600 focus:ring-indigo-500 border-slate-300 rounded"
                             {% if item.completado %}checked{% endif %}
                             hx-post="/api/v1/checklist-items/{{ item.id }}/toggle"
                             hx-trigger="change"
                             hx-target="#modal-root" hx-swap="innerHTML">
                      <span class="{% if item.completado %}line-through text-slate-400{% endif %}">
                        {{ item.texto }}
                      </span>
                    </li>
                  {% endfor %}
                </ul>
              </div>
            {% endfor %}
          {% else %}
            <div class="text-center text-xs text-slate-400 italic py-6">No hay tareas registradas.</div>
          {% endif %}
        </div>

        <form hx-post="/api/v1/tickets/{{ ticket.id }}/checklists"
              hx-target="#modal-root" hx-swap="innerHTML"
              class="pt-3 border-t border-slate-100 space-y-2">
          <input type="hidden" name="active_tab" value="checklist">
          <input type="text" name="titulo" required
                 placeholder="Título del nuevo checklist..."
                 class="w-full text-sm border border-slate-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500">
          <div class="flex justify-end">
            <button type="submit"
                    class="px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-600 hover:bg-indigo-700 text-white">
              Agregar checklist
            </button>
          </div>
        </form>
      </div>

      <!-- Tab: Trazabilidad -->
      <div class="tab-panel {% if _active != 'trazabilidad' %}hidden{% endif %} p-5 space-y-3" data-panel="trazabilidad">
        <div class="flex items-center justify-between mb-1">
          <h4 class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Historial de cambios</h4>
          <span class="text-[10px] text-slate-400">Total: {{ auditorias|length }} evento(s)</span>
        </div>
        <div class="space-y-2 max-h-[60vh] overflow-y-auto pr-1">
          {% if auditorias %}
            <ol class="relative border-l-2 border-slate-200 ml-1 space-y-3">
              {% for a in auditorias %}
                {% set nc = (a.usuario.nombre_completo if a.usuario else 'Sistema') %}
                {% set ini = (nc.split(' ')[:2]|map('first')|join|upper) if nc and nc != 'Sistema' else 'SY' %}
                {% set accion_legible = {
                    'CAMBIO_ESTADO': 'Cambió el estado',
                    'TICKET_CREADO': 'Creó el ticket',
                    'ASIGNACION': 'Reasignó el ticket',
                    'COMENTARIO_CREADO': 'Comentario creado',
                    'COMENTARIO_ELIMINADO': 'Comentario eliminado',
                    'CHECKLIST_CREADA': 'Checklist creado',
                    'CHECKLIST_ELIMINADA': 'Checklist eliminado',
                    'CHECKLIST_ITEM_TOGGLE': 'Actualizó checklist',
                    'ADJUNTO_SUBIDO': 'Subió adjunto',
                    'ADJUNTO_ELIMINADO': 'Eliminó adjunto',
                    'ETIQUETA_ASIGNADA': 'Etiqueta asignada',
                    'ETIQUETA_REMOVIDA': 'Etiqueta removida',
                    'TICKET_DUPLICADO': 'Ticket duplicado',
                  }.get(a.accion|upper, a.accion) %}
                <li class="ml-4 relative">
                  <span class="absolute -left-[1.45rem] top-0.5 w-5 h-5 rounded-full flex items-center justify-center
                               {% if a.accion|upper == 'CAMBIO_ESTADO' %}bg-indigo-100 text-indigo-700
                               {% elif a.accion|upper == 'TICKET_CREADO' %}bg-emerald-100 text-emerald-700
                               {% elif a.accion|upper == 'COMENTARIO_CREADO' %}bg-sky-100 text-sky-700
                               {% elif a.accion|upper == 'ADJUNTO_SUBIDO' %}bg-amber-100 text-amber-700
                               {% elif a.accion|upper == 'CHECKLIST_CREADA' or a.accion|upper == 'CHECKLIST_ITEM_TOGGLE' %}bg-violet-100 text-violet-700
                               {% else %}bg-slate-100 text-slate-600{% endif %}">
                    <span class="text-[8px] font-bold">{{ ini[:2] }}</span>
                  </span>
                  <div class="rounded-lg border border-slate-200 bg-white p-2.5">
                    <div class="flex items-center justify-between gap-2 mb-1">
                      <div class="flex items-center gap-1.5 min-w-0">
                        <span class="text-xs font-semibold text-slate-700 truncate">{{ nc }}</span>
                        <span class="text-xs text-slate-500">·</span>
                        <span class="text-xs text-slate-600">{{ accion_legible }}</span>
                      </div>
                      <span class="text-[10px] text-slate-400 whitespace-nowrap"
                            title="{{ a.created_at.isoformat() if a.created_at else '' }}">
                        {{ a.created_at.strftime('%Y-%m-%d %H:%M') if a.created_at else '—' }}
                      </span>
                    </div>
                    {% if a.valor_anterior or a.valor_nuevo %}
                      <div class="text-[11px] text-slate-600 mt-1 space-y-0.5">
                        {% if a.valor_anterior %}
                          <div class="flex items-start gap-1.5">
                            <span class="text-red-600 font-mono flex-shrink-0">−</span>
                            <span class="font-mono break-all">{{ a.valor_anterior | tojson if a.valor_anterior is mapping else a.valor_anterior }}</span>
                          </div>
                        {% endif %}
                        {% if a.valor_nuevo %}
                          <div class="flex items-start gap-1.5">
                            <span class="text-emerald-600 font-mono flex-shrink-0">+</span>
                            <span class="font-mono break-all">{{ a.valor_nuevo | tojson if a.valor_nuevo is mapping else a.valor_nuevo }}</span>
                          </div>
                        {% endif %}
                      </div>
                    {% endif %}
                    {% if a.comentario %}
                      <div class="mt-1.5 pt-1.5 border-t border-slate-100">
                        <p class="text-[11px] italic text-slate-500">"{{ a.comentario }}"</p>
                      </div>
                    {% endif %}
                  </div>
                </li>
              {% endfor %}
            </ol>
          {% else %}
            <div class="text-center text-xs text-slate-400 italic py-6">No hay cambios registrados para este ticket.</div>
          {% endif %}
        </div>
      </div>

    </div>

    <!-- ============== FOOTER ============== -->
    <div class="px-5 py-3 bg-slate-50 border-t border-slate-200 flex items-center justify-between flex-shrink-0">
      <div class="text-[11px] text-slate-500 flex items-center gap-1.5 min-w-0">
        <span class="font-mono">#{{ ticket.id }}</span>
        <span>·</span>
        <span class="truncate" title="Última modificación">{{ ultima_modificacion|default('Actualizado ' + (ticket.updated_at.strftime('%Y-%m-%d %H:%M') if ticket.updated_at else '—')) }}</span>
      </div>
      <div class="flex items-center gap-2">
        <button type="button"
                data-action="duplicar-ticket" data-ticket-id="{{ ticket.id }}"
                class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100 inline-flex items-center gap-1">
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
          Duplicar
        </button>
        <button data-close-modal
                class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">
          Cerrar
        </button>
      </div>
    </div>
  </div>
</div>
""")


# ---------------------------------------------------------------------------
#  API pública
# ---------------------------------------------------------------------------

def render_detalle_modal(
    ticket,
    estados: Iterable,
    comentarios: Iterable,
    adjuntos: Iterable,
    checklists: Iterable,
    auditorias: Iterable = (),
    usuario=None,
    ultima_modificacion: str = "",
    active_tab: str = "detalles",
    usuarios: Iterable = (),
    etiquetas_disponibles: Iterable = (),
    campos_personalizados: Iterable = (),
) -> str:
    """Renderiza el modal completo de detalle de un ticket.

    Parameters
    ----------
    ticket : Ticket
        Instancia del modelo Ticket (con relaciones ``estado``, ``creador``,
        ``asignado``, ``etiquetas`` ya cargadas).
    estados : Iterable[Estado]
        Lista de todos los estados disponibles (para los botones de
        transición rápida).
    comentarios : Iterable[Comentario]
        Comentarios del ticket (orden ascendente).
    adjuntos : Iterable[Adjunto]
        Archivos adjuntos del ticket.
    checklists : Iterable[Checklist]
        Checklists con sus respectivos ``items``.
    auditorias : Iterable[Auditoria]
        Bitácora de auditoría del ticket (orden descendente por fecha).
    usuario : Usuario | None
        Usuario actual (para mostrarlo en el header si se requiere).
    ultima_modificacion : str
        Cadena amigable describiendo el último cambio (ej: "Juan cambió
        el estado a Cerrado, hace 5 min"). Si está vacía, se calcula
        automáticamente a partir de ``ticket.updated_at``.
    active_tab : str
        Pestaña que debe mostrarse activa al renderizar. Una de
        ``{"detalles", "comentarios", "adjuntos", "checklist",
        "trazabilidad"}``. Por defecto ``"detalles"``.
    usuarios : Iterable[Usuario]
        Lista de usuarios disponibles para el select de "Asignado".
    etiquetas_disponibles : Iterable[Etiqueta]
        Lista de todas las etiquetas del sistema (para el gestor de etiquetas).

    Returns
    -------
    str
        HTML listo para inyectar vía HTMX.
    """
    if not ultima_modificacion:
        # Fallback: usar updated_at del ticket
        if ticket.updated_at:
            ultima_modificacion = f"Actualizado {ticket.updated_at.strftime('%Y-%m-%d %H:%M')}"
        else:
            ultima_modificacion = "—"
    # Normalizar active_tab a un valor seguro
    _tabs_validos = {"detalles", "comentarios", "adjuntos", "checklist", "trazabilidad"}
    if active_tab not in _tabs_validos:
        active_tab = "detalles"
    return DETALLE_TEMPLATE.render(
        ticket=ticket,
        estados=list(estados),
        comentarios=list(comentarios),
        adjuntos=list(adjuntos),
        checklists=list(checklists),
        auditorias=list(auditorias),
        usuario=usuario,
        ultima_modificacion=ultima_modificacion,
        active_tab=active_tab,
        usuarios=list(usuarios),
        etiquetas_disponibles=list(etiquetas_disponibles),
        campos_personalizados=list(campos_personalizados),
    )
