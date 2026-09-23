"""Deterministic visible identifiers for dashboard visuals."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from dash import html

from .config import NAVIGATION, VISUAL_LINEAGE


_scope: ContextVar[tuple[int, int] | None] = ContextVar("visual_scope", default=None)
_counter: ContextVar[int] = ContextVar("visual_counter", default=0)


def _page_serial(page_id: str) -> int:
    for fallback, page in enumerate(
        sorted(NAVIGATION["dashboards"], key=lambda item: item.get("order", 0)), start=1
    ):
        if page["id"] == page_id:
            return int(page.get("serial", fallback))
    raise KeyError(f"Unknown dashboard page: {page_id}")


def _tab_serial(page_id: str, tab_id: str) -> int:
    if tab_id == "main":
        return 1
    tabs = sorted(
        NAVIGATION.get("subpages", {}).get(page_id, []),
        key=lambda item: item.get("order", 0),
    )
    for fallback, tab in enumerate(tabs, start=1):
        if tab["id"] == tab_id:
            return int(tab.get("serial", fallback))
    raise KeyError(f"Unknown tab {tab_id!r} for dashboard {page_id!r}")


@contextmanager
def visual_scope(page_id: str, tab_id: str = "main"):
    """Reset visual numbering for one rendered dashboard tab."""
    scope_token = _scope.set((_page_serial(page_id), _tab_serial(page_id, tab_id)))
    counter_token = _counter.set(0)
    try:
        yield
    finally:
        _counter.reset(counter_token)
        _scope.reset(scope_token)


def with_visual_scope(page_id: str, tab_id: str = "main"):
    def decorator(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with visual_scope(page_id, tab_id):
                return function(*args, **kwargs)
        return wrapped
    return decorator


def next_visual_id() -> str | None:
    current = _scope.get()
    if current is None:
        return None
    sequence = _counter.get() + 1
    _counter.set(sequence)
    return f"{current[0]}.{current[1]}.{sequence}"


def visual_source_ids(identifier: str | None) -> list[str]:
    return list(VISUAL_LINEAGE.get(identifier, [])) if identifier else []


def identified_visual(component, kind: str, *, identifier: str | None = None):
    """Wrap a table or chart with its visible page.tab.visual identifier."""
    identifier = identifier or next_visual_id()
    if identifier is None:
        return component
    source_ids = visual_source_ids(identifier)
    source_text = ", ".join(source_ids)
    badge_children = [html.Span(kind.title()), html.Code(identifier)]
    if source_ids:
        badge_children.extend([html.Span("Source"), html.Code(source_text)])
    return html.Div(
        [
            html.Div(
                badge_children,
                className="visual-identifier",
                title=(
                    f"{kind.title()} identifier {identifier}; source {source_text}"
                    if source_text else f"{kind.title()} identifier {identifier}"
                ),
            ),
            component,
        ],
        className="identified-visual",
        **{
            "data-visual-id": identifier,
            "data-visual-kind": kind,
            "data-source-ids": source_text,
        },
    )


def unwrap_identified_visual(component):
    """Return the underlying Dash component when a visual has been wrapped."""
    if isinstance(component, html.Div) and getattr(component, "className", None) == "identified-visual":
        return component.children[-1]
    return component
