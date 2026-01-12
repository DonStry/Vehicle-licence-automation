# app.py
import io
import json
import re
from datetime import date, datetime

import streamlit as st
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, BooleanObject, TextStringObject


st.set_page_config(page_title="Vehicle Form Assistant (Wizard)", layout="centered")


# =========================
# Session state init
# =========================
if "step" not in st.session_state:
    st.session_state.step = 1

if "user_type" not in st.session_state:
    st.session_state.user_type = "Personal"

if "data" not in st.session_state:
    st.session_state.data = {}

if "generated_pdf_bytes" not in st.session_state:
    st.session_state.generated_pdf_bytes = None

if "generated_pdf_name" not in st.session_state:
    st.session_state.generated_pdf_name = None


# =========================
# PDF helpers
# =========================
def make_initials(full_name: str) -> str:
    parts = [p for p in (full_name or "").strip().split() if p]
    return "".join([p[0].upper() for p in parts[:3]])


def list_pdf_fields(template_path: str) -> list[str]:
    reader = PdfReader(template_path)
    fields = reader.get_fields() or {}
    return sorted(fields.keys())


def set_field_da_fontsize(writer: PdfWriter, field_to_size: dict[str, int]):
    """
    Updates /DA font size for specific fields.
    If size is 0, most PDF viewers auto-fit to the field.
    Removes /AP so the viewer regenerates appearances.
    """
    if "/AcroForm" in writer._root_object:
        acroform = writer._root_object["/AcroForm"]
        acroform.update({NameObject("/NeedAppearances"): BooleanObject(True)})

    for page in writer.pages:
        annots = page.get("/Annots", [])
        if not annots:
            continue

        for annot_ref in annots:
            annot = annot_ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue

            t = annot.get("/T")
            if not t:
                continue

            field_name = str(t)
            if field_name not in field_to_size:
                continue

            da = annot.get("/DA")
            if not da:
                continue

            size = field_to_size[field_name]
            da_str = str(da)

            # Replace "/FontName 12 Tf" -> "/FontName 0 Tf" (or any size)
            da_str = re.sub(r"(/[\w]+)\s+(\d+(?:\.\d+)?)\s+Tf", rf"\1 {size} Tf", da_str)
            annot.update({NameObject("/DA"): TextStringObject(da_str)})

            # Remove appearance so viewer redraws using new DA
            if "/AP" in annot:
                del annot["/AP"]


def fill_pdf_acroform(template_path: str, field_values: dict) -> bytes:
    reader = PdfReader(template_path)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    root = reader.trailer["/Root"]
    if "/AcroForm" in root:
        writer._root_object.update({NameObject("/AcroForm"): root["/AcroForm"]})
        acroform = writer._root_object["/AcroForm"]
        acroform.update({NameObject("/NeedAppearances"): BooleanObject(True)})

    for page in writer.pages:
        writer.update_page_form_field_values(page, field_values)

    # Sizing rules:
    # 1) Comb fields already configured in PDF, keep them auto-fit (0)
    # 2) Normal text fields: 9
    # 3) Address lines: 8 (they tend to look off if too large)
    FIELD_FONT_SIZES = {
        # Comb / fixed box fields (auto-fit is fine)
        "IDNUMBER": 0,
        "Initials": 0,
        "LicNumber": 0,
        "RegNum": 0,
        "VIN": 0,
        "RepID": 0,
        "RepInti": 0,

        # Normal text fields (smaller)
        "Surname": 8,
        "Name": 8,
        "Email": 8,
        "VehBrand": 8,
        "VehSeries": 8,
        "RepSurname": 8,

        # Address fields (even smaller)
        "Address_line_1": 7,
        "Address_line_2": 7,
        "City": 7,
    }

    set_field_da_fontsize(writer, FIELD_FONT_SIZES)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def make_json_safe(obj):
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_json_safe(v) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj


