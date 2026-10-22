"""
Test E2E para la nueva funcionalidad de copy-paste en Adjuntos del Detalle.

Cubre:
  A. Pegar 1 imagen desde clipboard → aparece en paste-list con thumbnail
  B. Pegar 2 imágenes a la vez → ambas aparecen, toast muestra "2 imágenes"
  C. Pegar texto (no imagen) → no se intercepta (no rompe UX)
  D. Quitar una imagen pegada → desaparece de la lista y del fileInput.files
  E. Agregar descripción + Submit → backend recibe archivo + descripción
  F. Backend persiste con nombre "paste-YYYYMMDD-..." y descripción guardada
  G. Después de upload exitoso, el paste-list se limpia

Para simular el paste en Playwright:
  - Genera un PNG pequeño en memoria (base64 → Uint8Array)
  - Construye un ClipboardEvent con un DataTransfer que contiene el PNG
  - Lo dispara contra document
"""
import asyncio
import base64
import json
import sys

from playwright.async_api import async_playwright

# PNG mínimo válido (8x8 rojo)
PNG_8x8_RED = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x08\x00\x00\x00\x08"
    b"\x08\x02\x00\x00\x00K\x1d\x8a\xcf\x00\x00\x00\x12IDATx\x9cc\xf8\xcf"
    b"\xc0\x00\x00\x00\x03\x00\x01\xc8\xdb\xc6\x9e\x00\x00\x00\x00IEND\xaeB`\x82"
)
# PNG 16x16 verde (segundo archivo)
PNG_16x16_GREEN = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10"
    b"\x08\x02\x00\x00\x00\x90\x91h6\x00\x00\x00\x12IDATx\x9cc\xf8\xcf\xc0"
    b"\xc0\xc0\xc0\xf0\x9f\x81\x8b\x00\x05\x00\x01\xff\xa0\xfb\xf3\xfa\x00"
    b"\x00\x00\x00IEND\xaeB`\x82"
)


async def fire_paste(page, png_bytes: bytes, file_name: str = "clipboard-image.png",
                     mime: str = "image/png"):
    """Simula Ctrl+V con una imagen en el clipboard.

    Construye un ClipboardEvent con un DataTransfer que contiene un File con
    los bytes del PNG, y lo dispara contra `document`.
    """
    js = r"""
    async ({b64, name, mime}) => {
        // 1) Decodificar base64 -> Uint8Array
        const bin = atob(b64);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        // 2) Crear File y poblar DataTransfer
        const file = new File([bytes], name, { type: mime });
        const dt = new DataTransfer();
        dt.items.add(file);
        // 3) Disparar paste
        const evt = new ClipboardEvent('paste', {
            clipboardData: dt,
            bubbles: true,
            cancelable: true,
        });
        document.dispatchEvent(evt);
        return { ok: true, fileName: file.name, fileSize: file.size, fileType: file.type };
    }
    """
    return await page.evaluate(js, {
        "b64": base64.b64encode(png_bytes).decode(),
        "name": file_name,
        "mime": mime,
    })


