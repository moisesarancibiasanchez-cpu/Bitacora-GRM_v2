"""
Fragmento Jinja2: tarjeta individual del Kanban.
Se devuelve al frontend cuando hay éxito (HTMX hace outerHTML swap).
"""
from jinja2 import Environment

# Creamos un Environment propio con los filtros personalizados
# (incluye ``truncate_text`` para limitar la descripción de la tarjeta).
from app.core.jinja_filters import ALL_FILTERS  # noqa: E402

_ENV = Environment(autoescape=True)
for _fname, _ffunc in ALL_FILTERS.items():
    _ENV.filters[_fname] = _ffunc


CARD_TEMPLATE = _ENV.from_string("""
<div id="ticket-{{ ticket.id }}"
     class="kanban-card group cursor-pointer rounded-lg bg-white shadow-sm border border-slate-200 p-3 mb-2 hover:shadow-md hover:border-indigo-300 transition-all duration-150"
     data-ticket-id="{{ ticket.id }}"
     data-prioridad="{{ ticket.prioridad.value }}"
     data-estado="{{ ticket.estado.nombre }}"
     title="Doble clic o click para ver detalle · Arrastrar para mover">
  <div class="flex items-start justify-between gap-2 mb-1.5">
    <span class="font-mono text-[10px] tracking-wide text-slate-500 uppercase">{{ ticket.codigo }}</span>
    <div class="flex items-center gap-1.5">
      <span class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold
                   {% if ticket.prioridad.value == 'critica' %}bg-red-100 text-red-700
                   {% elif ticket.prioridad.value == 'alta' %}bg-orange-100 text-orange-700
                   {% elif ticket.prioridad.value == 'media' %}bg-yellow-100 text-yellow-700
                   {% else %}bg-slate-100 text-slate-600{% endif %}">
        {{ ticket.prioridad.value|upper }}
      </span>
      <button type="button"
              class="open-detail-btn w-5 h-5 rounded text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
              hx-get="/api/v1/tickets/{{ ticket.id }}/detalle-html"
              hx-target="#modal-root" hx-swap="innerHTML"
              title="Ver detalle">
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path>
        </svg>
      </button>
    </div>
  </div>
  <h4 class="text-sm font-medium text-slate-800 leading-snug mb-1.5 line-clamp-2">{{ ticket.titulo }}</h4>
  <p class="text-xs text-slate-500 line-clamp-2 mb-2 break-words" title="{{ ticket.descripcion or '' }}">{{ ticket.descripcion | truncate_text(70) }}</p>
  <div class="flex items-center justify-between text-[11px] text-slate-500">
    <div class="flex items-center gap-1">
      {% if ticket.asignado %}
        <span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-semibold">
          {{ ticket.asignado.nombre_completo[:1]|upper }}
        </span>
        <span>{{ ticket.asignado.nombre_completo.split(' ')[0] }}</span>
      {% else %}
        <span class="italic opacity-60">sin asignar</span>
      {% endif %}
    </div>
    <div class="flex items-center gap-1">
      {% if ticket.sla_cumplido == 0 %}
        <span class="inline-block w-1.5 h-1.5 rounded-full bg-red-500" title="SLA vencido"></span>
        <span class="text-red-600">SLA</span>
      {% elif ticket.sla_cumplido == -1 and ticket.fecha_vencimiento_sla %}
        <span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-500" title="SLA próximo"></span>
        <span class="text-amber-600">SLA</span>
      {% elif ticket.sla_cumplido == 1 %}
        <span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" title="SLA OK"></span>
        <span class="text-emerald-600">SLA</span>
      {% endif %}
    </div>
  </div>
</div>
""")


def render_tarjeta(ticket) -> str:
    """Renderiza la tarjeta de un ticket a HTML."""
    return CARD_TEMPLATE.render(ticket=ticket)