# =========================
# Field mappers
# =========================
def map_common_fields(user_type: str, data: dict) -> dict:
    fields = {}

    if user_type == "Personal":
        fields["IDNUMBER"] = data.get("id_number", "")
        fields["Surname"] = data.get("surname", "")
        fields["Name"] = data.get("first_name", "")
        fields["Initials"] = make_initials(data.get("first_name", ""))
        fields["Email"] = data.get("email", "")
        fields["Address_line_1"] = data.get("address_line_1", "")
        fields["Address_line_2"] = data.get("address_line_2", "")
        fields["City"] = data.get("city", "")
    else:
        fields["IDNUMBER"] = data.get("company_ck", "")
        fields["Surname"] = data.get("company_name", "")
        fields["Email"] = data.get("email", "")
        fields["Address_line_1"] = data.get("address_line_1", "")
        fields["Address_line_2"] = data.get("address_line_2", "")
        fields["City"] = data.get("city", "")

        fields["RepID"] = data.get("rep_id_number", "")
        fields["RepSurname"] = data.get("rep_surname", "")
        fields["RepInti"] = make_initials(data.get("rep_name", ""))

    fields["LicNumber"] = data.get("license_number", "")
    fields["RegNum"] = data.get("register_number", "")
    fields["VIN"] = data.get("vin", "")
    fields["VehBrand"] = data.get("make", "")
    fields["VehSeries"] = data.get("series_name", "")

    return fields


def map_alv_fields(user_type: str, data: dict) -> dict:
    return map_common_fields(user_type, data)


def map_rlv_fields(user_type: str, data: dict) -> dict:
    return map_common_fields(user_type, data)


def map_nco_fields(user_type: str, data: dict) -> dict:
    return map_common_fields(user_type, data)


# =========================
# Register forms
# =========================
FORM_REGISTRY = {
    "Vehicle licensing": {
        "template": "forms/ALV_Form.pdf",
        "file_suffix": "ALV_form",
        "mapper": map_alv_fields,
    },
    "Registration of new vehicle": {
        "template": "forms/RLV_form.pdf",
        "file_suffix": "RLV_form",
        "mapper": map_rlv_fields,
    },
    "Selling of vehicle": {
        "template": "forms/NCO_form.pdf",
        "file_suffix": "NCO_form",
        "mapper": map_nco_fields,
    },
}


# =========================
# Navigation helpers
# =========================
def next_step():
    st.session_state.step += 1


def prev_step():
    st.session_state.step -= 1


def clear_all():
    st.session_state.step = 1
    st.session_state.user_type = "Personal"
    st.session_state.data = {}
    st.session_state.generated_pdf_bytes = None
    st.session_state.generated_pdf_name = None


# =========================
# Form components
# =========================
def personal_fields():
    d = st.session_state.data
    d["id_number"] = st.text_input("ID number", value=d.get("id_number", ""))
    d["first_name"] = st.text_input("First name", value=d.get("first_name", ""))
    d["surname"] = st.text_input("Surname", value=d.get("surname", ""))
    d["email"] = st.text_input("Email", value=d.get("email", ""))
    d["cellphone"] = st.text_input("Cellphone number", value=d.get("cellphone", ""))
    d["address_line_1"] = st.text_input("Address line 1", value=d.get("address_line_1", ""))
    d["address_line_2"] = st.text_input("Address line 2", value=d.get("address_line_2", ""))
    d["city"] = st.text_input("City", value=d.get("city", ""))
    d["postal_code"] = st.text_input("Postal Code", value=d.get("postal_code", ""))


def company_fields():
    d = st.session_state.data
    d["company_ck"] = st.text_input("Company CK number", value=d.get("company_ck", ""))
    d["company_name"] = st.text_input("Company name", value=d.get("company_name", ""))
    d["rep_id_number"] = st.text_input("Representative ID number", value=d.get("rep_id_number", ""))
    d["rep_name"] = st.text_input("Representative Name", value=d.get("rep_name", ""))
    d["rep_surname"] = st.text_input("Representative Surname", value=d.get("rep_surname", ""))
    d["address_line_1"] = st.text_input("Address line 1", value=d.get("address_line_1", ""))
    d["address_line_2"] = st.text_input("Address line 2", value=d.get("address_line_2", ""))
    d["city"] = st.text_input("City", value=d.get("city", ""))
    d["postal_code"] = st.text_input("Postal Code", value=d.get("postal_code", ""))
    d["email"] = st.text_input("Email", value=d.get("email", ""))
    d["cellphone"] = st.text_input("Cellnumber", value=d.get("cellphone", ""))


def vehicle_fields():
    d = st.session_state.data
    d["license_number"] = st.text_input("License Number", value=d.get("license_number", ""))
    d["register_number"] = st.text_input("Register Number", value=d.get("register_number", ""))
    d["vin"] = st.text_input("VIN", value=d.get("vin", ""))
    d["make"] = st.text_input("Make", value=d.get("make", ""))
    d["series_name"] = st.text_input("Series name", value=d.get("series_name", ""))


