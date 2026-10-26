# -*- coding: utf-8 -*-
"""Confirma el comportamiento de LOWER()/LIKE de SQLite frente a acentos.

Relevante para el bug de 4.6/4.7: el literal SQL con el que se comparaba
('produccion ok', sin tilde) nunca coincidía con el nombre real del estado
('Producción OK', con tilde), ni en PostgreSQL (comparación de cadenas
distintas) ni en SQLite (además, LOWER() de SQLite sólo normaliza ASCII).
"""
import sqlite3

c = sqlite3.connect(":memory:")
c.execute("CREATE TABLE e (n TEXT)")
c.execute("INSERT INTO e VALUES ('Producción OK')")
c.execute("INSERT INTO e VALUES ('produccion ok')")
c.execute("INSERT INTO e VALUES ('PRODUCCION OK')")

print("sqlite version   :", sqlite3.sqlite_version)
print("LOWER('Produccion OK') ->", repr(c.execute("SELECT LOWER('Producción OK')").fetchone()[0]))
print("LOWER('PRODUCCION OK') ->", repr(c.execute("SELECT LOWER('PRODUCCION OK')").fetchone()[0]))
print("filas LOWER(n)='produccion ok' :", c.execute(
    "SELECT COUNT(*) FROM e WHERE LOWER(n) = 'produccion ok'").fetchone()[0])
print("filas LOWER(n) LIKE '%produccion%' :", c.execute(
    "SELECT COUNT(*) FROM e WHERE LOWER(n) LIKE '%produccion%'").fetchone()[0])
print("filas LOWER(n) LIKE '%producci%'   :", c.execute(
    "SELECT COUNT(*) FROM e WHERE LOWER(n) LIKE '%producci%'").fetchone()[0])

import unicodedata


def norm(v):
    d = unicodedata.normalize("NFD", v or "")
    s = "".join(ch for ch in d if not unicodedata.combining(ch))
    return " ".join(s.lower().split())


print("normalizacion python 'Produccion OK' ->", repr(norm("Producción OK")))
print("normalizacion python 'produccion ok' ->", repr(norm("produccion ok")))
print("normalizacion python 'PRODUCCION OK' ->", repr(norm("PRODUCCION OK")))
print("las 3 filas normalizan a 'produccion ok':",
      all(norm(r[0]) == "produccion ok" for r in c.execute("SELECT n FROM e").fetchall()))
