"""
Fragmento Jinja2: columna del Kanban.
"""
from jinja2 import Template

COLUMN_TEMPLATE = Template("""
<div id="column-{{ estado.id }}"
     class="kanban-column flex-shrink-0 w-72 rounded-xl bg-slate-100/70 p-3 flex flex-col"
     data-estado-id="{{ estado.id }}"
     data-estado-nombre="{{ estado.nombre }}">
  <div class="flex items-center justify-between mb-3 px-1">
    <div class="flex items-center gap-2">
      <span class="inline-block w-2.5 h-2.5 rounded-full" style="background-color: {{ estado.color }}"></span>
      <h3 class="font-semibold text-sm text-slate-700 uppercase tracking-wide">{{ estado.nombre }}</h3>
    </div>
    <span class="text-xs font-mono text-slate-500 bg-white px-2 py-0.5 rounded-full border border-slate-200"
          id="count-{{ estado.id }}">{{ tickets|length }}</span>
  </div>
  <div class="kanban-list flex-1 overflow-y-auto min-h-[200px] space-y-0.5 pr-1"
       hx-target=".kanban-list"
       data-estado-id="{{ estado.id }}">
    {% for ticket in tickets %}
      {{ card_macro(ticket) }}
    {% else %}
      <div class="empty-column text-center text-xs text-slate-400 py-8 italic">
        Arrastra una tarjeta aquí
      </div>
    {% endfor %}
  </div>
</div>
""")


def render_columna(estado, tickets) -> str:
    """Renderiza la columna completa de un estado."""
    from app.templates.kanban.partials.card import render_tarjeta
    return COLUMN_TEMPLATE.render(
        estado=estado,
        tickets=tickets,
        card_macro=lambda t: render_tarjeta(t),
    )
