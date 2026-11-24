"""Shared SQL search, counters and pagination for the service catalogs."""

from peewee import Case, SqliteDatabase, fn

from app.db import database_proxy


def catalog_search(fields, term):
    """Match a literal substring across the same ordered fields shown in the UI."""
    if isinstance(database_proxy.obj, SqliteDatabase):
        # SQLite's built-in LOWER only folds ASCII.
        expression = fn.catalog_search_text(*fields)
    else:
        expression = fn.LOWER(fn.CONCAT_WS(" ", *fields))
    return expression.contains(term.strip().lower())


def catalog_summary(scope, **conditions):
    """Count the visible catalog and each status bucket in one query."""
    counters = [
        fn.COUNT(Case(None, ((condition, 1),))).alias(name)
        for name, condition in conditions.items()
    ]
    return scope.select(fn.COUNT(scope.model._meta.primary_key).alias("total"), *counters).dicts().get()


def catalog_page(query, page, page_size, summary):
    """Count filtered rows and fetch one bounded, deterministically ordered page."""
    page_size = min(100, max(1, page_size))
    total = query.order_by().count()
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(pages, max(1, page))
    start = (page - 1) * page_size
    return {
        "items": list(query.paginate(page, page_size)),
        "pagination": {
            "page": page, "page_size": page_size, "total_items": total,
            "total_pages": pages, "from": start + 1 if total else 0,
            "to": min(start + page_size, total),
            "has_prev": page > 1, "has_next": page < pages,
        },
        "summary": summary,
    }
