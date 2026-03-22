from __future__ import annotations

import copy
import os
import uuid
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for

from library.loader import load_library_from_csv
from library import service as svc

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "lis-dev-secret-change-for-production")

DATA_DIR = Path(__file__).resolve().parent / "data"
_SESSION_STATES: dict[str, object] = {}
_BASELINE = None

ADMIN_PASSWORD = os.environ.get("LIBRARY_ADMIN_PASSWORD", "lis-admin")


def _baseline():
    global _BASELINE
    if _BASELINE is None:
        _BASELINE = load_library_from_csv(DATA_DIR)
    return _BASELINE


def get_library():
    """Per-browser session library state (assignment: changes do not persist across sessions)."""
    sid = session.get("lis_sid")
    if not sid or sid not in _SESSION_STATES:
        sid = str(uuid.uuid4())
        session["lis_sid"] = sid
        _SESSION_STATES[sid] = copy.deepcopy(_baseline())
    return _SESSION_STATES[sid]


@app.context_processor
def inject_globals():
    lib = get_library()
    card = (session.get("lis_borrower_card") or "").strip()
    b = svc.find_borrower_by_card(lib, card) if card else None
    return {
        "sim_date": lib.simulation_date.isoformat(),
        "admin_logged_in": bool(session.get("lis_admin")),
        "borrower_logged_in": bool(b),
        "borrower_card": card,
        "borrower_display_name": b.name if b else "",
    }


def _require_admin():
    if not session.get("lis_admin"):
        flash("Staff sign-in required.", "err")
        return redirect(url_for("admin_desk"))
    return None


def _borrower_card_or_redirect():
    card = (session.get("lis_borrower_card") or "").strip()
    lib = get_library()
    b = svc.find_borrower_by_card(lib, card) if card else None
    if not b:
        session.pop("lis_borrower_card", None)
        flash("Sign in with a valid library card.", "err")
        return None, redirect(url_for("borrower_portal"))
    return card, None


@app.route("/")
def home():
    return render_template("portal.html")


@app.get("/admin")
def admin_desk():
    if not session.get("lis_admin"):
        return render_template("admin/login.html")
    return render_template("admin/desk.html")


@app.post("/admin/login")
def admin_login():
    if (request.form.get("password") or "") == ADMIN_PASSWORD:
        session["lis_admin"] = True
        flash("Signed in as staff.", "ok")
    else:
        flash("Incorrect password.", "err")
    return redirect(url_for("admin_desk"))


@app.post("/admin/logout")
def admin_logout():
    session.pop("lis_admin", None)
    flash("Signed out.", "ok")
    return redirect(url_for("home"))


@app.get("/borrower")
def borrower_portal():
    lib = get_library()
    card = (session.get("lis_borrower_card") or "").strip()
    profile = svc.query_borrower(lib, card) if card else None
    if card and not profile:
        session.pop("lis_borrower_card", None)
        flash("No borrower found for that card.", "err")
    return render_template("borrower.html", profile=profile)


@app.post("/borrower/login")
def borrower_login():
    card = (request.form.get("card_barcode") or "").strip()
    lib = get_library()
    if not card or not svc.find_borrower_by_card(lib, card):
        flash("No borrower found for that card.", "err")
        session.pop("lis_borrower_card", None)
        return redirect(url_for("borrower_portal"))
    session["lis_borrower_card"] = card
    flash("Signed in.", "ok")
    return redirect(url_for("borrower_portal"))


@app.post("/borrower/logout")
def borrower_logout():
    session.pop("lis_borrower_card", None)
    flash("Signed out.", "ok")
    return redirect(url_for("borrower_portal"))


@app.post("/borrower/checkout")
def borrower_checkout():
    card, redir = _borrower_card_or_redirect()
    if redir:
        return redir
    ok, msg = svc.checkout(get_library(), card, _form_str("copy_barcode"))
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("borrower_portal"))


@app.post("/borrower/return")
def borrower_return():
    lib = get_library()
    card, redir = _borrower_card_or_redirect()
    if redir:
        return redir
    b = svc.find_borrower_by_card(lib, card)
    assert b is not None
    ok, msg = svc.return_copy_for_borrower(lib, _form_str("copy_barcode"), b.borrower_id)
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("borrower_portal"))


@app.post("/borrower/reserve")
def borrower_reserve():
    card, redir = _borrower_card_or_redirect()
    if redir:
        return redir
    ok, msg = svc.reserve_book(get_library(), card, _form_str("isbn"))
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("borrower_portal"))


