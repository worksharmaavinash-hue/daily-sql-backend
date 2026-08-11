"""
SqlDialectGenerator
===================
Converts a dialect-agnostic JSON schema descriptor into SQL DDL (CREATE TABLE)
and DML (INSERT INTO) for a target SQL dialect.

Supported dialects: 'postgresql', 'mysql'

JSON descriptor format
----------------------
{
    "columns": [
        {
            "name":          str,                    # column name (required)
            "type":          str,                    # logical type (see TYPE_MAP below)
            "primary_key":   bool  (optional),
            "auto_increment":bool  (optional),
            "nullable":      bool  (optional, default True),
            "unique":        bool  (optional),
            "default":       any   (optional),
            # type-specific size params:
            "length":        int   (for varchar),
            "precision":     int   (for decimal/numeric),
            "scale":         int   (for decimal/numeric)
        },
        ...
    ],
    "rows": [
        [val1, val2, ...],   # one list per row, values match column order
        ...
    ]
}

Extending this generator
------------------------
- To add a new type:   add an entry to TYPE_MAP below.
- To add a new dialect: add cases in _map_type() and _format_value().
- To add a new attribute (e.g., foreign keys, check constraints): extend
  _build_column_def() with the new attribute.
"""

from __future__ import annotations
from typing import Any


# ──────────────────────────────────────────────────────────────────────────────
# Type mapping table
# Format: logical_type -> {dialect: sql_type_string}
# Add new types here; they become available in all generators automatically.
# ──────────────────────────────────────────────────────────────────────────────
TYPE_MAP: dict[str, dict[str, str]] = {
    "integer":   {"postgresql": "INTEGER",                  "mysql": "INT"},
    "bigint":    {"postgresql": "BIGINT",                   "mysql": "BIGINT"},
    "smallint":  {"postgresql": "SMALLINT",                 "mysql": "SMALLINT"},
    "varchar":   {"postgresql": "VARCHAR({length})",        "mysql": "VARCHAR({length})"},
    "char":      {"postgresql": "CHAR({length})",           "mysql": "CHAR({length})"},
    "text":      {"postgresql": "TEXT",                     "mysql": "TEXT"},
    "decimal":   {"postgresql": "DECIMAL({precision},{scale})", "mysql": "DECIMAL({precision},{scale})"},
    "numeric":   {"postgresql": "NUMERIC({precision},{scale})", "mysql": "DECIMAL({precision},{scale})"},
    "float":     {"postgresql": "FLOAT",                    "mysql": "FLOAT"},
    "double":    {"postgresql": "DOUBLE PRECISION",         "mysql": "DOUBLE"},
    "boolean":   {"postgresql": "BOOLEAN",                  "mysql": "TINYINT(1)"},
    "date":      {"postgresql": "DATE",                     "mysql": "DATE"},
    "timestamp": {"postgresql": "TIMESTAMP WITH TIME ZONE", "mysql": "DATETIME"},
    "json":      {"postgresql": "JSONB",                    "mysql": "JSON"},
}

# Default length/precision/scale if not specified in descriptor
DEFAULT_VARCHAR_LENGTH = 255
DEFAULT_DECIMAL_PRECISION = 10
DEFAULT_DECIMAL_SCALE = 2


