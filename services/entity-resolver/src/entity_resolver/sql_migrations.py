"""Small PostgreSQL migration helpers for asyncpg-backed schema setup.

SQLAlchemy's asyncpg dialect prepares individual statements and therefore cannot
execute a migration file containing multiple top-level commands in one call.
Naively splitting on semicolons is also unsafe because PL/pgSQL function bodies
contain semicolons inside dollar-quoted blocks.
"""
from __future__ import annotations

import re

_DOLLAR_TAG = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


def split_postgres_statements(sql: str) -> list[str]:
    """Split PostgreSQL SQL at top-level semicolons.

    Semicolons inside single-quoted strings, double-quoted identifiers,
    dollar-quoted bodies, line comments, and block comments are preserved.
    This is intentionally a statement splitter, not a SQL parser.
    """
    statements: list[str] = []
    start = 0
    i = 0
    n = len(sql)
    single_quote = False
    double_quote = False
    line_comment = False
    block_comment_depth = 0
    dollar_tag: str | None = None

    while i < n:
        if line_comment:
            if sql[i] == "\n":
                line_comment = False
            i += 1
            continue

        if block_comment_depth:
            if sql.startswith("/*", i):
                block_comment_depth += 1
                i += 2
                continue
            if sql.startswith("*/", i):
                block_comment_depth -= 1
                i += 2
                continue
            i += 1
            continue

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i):
                i += len(dollar_tag)
                dollar_tag = None
            else:
                i += 1
            continue

        ch = sql[i]

        if single_quote:
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    i += 2
                    continue
                single_quote = False
            i += 1
            continue

        if double_quote:
            if ch == '"':
                if i + 1 < n and sql[i + 1] == '"':
                    i += 2
                    continue
                double_quote = False
            i += 1
            continue

        if sql.startswith("--", i):
            line_comment = True
            i += 2
            continue
        if sql.startswith("/*", i):
            block_comment_depth = 1
            i += 2
            continue
        if ch == "'":
            single_quote = True
            i += 1
            continue
        if ch == '"':
            double_quote = True
            i += 1
            continue
        if ch == "$":
            match = _DOLLAR_TAG.match(sql, i)
            if match:
                dollar_tag = match.group(0)
                i = match.end()
                continue
        if ch == ";":
            statement = sql[start:i].strip()
            if statement:
                statements.append(statement)
            start = i + 1
        i += 1

    tail = sql[start:].strip()
    if tail:
        statements.append(tail)
    return statements