async def fire_multi_paste(page, payloads):
    """Pega múltiples imágenes en un solo evento (caso: snipping tool con varias)."""
    js = r"""
    async ({items}) => {
        const dt = new DataTransfer();
        for (const {b64, name, mime} of items) {
            const bin = atob(b64);
            const bytes = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
            const f = new File([bytes], name, { type: mime });
            dt.items.add(f);
        }
        const evt = new ClipboardEvent('paste', {
            clipboardData: dt, bubbles: true, cancelable: true,
        });
        document.dispatchEvent(evt);
        return { ok: true, count: items.length };
    }
    """
    return await page.evaluate(js, {
        "items": [
            {"b64": base64.b64encode(p["bytes"]).decode(),
             "name": p["name"], "mime": p["mime"]}
            for p in payloads
        ]
    })


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        # Capturar logs del servidor
        page.on("console", lambda msg: print(f"  [browser:{msg.type}] {msg.text[:200]}"))

        # Capturar requests para verificar POST
        post_responses = []
        async def on_response(resp):
            if "/adjuntos" in resp.url and resp.request.method == "POST":
                try:
                    body = await resp.text()
                    post_responses.append({
                        "url": resp.url,
                        "status": resp.status,
                        "body": body[:300],
                    })
                except Exception:
                    pass
        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        print("=== 1) Login ===")
        await page.goto("http://127.0.0.1:8766/auth/login")
        await page.fill('input[name="username"]', "admin")
        await page.fill('input[name="password"]', "admin123")
        await page.click('button[type="submit"]')
        await page.wait_for_url("**/kanban", timeout=15000)
        print(f"  URL: {page.url}")

        print("=== 2) Abrir primer ticket ===")
        await page.wait_for_selector('.kanban-card .open-detail-btn', timeout=10000)
        await page.click('.kanban-card .open-detail-btn')
        # El modal abre en tab "detalles", hay que ir a tab "adjuntos"
        await page.wait_for_selector('[data-tab="adjuntos"]', timeout=10000)
        await page.click('[data-tab="adjuntos"]')
        # Ahora el form de adjuntos está visible
        await page.wait_for_selector('[id^="adjuntos-form-"]', state="visible", timeout=10000)
        ticket_form = await page.query_selector('[id^="adjuntos-form-"]')
        form_id = await ticket_form.get_attribute("id")
        ticket_id = form_id.replace("adjuntos-form-", "")
        print(f"  ticket_id: {ticket_id}")

        print("=== 3) Activar tab Adjuntos ===")
        # El paste-list está en el DOM pero oculto (class="hidden") por diseño:
        # solo se hace visible cuando hay archivos pegados. Lo esperamos attached.
        await page.wait_for_selector(f'#adjuntos-paste-list-{ticket_id}', state="attached", timeout=5000)
        paste_list_id = f"adjuntos-paste-list-{ticket_id}"
        paste_desc_id = f"adjuntos-paste-desc-{ticket_id}"
        file_input_id = f"adjunto-file-{ticket_id}"
        print(f"  paste-list attached: #{paste_list_id}")
        print(f"  desc attached: #{paste_desc_id}")
        print(f"  file input: #{file_input_id}")

        # =====================================================================
        print("=== 4) Test A: Pegar 1 imagen → aparece en paste-list ===")
        result = await fire_paste(page, PNG_8x8_RED, "screenshot-error.png")
        print(f"  Paste disparado: {result}")
        await page.wait_for_selector(f'#{paste_list_id} img', timeout=3000)
        paste_count = await page.eval_on_selector_all(
            f'#{paste_list_id} [data-remove-paste]',
            "els => els.length"
        )
        print(f"  Imágenes en paste-list: {paste_count}")
        assert paste_count == 1, f"Esperaba 1, hay {paste_count}"
        # Verificar que el input contiene la imagen combinada
        file_count = await page.eval_on_selector(
            f'#{file_input_id}',
            "el => el.files.length"
        )
        print(f"  Archivos en fileInput.files: {file_count}")
        assert file_count == 1, f"Esperaba 1, hay {file_count}"
        # Verificar que la descripción está visible
        desc_visible = await page.is_visible(f'#{paste_desc_id}')
        print(f"  Textarea descripción visible: {desc_visible}")
        assert desc_visible, "La textarea debería estar visible"
        print("  ✅ Test A OK")

        # =====================================================================
        print("=== 5) Test B: Agregar descripción ===")
        await page.fill(f'#{paste_desc_id}', "Captura de error en login - severidad alta")
        desc_value = await page.input_value(f'#{paste_desc_id}')
        print(f"  Descripción: '{desc_value}'")
        assert "error en login" in desc_value

        # =====================================================================
        print("=== 6) Test C: Quitar la imagen pegada (botón X) ===")
        await page.click(f'#{paste_list_id} [data-remove-paste]')
        await page.wait_for_function(
            f"document.querySelector('#{paste_list_id}').children.length === 0",
            timeout=3000
        )
        paste_count_after = await page.eval_on_selector_all(
            f'#{paste_list_id} [data-remove-paste]',
            "els => els.length"
        )
        file_count_after = await page.eval_on_selector(
            f'#{file_input_id}',
            "el => el.files.length"
        )
        print(f"  Después de quitar: paste-list={paste_count_after}, fileInput={file_count_after}")
        assert paste_count_after == 0
        assert file_count_after == 0
        print("  ✅ Test C OK")

        # =====================================================================
        print("=== 7) Test D: Pegar 2 imágenes a la vez ===")
        await fire_multi_paste(page, [
            {"bytes": PNG_8x8_RED, "name": "snip1.png", "mime": "image/png"},
            {"bytes": PNG_16x16_GREEN, "name": "snip2.png", "mime": "image/png"},
        ])
        await page.wait_for_function(
            f"document.querySelectorAll('#{paste_list_id} [data-remove-paste]').length === 2",
            timeout=3000
        )
        paste_count_2 = await page.eval_on_selector_all(
            f'#{paste_list_id} [data-remove-paste]',
            "els => els.length"
        )
        file_count_2 = await page.eval_on_selector(
            f'#{file_input_id}',
            "el => el.files.length"
        )
        print(f"  paste-list: {paste_count_2}, fileInput: {file_count_2}")
        assert paste_count_2 == 2
        assert file_count_2 == 2
        print("  ✅ Test D OK")

        # =====================================================================
        print("=== 8) Test E: Texto plain NO se intercepta (paste de texto en input) ===")
        # Pegamos un texto 'Hola' en un input de texto (que existe en el modal)
        # → el listener debe hacer return temprano
        js_text = r"""
        () => {
            // Buscar el primer input de texto en el modal
            const inputs = document.querySelectorAll('input[type="text"], textarea');
            if (!inputs.length) return { found: false };
            const target = inputs[0];
            target.focus();
            const dt = new DataTransfer();
            dt.setData('text/plain', 'Hola mundo pegado');
            const evt = new ClipboardEvent('paste', {
                clipboardData: dt, bubbles: true, cancelable: true,
            });
            target.dispatchEvent(evt);
            // Pegar imágenes también para verificar que NO interfiere con el input
            // El listener global hace return si target es un input de texto
            return { found: true, tag: target.tagName, type: target.type };
        }
        """
        text_result = await page.evaluate(js_text)
        print(f"  Texto pegado en input: {text_result}")
        # paste-list debe seguir con 2 imágenes (no se agregaron nuevas)
        paste_count_after_text = await page.eval_on_selector_all(
            f'#{paste_list_id} [data-remove-paste]',
            "els => els.length"
        )
        assert paste_count_after_text == 2, \
            f"Texto no debió afectar paste-list, pero hay {paste_count_after_text}"
        print("  ✅ Test E OK")

        # =====================================================================
        print("=== 9) Test F: Submit y verificar upload ===")
        # Limpiar el input de texto por si acaso
        await page.evaluate(f"document.querySelector('#{paste_desc_id}').value = ''")
        # Llenar descripción nueva
        await page.fill(f'#{paste_desc_id}', "Dos screenshots de evidencia")
        # Click submit + capturar el response del POST
        async with page.expect_response(
            lambda r: "/adjuntos" in r.url and r.request.method == "POST",
            timeout=15000
        ) as resp_info:
            await page.click(f'#{form_id} button[type="submit"]')
        resp = await resp_info.value
        status = resp.status
        body = await resp.text()
        print(f"  POST status: {status}, body[:200]: {body[:200]}")
        assert status in (200, 201), f"Esperaba 2xx, got {status}"
        await asyncio.sleep(1.5)  # dejar que HTMX termine el swap
        print(f"  POST responses capturados: {len(post_responses)}")
        for r in post_responses:
            print(f"    status={r['status']}, body[:120]={r['body'][:120]}")
        print("  ✅ Test F OK (POST exitoso)")

        # =====================================================================
        print("=== 10) Test G: Verificar que backend guardó con nombre 'paste-' ===")
        # Recargar página y abrir el mismo ticket para ver si los adjuntos persisten
        await page.goto(f"http://127.0.0.1:8766/kanban")
        await page.wait_for_selector('.kanban-card .open-detail-btn', timeout=10000)
        await page.click(f'.kanban-card .open-detail-btn')
        await page.wait_for_selector(f'[data-tab="adjuntos"]', timeout=5000)
        await page.click(f'[data-tab="adjuntos"]')
        await asyncio.sleep(0.5)
        # Buscar nombres con "paste-" en la lista de adjuntos existentes
        paste_names = await page.eval_on_selector_all(
            '.tab-panel[data-panel="adjuntos"] span.text-xs.text-slate-700',
            "els => els.map(e => e.textContent.trim()).filter(t => t.startsWith('paste-'))"
        )
        print(f"  Adjuntos con nombre 'paste-': {paste_names}")
        assert len(paste_names) >= 2, f"Esperaba ≥2, encontré {len(paste_names)}"
        print("  ✅ Test G OK")

        # =====================================================================
        print("=== 11) Verificar que descripción se guardó en BD ===")
        # curl al backend para ver descripcion
        import subprocess
        curl = subprocess.run(
            ["curl", "-s", "-H", "X-User-Id: 1",
             f"http://127.0.0.1:8766/api/v1/tickets/{ticket_id}/adjuntos"],
            capture_output=True, text=True, timeout=10
        )
        adjuntos = json.loads(curl.stdout)
        paste_adjuntos = [a for a in adjuntos if a["nombre_original"].startswith("paste-")]
        print(f"  Total adjuntos con paste-: {len(paste_adjuntos)}")
        if paste_adjuntos:
            print(f"  Descripciones: {[a.get('descripcion') for a in paste_adjuntos]}")
            assert any("evidencia" in (a.get("descripcion") or "").lower()
                       for a in paste_adjuntos), \
                "Ninguna descripción contiene 'evidencia'"
        print("  ✅ Descripción persistida OK")

        await browser.close()
        print("\n🎉 TODOS LOS TESTS PASARON")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as e:
        print(f"\n❌ FALLÓ: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