def rlv_fields():
    d = st.session_state.data
    st.markdown("#### RLV: Registration of vehicle")
    d["rlv_engine_number"] = st.text_input("Engine number", value=d.get("rlv_engine_number", ""))
    d["rlv_colour"] = st.text_input("Colour", value=d.get("rlv_colour", ""))
    d["rlv_model_year"] = st.text_input("Model year", value=d.get("rlv_model_year", ""))
    d["rlv_vehicle_category"] = st.text_input("Vehicle category/class", value=d.get("rlv_vehicle_category", ""))


def nco_fields():
    d = st.session_state.data
    st.markdown("#### NCO: Selling of motor vehicle (Change of ownership)")
    d["nco_sale_date"] = st.date_input("Date of sale", value=d.get("nco_sale_date"))
    d["nco_sale_price"] = st.text_input("Sale price", value=d.get("nco_sale_price", ""))
    d["nco_odometer"] = st.text_input("Odometer reading (km)", value=d.get("nco_odometer", ""))


# =========================
# Validation
# =========================
def is_blank(value) -> bool:
    return value is None or str(value).strip() == ""


def validate_step(step: int) -> tuple[bool, str]:
    d = st.session_state.data

    if step == 1:
        if st.session_state.user_type not in ("Personal", "Company"):
            return False, "Please choose Personal or Company."
        return True, ""

    if step == 2:
        if st.session_state.user_type == "Personal":
            required = ["id_number", "first_name", "surname", "email", "cellphone", "address_line_1", "city", "postal_code"]
        else:
            required = ["company_ck", "company_name", "rep_id_number", "rep_name", "rep_surname", "address_line_1", "city", "postal_code", "email", "cellphone"]

        missing = [k for k in required if is_blank(d.get(k, ""))]
        if missing:
            return False, "Please complete: " + ", ".join(missing)
        return True, ""

    if step == 3:
        if is_blank(d.get("transaction_type", "")):
            return False, "Please select a transaction type."
        return True, ""

    if step == 4:
        required = ["license_number", "register_number", "vin", "make", "series_name"]
        missing = [k for k in required if is_blank(d.get(k, ""))]
        if missing:
            return False, "Please complete: " + ", ".join(missing)
        return True, ""

    return True, ""


# =========================
# Review UI
# =========================
def pretty_review(user_type: str, data: dict):
    labels = {
        # Personal
        "id_number": "ID Number",
        "first_name": "First Name",
        "surname": "Surname",
        "email": "Email",
        "cellphone": "Cellphone Number",
        "address_line_1": "Address line 1",
        "address_line_2": "Address line 2",
        "city": "City",
        "postal_code": "Postal Code",
        # Company
        "company_ck": "Company CK Number",
        "company_name": "Company Name",
        "rep_id_number": "Representative ID Number",
        "rep_name": "Representative Name",
        "rep_surname": "Representative Surname",
        # Transaction
        "transaction_type": "Transaction Type",
        # Vehicle
        "license_number": "License Number",
        "register_number": "Register Number",
        "vin": "VIN",
        "make": "Make",
        "series_name": "Series Name",
    }

    def show_kv(keys):
        left, right = st.columns(2)
        for i, k in enumerate(keys):
            value = data.get(k, "")
            value = value if str(value).strip() else "-"
            target = left if i % 2 == 0 else right
            with target:
                st.markdown(f"**{labels.get(k, k)}**")
                st.write(value)

    st.subheader("Step 5: Review")

    # ✅ View details expander
    with st.expander("View details", expanded=True):
        with st.container(border=True):
            st.markdown("### Applicant")
            st.caption(f"Applicant type: {user_type}")
            if user_type == "Personal":
                show_kv(["id_number", "first_name", "surname", "email", "cellphone",
                         "address_line_1", "address_line_2", "city", "postal_code"])
            else:
                show_kv(["company_ck", "company_name", "rep_id_number", "rep_name", "rep_surname",
                         "email", "cellphone", "address_line_1", "address_line_2", "city", "postal_code"])

            if st.button("Edit applicant details"):
                st.session_state.step = 2
                st.rerun()

        with st.container(border=True):
            st.markdown("### Transaction")
            show_kv(["transaction_type"])
            if st.button("Edit transaction type"):
                st.session_state.step = 3
                st.rerun()

        with st.container(border=True):
            st.markdown("### Vehicle")
            show_kv(["license_number", "register_number", "vin", "make", "series_name"])
            if st.button("Edit vehicle details"):
                st.session_state.step = 4
                st.rerun()

        with st.expander("Show raw data (advanced)"):
            st.json(data)

    st.divider()

    # Download captured JSON
    st.download_button(
        "Download captured data (JSON)",
        data=json.dumps(make_json_safe({"applicant_type": user_type, **data}), indent=2),
        file_name="captured_data.json",
        mime="application/json",
    )

    # Generate filled PDF
    tx = data.get("transaction_type", "")
    if tx in FORM_REGISTRY:
        cfg = FORM_REGISTRY[tx]

        st.subheader("Generate your form")
        col_a, col_b = st.columns([1, 1])

        with col_a:
            if st.button(f"Generate form: {tx}"):
                try:
                    field_values = cfg["mapper"](user_type, data)
                    pdf_bytes = fill_pdf_acroform(cfg["template"], field_values)

                    # Build filename
                    if user_type == "Personal":
                        initial = (data.get("first_name", "")[:1] or "X").upper()
                        surname = data.get("surname", "Unknown")
                    else:
                        initial = (data.get("rep_name", "")[:1] or "X").upper()
                        surname = data.get("rep_surname", "Unknown")

                    initial = "".join(c for c in initial if c.isalnum())
                    surname = "".join(c for c in surname if c.isalnum())
                    filename = f"{initial}_{surname}_{cfg['file_suffix']}.pdf"

                    st.session_state.generated_pdf_bytes = pdf_bytes
                    st.session_state.generated_pdf_name = filename

                    st.success("Form generated successfully.")
                    st.rerun()
                except FileNotFoundError:
                    st.error(f"Template not found: {cfg['template']}")
                except Exception as e:
                    st.error(f"Could not generate the form: {e}")

        with col_b:
            if st.session_state.generated_pdf_bytes and st.session_state.generated_pdf_name:
                st.download_button(
                    "Download completed PDF",
                    data=st.session_state.generated_pdf_bytes,
                    file_name=st.session_state.generated_pdf_name,
                    mime="application/pdf",
                )
            else:
                st.caption("Generate the form first, then the download will appear here.")

        with st.expander("Developer: Show PDF field names"):
            try:
                st.write(list_pdf_fields(cfg["template"]))
            except Exception as e:
                st.write(f"Could not read fields: {e}")
    else:
        st.info("No PDF template is registered for this transaction yet.")

