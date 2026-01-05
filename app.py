from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
import re
import json

app = Flask(__name__)
app.secret_key = "change_this_to_any_random_string"

TRANSACTION_OPTIONS = [
    "Vehicle licensing",
    "Register of a new vehicle",
    "Selling of vehicle",
]
CUSTOMER_OPTIONS = ["Private person", "Company"]

PERSONAL_FIELDS = ["name", "surname", "id_number", "address", "cellphone", "email"]
COMPANY_FIELDS = [
    "company_name",
    "company_ck_number",
    "company_representative",
    "representative_id_number",
    "company_cellnum",
    "company_email",
    "company_address",
]
VEHICLE_FIELDS = ["brand", "type", "register_number", "vehicle_licence_number", "vin"]


def is_valid_email(email: str) -> bool:
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None


def build_record_from_session() -> dict:
    record = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "transaction_type": session.get("transaction_type", ""),
        "customer_type": session.get("customer_type", ""),
        "customer": {},
        "vehicle": session.get("vehicle_data", {}),
    }

    if record["customer_type"] == "Private person":
        record["customer"] = session.get("personal_data", {})
    else:
        record["customer"] = session.get("company_data", {})

    return record


def append_record_to_jsonl(record: dict, filename: str = "licenses.jsonl") -> None:
    with open(filename, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


@app.route("/", methods=["GET", "POST"])
def start():
    data = {
        "transaction_type": session.get("transaction_type", ""),
        "customer_type": session.get("customer_type", ""),
    }

    if request.method == "POST":
        transaction_type = request.form.get("transaction_type", "").strip()
        customer_type = request.form.get("customer_type", "").strip()

        if transaction_type not in TRANSACTION_OPTIONS:
            flash("Please select a valid transaction type.")
            return render_template("start.html", data=data, transactions=TRANSACTION_OPTIONS, customers=CUSTOMER_OPTIONS)

        if customer_type not in CUSTOMER_OPTIONS:
            flash("Please select Private person or Company.")
            return render_template("start.html", data=data, transactions=TRANSACTION_OPTIONS, customers=CUSTOMER_OPTIONS)

        session["transaction_type"] = transaction_type
        session["customer_type"] = customer_type

        # Clear any old data if the user starts over
        session.pop("personal_data", None)
        session.pop("company_data", None)
        session.pop("vehicle_data", None)

        if customer_type == "Company":
            return redirect(url_for("company"))
        return redirect(url_for("personal"))

    return render_template("start.html", data=data, transactions=TRANSACTION_OPTIONS, customers=CUSTOMER_OPTIONS)


@app.route("/personal", methods=["GET", "POST"])
def personal():
    if "transaction_type" not in session or "customer_type" not in session:
        flash("Please complete the start questions first.")
        return redirect(url_for("start"))

    if session.get("customer_type") != "Private person":
        return redirect(url_for("company"))

    data = session.get("personal_data", {})

    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in PERSONAL_FIELDS}

        missing = [k for k, v in data.items() if not v]
        if missing:
            flash("Please fill in all personal details.")
            return render_template("personal.html", data=data)

        if not is_valid_email(data["email"]):
            flash("Please enter a valid email address.")
            return render_template("personal.html", data=data)

        session["personal_data"] = data
        return redirect(url_for("vehicle"))

    return render_template("personal.html", data=data)


@app.route("/company", methods=["GET", "POST"])
def company():
    if "transaction_type" not in session or "customer_type" not in session:
        flash("Please complete the start questions first.")
        return redirect(url_for("start"))

    if session.get("customer_type") != "Company":
        return redirect(url_for("personal"))

    data = session.get("company_data", {})

    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in COMPANY_FIELDS}

        missing = [k for k, v in data.items() if not v]
        if missing:
            flash("Please fill in all company details.")
            return render_template("company.html", data=data)

        # basic email check for company email
        if not is_valid_email(data["company_email"]):
            flash("Please enter a valid company email address.")
            return render_template("company.html", data=data)

        session["company_data"] = data
        return redirect(url_for("vehicle"))

    return render_template("company.html", data=data)


@app.route("/vehicle", methods=["GET", "POST"])
def vehicle():
    if "transaction_type" not in session or "customer_type" not in session:
        flash("Please complete the start questions first.")
        return redirect(url_for("start"))

    customer_type = session.get("customer_type")

    if customer_type == "Private person" and "personal_data" not in session:
        flash("Please complete personal details first.")
        return redirect(url_for("personal"))

    if customer_type == "Company" and "company_data" not in session:
        flash("Please complete company details first.")
        return redirect(url_for("company"))

    data = session.get("vehicle_data", {})

    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in VEHICLE_FIELDS}

        missing = [k for k, v in data.items() if not v]
        if missing:
            flash("Please fill in all vehicle details.")
            return render_template("vehicles.html", data=data)

        # THIS is what you asked about earlier:
        session["vehicle_data"] = data

        record = build_record_from_session()
        append_record_to_jsonl(record)

        session.clear()
        flash("Saved successfully!")
        return redirect(url_for("start"))

    return render_template("vehicles.html", data=data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
