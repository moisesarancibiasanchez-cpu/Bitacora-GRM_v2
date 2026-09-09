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
<div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 modal-backdrop"
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
        <h3 class="text-base font-semibold text-slate-800 leading-snug">{{ ticket.titulo }}</h3>
      </div>
      <button data-close-modal
              class="w-8 h-8 rounded-md flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100 flex-shrink-0">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
        </svg>
      </button>
    </div>

    <!-- ============== TABS ============== -->
    <div class="border-b border-slate-200 px-5 flex items-center gap-1 flex-shrink-0" role="tablist">
      <button class="tab-btn px-3 py-2.5 text-xs font-medium border-b-2 border-indigo-600 text-indigo-700"
              data-tab="detalles">Detalles</button>
      <button class="tab-btn px-3 py-2.5 text-xs font-medium border-b-2 border-transparent text-slate-500 hover:text-slate-700"
              data-tab="comentarios">
        Comentarios
        <span class="ml-1 px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10px]">{{ comentarios|length }}</span>
      </button>
      <button class="tab-btn px-3 py-2.5 text-xs font-medium border-b-2 border-transparent text-slate-500 hover:text-slate-700"
              data-tab="adjuntos">
        Adjuntos
        <span class="ml-1 px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10px]">{{ adjuntos|length }}</span>
      </button>
      <button class="tab-btn px-3 py-2.5 text-xs font-medium border-b-2 border-transparent text-slate-500 hover:text-slate-700"
              data-tab="checklist">
        Checklist
        <span class="ml-1 px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10px]">{{ checklists|length }}</span>
      </button>
    </div>

    <!-- ============== BODY ============== -->
    <div class="flex-1 overflow-y-auto">

      <!-- Tab: Detalles -->
      <div class="tab-panel p-5 space-y-4" data-panel="detalles">
        <div>
          <h4 class="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1">Descripción</h4>
          <p class="text-sm text-slate-700 whitespace-pre-wrap">{{ ticket.descripcion or '— Sin descripción —' }}</p>
        </div>

        <div class="grid grid-cols-2 gap-3 text-xs">
          <div>
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Tipo</span>
            <span class="text-slate-700">{{ ticket.tipo.value }}</span>
          </div>
          <div>
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Prioridad</span>
            <span class="text-slate-700">{{ ticket.prioridad.value }}</span>
          </div>
          <div>
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Creador</span>
            <span class="text-slate-700">{{ ticket.creador.nombre_completo if ticket.creador else '—' }}</span>
          </div>
          <div>
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Asignado</span>
            <span class="text-slate-700">{{ ticket.asignado.nombre_completo if ticket.asignado else '— sin asignar —' }}</span>
          </div>
          <div>
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">SLA</span>
            <span class="text-slate-700">
              {% if ticket.fecha_vencimiento_sla %}
                {{ ticket.fecha_vencimiento_sla.strftime('%Y-%m-%d %H:%M') }}
              {% else %}—{% endif %}
            </span>
          </div>
          <div>
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Creado</span>
            <span class="text-slate-700">{{ ticket.created_at.strftime('%Y-%m-%d %H:%M') if ticket.created_at else '—' }}</span>
          </div>
        </div>

        {% if ticket.etiquetas %}
        <div>
          <h4 class="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1.5">Etiquetas</h4>
          <div class="flex flex-wrap gap-1.5">
            {% for et in ticket.etiquetas %}
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium"
                    style="background-color: {{ et.color }}20; color: {{ et.color }};">
                <span class="inline-block w-1.5 h-1.5 rounded-full" style="background-color: {{ et.color }}"></span>
                {{ et.nombre }}
              </span>
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
      <div class="tab-panel hidden p-5 space-y-3" data-panel="comentarios">
        <!-- Listado -->
        <div class="space-y-2.5 max-h-72 overflow-y-auto pr-1">
          {% if comentarios %}
            {% for c in comentarios %}
              <div class="rounded-lg border border-slate-200 bg-slate-50/40 p-3">
                <div class="flex items-center justify-between mb-1">
                  <div class="flex items-center gap-1.5">
                    <span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-semibold">
                      {{ c.usuario.nombre_completo[:1]|upper if c.usuario else '?' }}
                    </span>
                    <span class="text-xs font-medium text-slate-700">{{ c.usuario.nombre_completo if c.usuario else 'Anónimo' }}</span>
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
      <div class="tab-panel hidden p-5 space-y-3" data-panel="adjuntos">
        <div class="space-y-1.5 max-h-72 overflow-y-auto pr-1">
          {% if adjuntos %}
            {% for a in adjuntos %}
              <div class="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50/40 p-2.5">
                <div class="flex items-center gap-2 min-w-0">
                  <svg class="w-4 h-4 text-slate-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path>
                  </svg>
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
      <div class="tab-panel hidden p-5 space-y-3" data-panel="checklist">
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

    </div>

    <!-- ============== FOOTER ============== -->
    <div class="px-5 py-3 bg-slate-50 border-t border-slate-200 flex items-center justify-between flex-shrink-0">
      <span class="text-[11px] text-slate-500">
        Ticket #{{ ticket.id }} · Actualizado {{ ticket.updated_at.strftime('%Y-%m-%d %H:%M') if ticket.updated_at else '—' }}
      </span>
      <button data-close-modal
              class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">
        Cerrar
      </button>
    </div>
  </div>
</div>

<script>
  // === Tabs ===
  (function () {
    const root = document.querySelector('[data-modal="detalle-ticket"]');
    if (!root) return;
    const btns = root.querySelectorAll('.tab-btn');
    const panels = root.querySelectorAll('.tab-panel');
    btns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.tab;
        btns.forEach((b) => {
          if (b === btn) {
            b.classList.add('border-indigo-600', 'text-indigo-700');
            b.classList.remove('border-transparent', 'text-slate-500');
          } else {
            b.classList.remove('border-indigo-600', 'text-indigo-700');
            b.classList.add('border-transparent', 'text-slate-500');
          }
        });
        panels.forEach((p) => {
          if (p.dataset.panel === target) p.classList.remove('hidden');
          else p.classList.add('hidden');
        });
      });
    });

    // Cambio de estado rápido: reutiliza el handler de kanban.js si existe
    window.cambiarEstadoRapido = function (ticketId, estadoId) {
      const evt = new CustomEvent('quick-state-change', { detail: { ticketId, estadoId } });
      document.dispatchEvent(evt);
    };
  })();
</script>
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
    usuario=None,
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
    usuario : Usuario | None
        Usuario actual (para mostrarlo en el header si se requiere).

    Returns
    -------
    str
        HTML listo para inyectar vía HTMX.
    """
    return DETALLE_TEMPLATE.render(
        ticket=ticket,
        estados=list(estados),
        comentarios=list(comentarios),
        adjuntos=list(adjuntos),
        checklists=list(checklists),
        usuario=usuario,
    )