# =========================
# Main UI
# =========================
st.title("Vehicle Form Assistant!")

with st.sidebar:
    st.header("Controls")
    if st.button("Start over"):
        clear_all()
        st.rerun()

steps_total = 5
st.progress((st.session_state.step - 1) / (steps_total - 1))
st.caption(f"Step {st.session_state.step} of {steps_total}")

if st.session_state.step == 1:
    st.subheader("Step 1: Applicant Type")
    st.session_state.user_type = st.radio(
        "Is this for Personal or Company?",
        ["Personal", "Company"],
        index=0 if st.session_state.user_type == "Personal" else 1,
    )

elif st.session_state.step == 2:
    st.subheader("Step 2: Applicant Details")
    if st.session_state.user_type == "Personal":
        personal_fields()
    else:
        company_fields()

elif st.session_state.step == 3:
    st.subheader("Step 3: Transaction Type")
    d = st.session_state.data
    current = d.get("transaction_type", "")
    options = [""] + list(FORM_REGISTRY.keys())

    idx = options.index(current) if current in options else 0
    d["transaction_type"] = st.selectbox("Select the transaction type", options, index=idx)

elif st.session_state.step == 4:
    st.subheader("Step 4: Transaction Details + Vehicle Details")

    tx = st.session_state.data.get("transaction_type", "")

    if tx == "Registration of new vehicle":
        rlv_fields()
        st.divider()
    elif tx == "Selling of vehicle":
        nco_fields()
        st.divider()

    vehicle_fields()

elif st.session_state.step == 5:
    pretty_review(st.session_state.user_type, st.session_state.data)

st.divider()
left, right = st.columns(2)

with left:
    if st.session_state.step > 1:
        if st.button("Back"):
            prev_step()
            st.rerun()

with right:
    if st.session_state.step < steps_total:
        if st.button("Next"):
            ok, msg = validate_step(st.session_state.step)
            if not ok:
                st.error(msg)
            else:
                # Reset generated PDF when moving between steps
                st.session_state.generated_pdf_bytes = None
                st.session_state.generated_pdf_name = None
                next_step()
                st.rerun()
    else:
        if st.button("Finish (reset)"):
            clear_all()
            st.rerun()
