"""
CorpFlow Portal - Mock Company Web Application
Flask backend server for AI Agent Browser Automation Demonstrations.
Port: 5001
"""

import os
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, abort

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "corpflow-secret-key-2026")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
INVOICES_FILE = os.path.join(DATA_DIR, "invoices.json")
SUBMISSIONS_FILE = os.path.join(DATA_DIR, "submissions.json")


def load_invoices():
    """Load invoice records from invoices.json."""
    if not os.path.exists(INVOICES_FILE):
        return []
    try:
        with open(INVOICES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        app.logger.error(f"Error loading invoices: {e}")
        return []


def load_submissions():
    """Load submission records from submissions.json."""
    if not os.path.exists(SUBMISSIONS_FILE):
        return []
    try:
        with open(SUBMISSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        app.logger.error(f"Error loading submissions: {e}")
        return []


def save_submissions(submissions):
    """Save submission records to submissions.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(SUBMISSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(submissions, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        app.logger.error(f"Error saving submissions: {e}")
        return False


def get_invoice_by_id(inv_id):
    """Find an invoice by integer ID or invoice number."""
    invoices = load_invoices()
    str_id = str(inv_id).strip()
    for inv in invoices:
        if str(inv.get("id")) == str_id or inv.get("invoice_number", "").lower() == str_id.lower():
            return inv
    return None


@app.route("/")
def index():
    """Homepage with company branding and summary stats."""
    invoices = load_invoices()
    submissions = load_submissions()

    total_invoices = len(invoices)
    pending_count = sum(1 for inv in invoices if inv.get("status", "").lower() == "pending")
    overdue_count = sum(1 for inv in invoices if inv.get("status", "").lower() == "overdue")
    paid_count = sum(1 for inv in invoices if inv.get("status", "").lower() == "paid")
    total_submissions = len(submissions)

    return render_template(
        "index.html",
        total_invoices=total_invoices,
        pending_count=pending_count,
        overdue_count=overdue_count,
        paid_count=paid_count,
        total_submissions=total_submissions,
        invoices=invoices[:5],  # Recent top 5
    )


@app.route("/invoices")
def invoices():
    """Invoices listing page with searchable / filterable table."""
    invoices_list = load_invoices()
    return render_template("invoices.html", invoices=invoices_list)


@app.route("/invoices/<inv_id>")
def invoice_detail(inv_id):
    """Invoice detail page showing all fields clearly with explicit DOM IDs."""
    invoice = get_invoice_by_id(inv_id)
    if not invoice:
        abort(404, description=f"Invoice with ID or number '{inv_id}' not found.")
    return render_template("invoice_detail.html", invoice=invoice)


@app.route("/internal/data-entry", methods=["GET", "POST"])
def data_entry():
    """
    GET: Render data entry form (supports pre-fill via query parameters).
    POST: Process form submission, validate, persist, and render success confirmation.
    """
    if request.method == "POST":
        # Handle both form submissions and JSON payloads
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form.to_dict()

        company_name = data.get("company_name", "").strip()
        invoice_number = data.get("invoice_number", "").strip()
        raw_amount = data.get("amount", "").strip()
        currency = data.get("currency", "USD").strip().upper()
        due_date = data.get("due_date", "").strip()
        notes = data.get("notes", "").strip()

        # Simple validation
        errors = []
        if not company_name:
            errors.append("Company Name is required.")
        if not invoice_number:
            errors.append("Invoice Number is required.")
        if not raw_amount:
            errors.append("Amount is required.")
        if not due_date:
            errors.append("Due Date is required.")

        amount = 0.0
        try:
            amount = float(str(raw_amount).replace(",", "").replace("$", "").replace("₹", ""))
        except (ValueError, TypeError):
            errors.append("Amount must be a valid numeric value.")

        if errors:
            if request.is_json or request.headers.get("Accept") == "application/json":
                return jsonify({"status": "error", "errors": errors}), 400
            for err in errors:
                flash(err, "danger")
            return render_template("data_entry.html", prefill=data), 400

        # Create submission record
        submissions = load_submissions()
        submission_num = 1001 + len(submissions)
        sub_id = f"SUB-{submission_num}"

        new_submission = {
            "id": sub_id,
            "company_name": company_name,
            "invoice_number": invoice_number,
            "amount": amount,
            "currency": currency,
            "due_date": due_date,
            "notes": notes,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        submissions.append(new_submission)
        save_submissions(submissions)

        # JSON response for programmatic API requests
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({
                "status": "success",
                "message": "Submission recorded successfully",
                "submission": new_submission
            }), 201

        return render_template("success.html", submission=new_submission)

    # GET request - check if query parameters provide prefill data
    prefill = {
        "company_name": request.args.get("company_name", ""),
        "invoice_number": request.args.get("invoice_number", ""),
        "amount": request.args.get("amount", ""),
        "currency": request.args.get("currency", "USD"),
        "due_date": request.args.get("due_date", ""),
        "notes": request.args.get("notes", "")
    }

    # If invoice_id was given, populate from invoice data
    invoice_id = request.args.get("invoice_id")
    if invoice_id:
        inv = get_invoice_by_id(invoice_id)
        if inv:
            prefill["company_name"] = inv.get("company_name", "")
            prefill["invoice_number"] = inv.get("invoice_number", "")
            prefill["amount"] = inv.get("amount", "")
            prefill["currency"] = inv.get("currency", "USD")
            prefill["due_date"] = inv.get("due_date", "")
            prefill["notes"] = inv.get("description", "")

    return render_template("data_entry.html", prefill=prefill)


@app.route("/internal/submissions")
def view_submissions():
    """View all submitted entries in a table ledger."""
    submissions = load_submissions()
    # Show newest first
    reversed_submissions = list(reversed(submissions))
    return render_template("submissions.html", submissions=reversed_submissions)


@app.route("/api/submissions", methods=["GET"])
def api_submissions():
    """JSON API endpoint returning all submitted entries for programmatic verification."""
    submissions = load_submissions()
    
    # Optional filtering by invoice_number or company_name
    inv_filter = request.args.get("invoice_number")
    company_filter = request.args.get("company_name")
    
    filtered = submissions
    if inv_filter:
        filtered = [s for s in filtered if s.get("invoice_number", "").lower() == inv_filter.lower()]
    if company_filter:
        filtered = [s for s in filtered if company_filter.lower() in s.get("company_name", "").lower()]

    return jsonify({
        "status": "success",
        "count": len(filtered),
        "total": len(submissions),
        "submissions": filtered
    })


@app.route("/api/invoices", methods=["GET"])
def api_invoices():
    """JSON API endpoint returning invoice catalog."""
    invoices_list = load_invoices()
    return jsonify({
        "status": "success",
        "count": len(invoices_list),
        "invoices": invoices_list
    })


@app.route("/api/invoices/<inv_id>", methods=["GET"])
def api_invoice_detail(inv_id):
    """JSON API endpoint for a single invoice."""
    invoice = get_invoice_by_id(inv_id)
    if not invoice:
        return jsonify({"status": "error", "message": "Invoice not found"}), 404
    return jsonify({
        "status": "success",
        "invoice": invoice
    })


@app.errorhandler(404)
def page_not_found(e):
    return render_template(
        "base.html",
        content=f'<div class="card p-5 text-center my-5"><h2 class="text-danger">404 - Not Found</h2><p class="text-secondary">{e.description if hasattr(e, "description") else "The requested page does not exist."}</p><a href="/" class="btn btn-primary d-inline-block mx-auto mt-3">Return to Dashboard</a></div>'
    ), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print("=" * 60)
    print(f" Starting CorpFlow Portal Mock Application on port {port}...")
    print(f" Dashboard URL:      http://0.0.0.0:{port}/")
    print(f" Invoices URL:       http://0.0.0.0:{port}/invoices")
    print(f" Data Entry URL:     http://0.0.0.0:{port}/internal/data-entry")
    print(f" Submissions URL:    http://0.0.0.0:{port}/internal/submissions")
    print(f" Submissions API:    http://0.0.0.0:{port}/api/submissions")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False)
