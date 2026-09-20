"""Verifica el orden y tab por defecto del editor markdown de Bitácora GRM.

Comprueba que:
  1. El botón "Vista previa" aparece ANTES de "Escribir" en el HTML de tabs.
  2. El tab inicial es "preview", no "write".
"""
import re
import pathlib

JS = pathlib.Path(__file__).parent / "app" / "static" / "js" / "htmx-events.js"
src = JS.read_text(encoding="utf-8")


def test_vista_previa_es_primer_tab():
    """El botón 'Vista previa' debe aparecer antes que 'Escribir' en el HTML."""
    # Busca las dos líneas de los botones en el orden correcto (con cualquier
    # cantidad de separadores JS entre ellas: '+', whitespace, etc.).
    idx_preview = src.find('data-md-tab="preview"')
    idx_write = src.find('data-md-tab="write"')
    assert idx_preview != -1, "No se encontró data-md-tab='preview'"
    assert idx_write != -1, "No se encontró data-md-tab='write'"
    assert idx_preview < idx_write, (
        f"'preview' (idx={idx_preview}) debe aparecer ANTES que 'write' "
        f"(idx={idx_write})."
    )
    # También verificamos que la etiqueta textual acompaña el orden
    idx_preview_label = src.find('>Vista previa<', idx_preview)
    idx_write_label = src.find('>Escribir<', idx_preview)
    assert idx_preview_label != -1 and idx_write_label != -1
    assert idx_preview_label < idx_write_label, (
        "Etiqueta 'Vista previa' debe aparecer antes de 'Escribir'."
    )
    print("PASS: Vista previa es el primer tab (orden invertido correctamente)")


def test_default_tab_es_preview():
    """setActive debe llamarse con 'preview' como tab inicial."""
    # Busca setActive(...) y verifica que el argumento es 'preview'
    m = re.search(r"setActive\(\s*['\"](\w+)['\"]\s*\)\s*;\s*\n\s*\}\)\;\s*\n\s*\}", src)
    assert m, "No se encontró la invocación setActive(...) al final del loop."
    active = m.group(1)
    assert active == "preview", f"Tab inicial esperado 'preview', got {active!r}"
    print(f"PASS: Tab inicial = {active!r} (Vista previa por defecto)")


def test_render_markdown_se_invoca_al_iniciar():
    """Cuando arrancamos en preview, renderMarkdown debe poblar el contenido."""
    # renderMarkdown debe invocarse con ta.value dentro de setActive('preview')
    # Verifica que existe la rama tab === 'preview' con preview.innerHTML = renderMarkdown(...)
    m = re.search(
        r"if\s*\(\s*tab\s*===\s*['\"]preview['\"]\s*\)\s*\{[^}]*preview\.innerHTML\s*=\s*renderMarkdown\(ta\.value",
        src,
        flags=re.DOTALL,
    )
    assert m, "La rama preview debe llamar renderMarkdown(ta.value) al activarse."
    print("PASS: renderMarkdown se invoca al activar 'preview' (carga inicial correcta)")


def test_toggle_escribir_aun_funciona():
    """El click handler sigue aceptando data-md-tab='write' para volver al editor."""
    m = re.search(r"setActive\(b\.getAttribute\(['\"]data-md-tab['\"]\)\)", src)
    assert m, "El handler de click debe seguir invocando setActive(tabName) genérico."
    print("PASS: Toggle entre tabs (write ↔ preview) sigue funcionando")


if __name__ == "__main__":
    test_vista_previa_es_primer_tab()
    test_default_tab_es_preview()
    test_render_markdown_se_invoca_al_iniciar()
    test_toggle_escribir_aun_funciona()
    print("\n=== ALL TESTS PASSED ===")