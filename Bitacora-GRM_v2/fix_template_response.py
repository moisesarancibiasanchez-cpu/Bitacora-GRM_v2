#!/usr/bin/env python3
"""Migrates templates.TemplateResponse from old (name, ctx) signature to new (request, name, ctx).

This script:
1. Locates every `templates.TemplateResponse(...)` block (multi-line).
2. Rewrites it to `templates.TemplateResponse(request, NAME, { ... })`.
3. Strips the now-redundant `"request": request,` from the context dict.
4. Idempotent: re-running the script on already-fixed code is a no-op.

It intentionally targets only the multi-line form (which is how the
project uses it everywhere). Inline `templates.TemplateResponse("x", {...})`
calls (single-line) are handled the same way by a second regex.
"""
import re
import sys
from pathlib import Path

PATH = Path("app/main.py")
src = PATH.read_text(encoding="utf-8")

orig = src

# 1) Multi-line form:
#    return templates.TemplateResponse(
#        "name.html",
#        {
#            "request": request, ...,
#        },
#    )
# becomes:
#    return templates.TemplateResponse(
#        request,
#        "name.html",
#        {
#            ...,
#        },
#    )

# Match "templates.TemplateResponse(\n" followed by content (no closing paren).
pattern_ml = re.compile(
    r"templates\.TemplateResponse\(\s*\n(\s*)\"([^\"]+)\",\s*\n(\s*)\{",
    flags=re.MULTILINE,
)

def replace_ml(m: re.Match) -> str:
    indent_name = m.group(1)
    indent_body = m.group(3)
    name = m.group(2)
    return (
        f"templates.TemplateResponse(\n"
        f"{indent_name}request,\n"
        f"{indent_name}\"{name}\",\n"
        f"{indent_body}{{"
    )

src = pattern_ml.sub(replace_ml, src)

# 2) Single-line form:
#    templates.TemplateResponse("x.html", {"request": request, ...})
# becomes:
#    templates.TemplateResponse(request, "x.html", {...})
pattern_sl = re.compile(
    r'templates\.TemplateResponse\(\s*"([^"]+)",\s*(\{[^}]*\})\)',
)
def replace_sl(m: re.Match) -> str:
    name = m.group(1)
    ctx = m.group(2)
    return f'templates.TemplateResponse(request, "{name}", {ctx})'
src = pattern_sl.sub(replace_sl, src)

# 3) Strip "request": request, from the context dict.
#    We are conservative: only match when it's followed by another key
#    (i.e. not the LAST key, where trailing comma matters) or by a comma.
#    Actually we strip any "request": request, occurrences in the
#    context dict, even if last (no harm — Jinja2Templates ignores it
#    when passed in kwargs/context).
src = re.sub(r'"request":\s*request,\s*', '', src)
src = re.sub(r'"request":\s*request(\s*\})', r'\1', src)

if src == orig:
    print("No changes.")
else:
    PATH.write_text(src, encoding="utf-8")
    # Quick stats
    n_changes = (orig.count('templates.TemplateResponse(') -
                 src.count('templates.TemplateResponse(request,') +
                 src.count('templates.TemplateResponse(request,'))
    print(f"Updated. Multi-line + single-line rewrites applied. "
          f"File now has {src.count('templates.TemplateResponse(request,')} new-API calls.")
