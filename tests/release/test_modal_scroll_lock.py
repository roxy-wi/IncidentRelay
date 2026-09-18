"""Regression guards for preventing background scroll through open modals."""

from pathlib import Path


CSS = Path("app/static/css/material.css").read_text(encoding="utf-8")
DIALOGS = Path("app/static/js/core/dialogs.js").read_text(encoding="utf-8")


def test_open_modal_locks_both_root_scroll_containers():
    assert "html.modal-open,\nbody.modal-open" in CSS
    assert "overflow: hidden;" in CSS
    assert "overscroll-behavior: none;" in CSS

    assert '$("html, body").addClass("modal-open");' in DIALOGS
    assert '$("html, body").removeClass("modal-open");' in DIALOGS


def test_modal_body_contains_scroll_chaining_at_its_boundary():
    modal_body_start = CSS.index("body.md-theme .app-modal-body,")
    modal_body_end = CSS.index("body.md-theme .app-modal-footer,", modal_body_start)
    modal_body = CSS[modal_body_start:modal_body_end]

    assert "overflow: auto;" in modal_body
    assert "overscroll-behavior: contain;" in modal_body