@app.post("/reset-session")
def reset_session():
    redir = _require_admin()
    if redir:
        return redir
    sid = session.get("lis_sid")
    if sid and sid in _SESSION_STATES:
        del _SESSION_STATES[sid]
    session.pop("lis_sid", None)
    session.pop("lis_admin", None)
    session.pop("lis_borrower_card", None)
    flash("Session cleared — data reloaded from CSV seed. Sign in again if needed.", "ok")
    return redirect(url_for("admin_desk"))


def _form_str(name: str) -> str:
    return (request.form.get(name) or "").strip()


@app.post("/tx/add-copy")
def tx_add_copy():
    redir = _require_admin()
    if redir:
        return redir
    ok, msg, _bc = svc.add_copy(get_library(), _form_str("isbn"))
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("admin_desk"))


@app.post("/tx/remove-copy")
def tx_remove_copy():
    redir = _require_admin()
    if redir:
        return redir
    ok, msg = svc.remove_copy(get_library(), _form_str("barcode"), _form_str("reason"))
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("admin_desk"))


@app.post("/tx/issue-card")
def tx_issue_card():
    redir = _require_admin()
    if redir:
        return redir
    ok, msg, _c = svc.issue_card(
        get_library(),
        _form_str("name"),
        _form_str("phone"),
        _form_str("borrower_type"),
        years_valid=int(_form_str("years_valid") or "1"),
    )
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("admin_desk"))


@app.post("/tx/pay-fines")
def tx_pay_fines():
    redir = _require_admin()
    if redir:
        return redir
    try:
        amt = float(_form_str("amount"))
    except ValueError:
        flash("Invalid amount.", "err")
        return redirect(url_for("admin_desk"))
    ok, msg = svc.pay_fines(get_library(), _form_str("card_barcode"), amt)
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("admin_desk"))


@app.post("/tx/checkout")
def tx_checkout():
    redir = _require_admin()
    if redir:
        return redir
    ok, msg = svc.checkout(
        get_library(),
        _form_str("card_barcode"),
        _form_str("copy_barcode"),
    )
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("admin_desk"))


@app.post("/tx/return")
def tx_return():
    redir = _require_admin()
    if redir:
        return redir
    ok, msg = svc.return_copy(get_library(), _form_str("copy_barcode"))
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("admin_desk"))


@app.post("/tx/new-day")
def tx_new_day():
    redir = _require_admin()
    if redir:
        return redir
    ok, msg = svc.new_day(get_library())
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("admin_desk"))


@app.post("/tx/reserve")
def tx_reserve():
    redir = _require_admin()
    if redir:
        return redir
    ok, msg = svc.reserve_book(get_library(), _form_str("card_barcode"), _form_str("isbn"))
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("admin_desk"))


@app.post("/tx/delete-borrower")
def tx_delete_borrower():
    redir = _require_admin()
    if redir:
        return redir
    ok, msg = svc.delete_borrower(get_library(), _form_str("borrower_id"))
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("admin_desk"))


@app.get("/reports/overdue")
def reports_overdue():
    rows = svc.report_overdue(get_library())
    return render_template("report_overdue.html", rows=rows, sim_date=get_library().simulation_date.isoformat())


@app.get("/reports/inventory")
def reports_inventory():
    rows = svc.report_inventory(get_library())
    return render_template("report_inventory.html", rows=rows, sim_date=get_library().simulation_date.isoformat())


@app.get("/queries")
def queries_hub():
    return render_template("queries.html", sim_date=get_library().simulation_date.isoformat())


@app.get("/query/borrower")
def query_borrower():
    card = request.args.get("card", "").strip()
    data = svc.query_borrower(get_library(), card) if card else None
    return render_template(
        "query_borrower.html",
        card=card,
        data=data,
        sim_date=get_library().simulation_date.isoformat(),
    )


@app.get("/query/copy")
def query_copy():
    bc = request.args.get("barcode", "").strip()
    data = svc.query_copy(get_library(), bc) if bc else None
    return render_template(
        "query_copy.html",
        barcode=bc,
        data=data,
        sim_date=get_library().simulation_date.isoformat(),
    )


@app.get("/query/book")
def query_book():
    isbn = request.args.get("isbn", "").strip()
    data = svc.query_book(get_library(), isbn) if isbn else None
    return render_template(
        "query_book.html",
        isbn=isbn,
        data=data,
        sim_date=get_library().simulation_date.isoformat(),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
