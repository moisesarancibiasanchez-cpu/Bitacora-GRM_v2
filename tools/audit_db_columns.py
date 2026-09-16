"""Inspecciona metadata de SQLAlchemy y muestra todas las columnas por tabla."""
import os
import sys

os.environ.setdefault('DATABASE_URL', 'sqlite:///./inspect_schema.db')
os.environ.setdefault('SECRET_KEY', 'k')
os.environ.setdefault('AUTO_INIT_DB', 'true')
sys.path.insert(0, '.')

from app.db.base import Base
from app.models import *  # importa todos los modelos


def fmt_type(col):
    """Devuelve una representación legible del tipo de columna."""
    t = col.type
    cls = type(t).__name__
    try:
        if hasattr(t, 'length') and t.length:
            return f'{cls}({t.length})'
        if cls == 'Enum':
            return f'ENUM({", ".join(t.enums)})'
        if cls == 'Boolean':
            return 'BOOLEAN'
        return cls
    except Exception:
        return cls


def fmt_constraints(col):
    parts = []
    if not col.nullable:
        parts.append('NOT NULL')
    if col.primary_key:
        parts.append('PRIMARY KEY')
    if col.unique:
        parts.append('UNIQUE')
    if col.foreign_keys:
        fks = []
        for fk in col.foreign_keys:
            target = fk.column.table.name + '.' + fk.column.name
            ondelete = fk.ondelete
            onupdate = fk.onupdate
            fk_str = target
            if ondelete:
                fk_str += f' ON DELETE {ondelete}'
            if onupdate and onupdate != 'NO ACTION':
                fk_str += f' ON UPDATE {onupdate}'
            fks.append(fk_str)
        parts.append('FK → ' + '; '.join(fks))
    if col.default is not None:
        try:
            parts.append(f'DEFAULT {col.default.arg!r}')
        except Exception:
            pass
    if col.index:
        parts.append('IDX')
    return ' '.join(parts)


print('=' * 100)
print(f' {"TABLA":<32} {"COLUMNA":<28} {"TIPO":<22} CONSTRAINTS')
print('=' * 100)

tables = sorted(Base.metadata.tables.keys(), key=str.lower)
total_cols = 0

for table_name in tables:
    table = Base.metadata.tables[table_name]
    cols = list(table.columns)
    print(f'┌─ {table_name} ({len(cols)} columnas)')
    for i, col in enumerate(cols):
        prefix = '├─' if i < len(cols) - 1 else '└─'
        ctype = fmt_type(col)
        cons = fmt_constraints(col)
        print(f'│  {prefix} {col.name:<28} {ctype:<22} {cons}')
        total_cols += 1
    print('│')
    # Mostrar índices secundarios
    idxs = list(table.indexes)
    if idxs:
        for idx in idxs:
            col_names = ', '.join(c.name for c in idx.columns)
            print(f'└─ INDEX {idx.name}: ({col_names})')
    # Unique constraints
    for uc in table.constraints:
        if hasattr(uc, 'name') and 'unique' in type(uc).__name__.lower():
            print(f'└─ UNIQUE: {[c.name for c in uc.columns]}')

print('=' * 100)
print(f' TABLAS: {len(tables)} | COLUMNAS TOTALES: {total_cols}')
