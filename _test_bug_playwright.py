#!/usr/bin/env python3
"""
Test E2E con Playwright que reproduce el bug original del usuario:

1. Login
2. Abre un ticket
3. Va a pestaña Referencias
4. Teclea texto en input → espera 500ms → verifica que NO se borró (era el bug)
5. Click en botón BUSCAR → verifica que aparecen resultados (era el bug)
6. Click en opción → selecciona → verifica
"""
import asyncio
import sys
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:8766"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context()
        page = await ctx.new_page()

        # Capturar requests HTMX para debug
        htmx_requests = []
        page.on("request", lambda req: htmx_requests.append((req.method, req.url)) if "/api/v1/tickets/buscar" in req.url else None)
        page.on("response", lambda res: print(f"  ← {res.status} {res.url[:90]}") if "/api/v1/tickets/buscar" in res.url else None)
        # Capturar TODAS las requests HTMX para entender qué pasa con el POST
        all_requests = []
        page.on("request", lambda req: all_requests.append((req.method, req.url, req.post_data)) if "/api/v1/tickets/" in req.url or "/api/v1/referencias" in req.url else None)
        all_responses = []
        page.on("response", lambda res: all_responses.append((res.status, res.url)) if "/api/v1/tickets/" in res.url or "/api/v1/referencias" in res.url else None)

        print("=== 1) Login ===")
        await page.goto(f"{BASE_URL}/auth/login")
        await page.fill('input[name="username"]', "admin")
        await page.fill('input[name="password"]', "admin123")
        await page.click('button[type="submit"]')
        # Esperar a que salga del login
        await page.wait_for_function(
            "() => !window.location.pathname.includes('/auth/login')",
            timeout=10000,
        )
        await asyncio.sleep(0.5)
        print(f"  URL actual: {page.url}")

        print("\n=== 2) Abrir primer ticket ===")
        # Esperar a que carguen las tarjetas (kanban-card)
        await page.wait_for_selector('.kanban-card', timeout=10000)
        # Click en la primera tarjeta (botón "ojo")
        await page.click('.kanban-card .open-detail-btn')
        # Esperar al modal
        await page.wait_for_selector('[data-modal="detalle-ticket"]', timeout=10000)
        print(f"  Modal abierto")

        print("\n=== 3) Click en pestaña Referencias ===")
        await page.click('[data-tab="referencias"]')
        await page.wait_for_selector('[id^="form-add-referencia-"]', state="attached", timeout=5000)
        # Pequeño sleep para que se ejecuten los scripts inline
        await asyncio.sleep(0.5)
        print(f"  Tab Referencias activa")

        # Encontrar el ticket_id del form
        ticket_id = await page.evaluate("""() => {
            const f = document.querySelector('[id^="form-add-referencia-"]');
            return f ? f.id.replace('form-add-referencia-', '') : null;
        }""")
        print(f"  ticket_id: {ticket_id}")

        input_sel = f"#ref-search-input-{ticket_id}"
        result_sel = f"#ref-search-result-{ticket_id}"
        btn_sel = f"#ref-search-btn-{ticket_id}"
        form_sel = f"#form-add-referencia-{ticket_id}"

        print("\n=== 4) Test bug 1: Teclear en input y verificar que NO se borra ===")
        # Limpiar input por si acaso
        await page.fill(input_sel, "")
        # Teclear texto
        await page.type(input_sel, "REF-TEST", delay=50)
        # Verificar inmediatamente
        val_inmediato = await page.input_value(input_sel)
        print(f"  Inmediato después de teclear: '{val_inmediato}'")
        # Esperar 600ms (más que el delay:250ms del HTMX)
        await asyncio.sleep(0.6)
        # Verificar de nuevo
        val_despues = await page.input_value(input_sel)
        print(f"  Después de 600ms (HTMX ya disparó): '{val_despues}'")
        if val_despues == "":
            print("  ❌ BUG REPRODUCIDO: el texto se borró después del keyup")
        elif val_despues == "REF-TEST":
            print("  ✅ FIX OK: el texto se mantuvo tras el keyup")
        else:
            print(f"  ⚠️ Texto inesperado: '{val_despues}'")

        print("\n=== 5) Test bug 2: Click BUSCAR y verificar que se ejecuta ===")
        # Resetear y teclear de nuevo
        await page.fill(input_sel, "")
        await page.type(input_sel, "REF-TEST", delay=50)
        await asyncio.sleep(0.3)
        # Verificar
        val_pre_click = await page.input_value(input_sel)
        print(f"  Antes del click en BUSCAR: '{val_pre_click}'")
        # Capturar responses
        requests_before = len(htmx_requests)
        # Click en BUSCAR
        await page.click(btn_sel)
        # Esperar
        await asyncio.sleep(0.6)
        val_post_click = await page.input_value(input_sel)
        print(f"  Después del click: '{val_post_click}'")
        requests_after = len(htmx_requests)
        print(f"  Requests GET /buscar disparados: {requests_after - requests_before}")

        # Verificar que el dropdown tiene resultados
        result_visible = await page.is_visible(result_sel)
        result_content = await page.inner_html(result_sel)
        has_options = "ref-search-option" in result_content
        print(f"  Dropdown visible: {result_visible}, tiene opciones: {has_options}")
        if has_options:
            print(f"  Primeras opciones:")
            for opt in result_content.split('<button')[:4]:
                if 'ref-search-option' in opt:
                    # Tomar el texto del primer span
                    print(f"    {opt[:200]}")

        if val_post_click == "":
            print("  ❌ BUG REPRODUCIDO: el click en BUSCAR borró el input")
        elif has_options:
            print("  ✅ FIX OK: el click en BUSCAR disparó la búsqueda y muestra opciones")
        else:
            print("  ⚠️ El input se mantuvo pero no hay opciones visibles")

        print("\n=== 6) Test bug 3: Submit del form (debe seguir funcionando) ===")
        # Click en la primera opción si existe
        if has_options:
            await page.click(f'{result_sel} .ref-search-option:first-of-type')
            await asyncio.sleep(0.3)
            hidden_val = await page.input_value(f"#ref-ticket-id-{ticket_id}")
            print(f"  ticket_referenciado_id: '{hidden_val}'")

            # Limpiar contadores y capturar POST
            post_count_before = sum(1 for r in all_requests if 'POST' in r[0])
            # Click en Agregar
            await page.click(f"#ref-add-btn-{ticket_id}")
            await asyncio.sleep(1.5)
            # Ver POST request body
            for method, url, body in all_requests[post_count_before:]:
                if 'POST' in method and '/referencias' in url:
                    print(f"  POST {url[:90]}")
                    print(f"  Body: {body[:200] if body else None}")
            # Ver responses nuevas
            new_responses = [r for r in all_responses[post_count_before:] if 'POST' in r[1] or '/referencias' in r[1]]
            for status, url in new_responses:
                print(f"  POST resp: {status} {url[:90]}")
            # Verificar que aparece la nueva referencia en la lista
            list_html = await page.inner_html(f"#referencias-list-{ticket_id}")
            tiene_ref = "REF-TEST" in list_html or "INC-002" in list_html
            print(f"  Lista contiene REF-TEST o INC-002: {tiene_ref}")
            if tiene_ref:
                print("  ✅ Form submit OK")
            else:
                print("  ❌ Form submit FAIL")
                print(f"  List HTML (últimos 200 chars): {list_html[-200:]}")

        await browser.close()
        print("\n=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())