class SqlDialectGenerator:
    """
    Stateless generator: call generate() to get (schema_sql, seed_sql).
    All methods are pure functions — no side effects.
    """

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def generate(
        self,
        descriptor: dict | str,
        table_name: str,
        dialect: str,
    ) -> tuple[str, str]:
        """
        Returns (schema_sql, seed_sql) for the given dialect.

        schema_sql: CREATE TABLE statement
        seed_sql:   INSERT INTO statement (empty string if no rows)
        """
        if isinstance(descriptor, str):
            import json
            descriptor = json.loads(descriptor)

        if dialect not in self.supported_dialects():
            raise ValueError(
                f"Unsupported dialect: '{dialect}'. "
                f"Supported: {', '.join(self.supported_dialects())}"
            )

        columns: list[dict] = descriptor.get("columns", [])
        rows: list[list] = descriptor.get("rows", [])

        schema_sql = self._build_create_table(table_name, columns, dialect)
        seed_sql = self._build_insert(table_name, columns, rows, dialect) if rows else ""

        return schema_sql, seed_sql

    @classmethod
    def supported_dialects(cls) -> list[str]:
        """
        Returns the list of SQL dialects this generator supports,
        derived automatically from TYPE_MAP.
        Adding a new dialect to TYPE_MAP makes it available here.
        """
        dialects: set[str] = set()
        for type_variants in TYPE_MAP.values():
            dialects.update(type_variants.keys())
        return sorted(dialects)

    def has_schema_metadata(self, descriptor: dict | str) -> bool:
        """
        Returns True if this descriptor is a rich SQL schema descriptor
        (vs a flat Python/PySpark seed_data_json that has no schema attributes).

        Detection: any column contains at least one schema-level attribute
        (primary_key, auto_increment, nullable, unique, default, length,
        precision, scale).
        """
        if isinstance(descriptor, str):
            import json
            descriptor = json.loads(descriptor)

        schema_attrs = {"primary_key", "auto_increment", "nullable", "unique",
                        "default", "length", "precision", "scale"}
        columns = descriptor.get("columns", [])
        return any(
            schema_attrs.intersection(col.keys())
            for col in columns
        )

    def get_sample_rows(self, descriptor: dict | str) -> list[dict]:
        """
        Returns the first 10 rows as list[dict] for sample_rows storage.
        """
        if isinstance(descriptor, str):
            import json
            descriptor = json.loads(descriptor)

        columns = descriptor.get("columns", [])
        col_names = [c["name"] for c in columns]
        rows = descriptor.get("rows", [])[:10]
        return [dict(zip(col_names, row)) for row in rows]

    # ──────────────────────────────────────────────────────────────────────────
    # DDL builder
    # ──────────────────────────────────────────────────────────────────────────

    def _build_create_table(
        self,
        table_name: str,
        columns: list[dict],
        dialect: str,
    ) -> str:
        col_defs = [self._build_column_def(col, dialect) for col in columns]

        if dialect == "mysql":
            return (
                f"CREATE TABLE `{table_name}` (\n"
                + ",\n".join(f"    {d}" for d in col_defs)
                + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
            )
        else:  # postgresql
            return (
                f'CREATE TABLE "{table_name}" (\n'
                + ",\n".join(f"    {d}" for d in col_defs)
                + "\n);"
            )

    def _build_column_def(self, col: dict, dialect: str) -> str:
        name = col["name"]
        sql_type = self._map_type(col, dialect)

        parts = [f'"{name}"' if dialect == "postgresql" else f"`{name}`", sql_type]

        # AUTO_INCREMENT / SERIAL handling
        if col.get("auto_increment"):
            if dialect == "mysql":
                parts.append("AUTO_INCREMENT")
            # For PostgreSQL, SERIAL already implies auto-increment (handled in _map_type)

        # NOT NULL / NULL
        if col.get("nullable") is False:
            parts.append("NOT NULL")

        # DEFAULT
        if "default" in col:
            default_val = self._format_default(col["default"], col.get("type", ""), dialect)
            parts.append(f"DEFAULT {default_val}")

        # UNIQUE
        if col.get("unique"):
            parts.append("UNIQUE")

        # PRIMARY KEY
        if col.get("primary_key"):
            parts.append("PRIMARY KEY")

        return " ".join(parts)

    # ──────────────────────────────────────────────────────────────────────────
    # DML builder
    # ──────────────────────────────────────────────────────────────────────────

    def _build_insert(
        self,
        table_name: str,
        columns: list[dict],
        rows: list[list],
        dialect: str,
    ) -> str:
        col_names = [c["name"] for c in columns]
        col_types = [c.get("type", "text") for c in columns]

        if dialect == "mysql":
            quoted_cols = ", ".join(f"`{c}`" for c in col_names)
            table_ref = f"`{table_name}`"
        else:
            quoted_cols = ", ".join(f'"{c}"' for c in col_names)
            table_ref = f'"{table_name}"'

        value_rows = []
        for row in rows:
            formatted = [
                self._format_value(val, col_types[i], dialect)
                for i, val in enumerate(row)
            ]
            value_rows.append(f"    ({', '.join(formatted)})")

        return (
            f"INSERT INTO {table_ref} ({quoted_cols}) VALUES\n"
            + ",\n".join(value_rows)
            + ";"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Type mapping
    # ──────────────────────────────────────────────────────────────────────────

    def _map_type(self, col: dict, dialect: str) -> str:
        """
        Maps a column descriptor to a SQL type string for the given dialect.
        Handles SERIAL shorthand for PostgreSQL auto-increment integers.
        """
        logical_type = col.get("type", "text").lower()

        # PostgreSQL SERIAL shorthand (combines INT + sequence in one keyword)
        if dialect == "postgresql" and col.get("auto_increment") and logical_type in ("integer", "bigint", "smallint"):
            serial_map = {"integer": "SERIAL", "bigint": "BIGSERIAL", "smallint": "SMALLSERIAL"}
            return serial_map[logical_type]

        if logical_type not in TYPE_MAP:
            raise ValueError(
                f"Unknown column type: '{logical_type}'. "
                f"Supported types: {sorted(TYPE_MAP.keys())}"
            )

        template = TYPE_MAP[logical_type].get(dialect)
        if not template:
            raise ValueError(f"Type '{logical_type}' has no mapping for dialect '{dialect}'")

        # Substitute size params
        return template.format(
            length=col.get("length", DEFAULT_VARCHAR_LENGTH),
            precision=col.get("precision", DEFAULT_DECIMAL_PRECISION),
            scale=col.get("scale", DEFAULT_DECIMAL_SCALE),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Value formatting
    # ──────────────────────────────────────────────────────────────────────────

    def _format_value(self, value: Any, col_type: str, dialect: str) -> str:
        """
        Formats a Python value as a SQL literal for the target dialect.
        """
        if value is None:
            return "NULL"

        col_type = col_type.lower()

        # Booleans
        if isinstance(value, bool):
            if dialect == "mysql":
                return "1" if value else "0"
            else:
                return "TRUE" if value else "FALSE"

        # Numeric types — emit as-is (no quoting)
        if isinstance(value, (int, float)) and col_type not in ("json",):
            return str(value)

        # Strings, dates, timestamps, json, etc. — single-quoted, escaped
        str_val = str(value).replace("'", "''")  # escape single quotes
        return f"'{str_val}'"

    def _format_default(self, value: Any, col_type: str, dialect: str) -> str:
        """
        Formats a DEFAULT clause value. Same as _format_value but booleans
        use dialect-appropriate literals even in DDL context.
        """
        return self._format_value(value, col_type, dialect)
