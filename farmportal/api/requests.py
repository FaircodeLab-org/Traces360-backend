# apps/farmportal/farmportal/api/requests.py

import json
import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime
from urllib.parse import urlparse
from farmportal.api.organization_profile import (
    _get_customer_permission_context,
    _get_supplier_permission_context,
    _require_supplier_permission,
    SUPPLIER_PERMISSION_PLOT_MANAGER,
    SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER,
)

DT = "Request"
RISK_ANALYSIS_CACHE_VERSION = "hansen_sentinel_area_v2"

# NEW: preferred user link fields per doctype (ordered by priority)
USER_LINK_FIELDS = {
    "Customer": ["custom_user", "user_id", "user"],
    "Supplier": ["custom_user", "user_id", "user"],
}


def _require_customer_request_permission(user: str, customer_hint: str, request_type: str | None = None) -> dict:
    context = _get_customer_permission_context(user, customer_hint)
    permissions = context.get("permissions", {}) if context else {}
    request_type_key = str(request_type or "").strip().lower()

    if request_type_key == "purchase_order":
        allowed = bool(permissions.get(SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER))
        message = _("You are not allowed to manage purchase order requests")
    else:
        allowed = bool(
            permissions.get(SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER)
            or permissions.get(SUPPLIER_PERMISSION_PLOT_MANAGER)
        )
        message = _("You are not allowed to manage requests")

    if not context.get("has_customer") or not allowed:
        frappe.throw(message, frappe.PermissionError)
    return context


def _require_supplier_request_permission(user: str, supplier_hint: str, request_type: str | None = None) -> dict:
    context = _get_supplier_permission_context(user, supplier_hint)
    permissions = context.get("permissions", {}) if context else {}
    request_type_key = str(request_type or "").strip().lower()

    if request_type_key == "purchase_order":
        allowed = bool(permissions.get(SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER))
        message = _("You are not allowed to manage purchase orders")
    else:
        allowed = bool(
            permissions.get(SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER)
            or permissions.get(SUPPLIER_PERMISSION_PLOT_MANAGER)
        )
        message = _("You are not allowed to manage requests")

    if not context.get("has_supplier") or not allowed:
        frappe.throw(message, frappe.PermissionError)
    return context


def _coerce_page(value, default=1):
    try:
        page = int(value)
        return page if page > 0 else default
    except (TypeError, ValueError):
        return default


def _coerce_page_size(value, default=25, max_size=100):
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = default
    if size <= 0:
        size = default
    return min(size, max_size)


def _build_pagination(page, page_size, total):
    total_pages = (total + page_size - 1) // page_size if page_size else 0
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


def _parse_status_filters(status):
    if status is None:
        return []

    if isinstance(status, (list, tuple, set)):
        raw_values = status
    else:
        raw_values = str(status).split(",")

    values = []
    seen = set()
    for raw in raw_values:
        token = str(raw or "").strip()
        if not token:
            continue
        lowered = token.lower()
        if lowered in ("all", "*"):
            continue
        canonical = token[:1].upper() + token[1:]
        if canonical not in seen:
            seen.add(canonical)
            values.append(canonical)
    return values


def _risk_cache_keys(customer: str) -> dict:
    versioned = f"{RISK_ANALYSIS_CACHE_VERSION}::{customer}"
    return {
        "analysis": f"risk_analysis_completed_on::{versioned}",
        "analyzed": f"risk_analyzed_plots::{versioned}",
        "progress": f"risk_analysis_progress::{versioned}",
    }


def _risk_analyzed_persistent_key(customer: str) -> str:
    versioned = f"{RISK_ANALYSIS_CACHE_VERSION}::{customer}"
    return f"risk_analyzed_plots_persistent::{versioned}"

def _cache_get_json(key: str, default):
    raw = frappe.cache().get_value(key)
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default

def _cache_set_json(key: str, value):
    frappe.cache().set_value(key, json.dumps(value))


def _load_persistent_analyzed_plot_names(customer: str) -> set[str]:
    key = _risk_analyzed_persistent_key(customer)
    raw = frappe.db.get_value(
        "DefaultValue",
        {"parent": "__default", "defkey": key},
        "defvalue",
    )
    if not raw:
        return set()

    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        parsed = []

    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except Exception:
            parsed = [p.strip() for p in parsed.split(",") if p and p.strip()]

    if not isinstance(parsed, list):
        return set()

    return {str(name).strip() for name in parsed if str(name).strip()}


def _save_persistent_analyzed_plot_names(customer: str, names: set[str]):
    key = _risk_analyzed_persistent_key(customer)
    normalized = sorted({str(name).strip() for name in (names or set()) if str(name).strip()})
    if normalized:
        frappe.defaults.set_global_default(key, json.dumps(normalized))
    else:
        frappe.defaults.set_global_default(key, None)

def _normalize_progress_payload(progress: dict | None):
    payload = dict(progress or {})
    status = str(payload.get("status") or "idle").lower()
    total = int(payload.get("total") or 0)
    processed = int(payload.get("processed") or 0)
    processed = min(processed, total) if total > 0 else processed
    percent = round((processed / total) * 100, 1) if total > 0 else (100.0 if status == "completed" else 0.0)
    payload["status"] = status
    payload["total"] = total
    payload["processed"] = processed
    payload["percent"] = percent
    payload["updated"] = int(payload.get("updated") or 0)
    payload["skipped"] = int(payload.get("skipped") or 0)
    payload["failed"] = int(payload.get("failed") or 0)
    payload["message"] = payload.get("message") or ""
    return payload

def _parse_request_plot_ids(request_row: dict) -> list[str]:
    plot_ids = []

    try:
        if request_row.get("shared_plots_json"):
            parsed = request_row["shared_plots_json"]
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            if isinstance(parsed, list):
                plot_ids.extend(parsed)
            elif parsed:
                plot_ids.append(parsed)
    except Exception:
        pass

    try:
        if request_row.get("purchase_order_data"):
            po_data = request_row["purchase_order_data"]
            if isinstance(po_data, str):
                po_data = json.loads(po_data)
            po_plots = (
                po_data.get("selected_plots")
                or po_data.get("selectedPlots")
                or po_data.get("plots")
                or []
            )
            if isinstance(po_plots, str):
                try:
                    po_plots = json.loads(po_plots)
                except Exception:
                    po_plots = [p.strip() for p in po_plots.split(",") if p.strip()]
            if isinstance(po_plots, list) and po_plots and isinstance(po_plots[0], dict):
                po_plots = [p.get("id") or p.get("plot_id") or p.get("name") for p in po_plots]
                po_plots = [p for p in po_plots if p]
            if isinstance(po_plots, list):
                plot_ids.extend(po_plots)
    except Exception:
        pass

    clean = []
    seen = set()
    for pid in plot_ids:
        key = str(pid).strip()
        if key and key not in seen:
            seen.add(key)
            clean.append(key)
    return clean


def _coerce_plot_refs(raw_value) -> list[str]:
    """
    Normalize shared-plot payloads into a clean list of identifiers (name/plot_id).
    Accepts list / JSON string / python-literal string / scalar.
    """
    if raw_value is None:
        return []

    values = []
    if isinstance(raw_value, list):
        values = raw_value
    elif isinstance(raw_value, str):
        raw_text = raw_value.strip()
        if not raw_text:
            return []
        try:
            parsed = json.loads(raw_text)
            values = parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            try:
                import ast
                parsed = ast.literal_eval(raw_text)
                values = parsed if isinstance(parsed, list) else [parsed]
            except Exception:
                values = [raw_text]
    else:
        values = [raw_value]

    refs = []
    seen = set()
    for value in values:
        if isinstance(value, dict):
            candidate = (
                value.get("id")
                or value.get("name")
                or value.get("plot_id")
                or value.get("plotId")
            )
        else:
            candidate = value

        key = str(candidate).strip() if candidate is not None else ""
        if key and key not in seen:
            seen.add(key)
            refs.append(key)

    return refs


def _resolve_supplier_plot_names(supplier_name: str, plot_refs: list[str]) -> list[str]:
    """
    Resolve incoming plot refs (docname or plot_id) to Land Plot docnames,
    strictly scoped to a single supplier.
    """
    supplier_name = str(supplier_name or "").strip()
    if not supplier_name:
        return []

    refs = []
    seen_refs = set()
    for ref in (plot_refs or []):
        key = str(ref).strip()
        if key and key not in seen_refs:
            seen_refs.add(key)
            refs.append(key)

    if not refs:
        return []

    plot_meta = frappe.get_meta("Land Plot")
    has_plot_id = plot_meta.has_field("plot_id")

    by_name_rows = frappe.get_all(
        "Land Plot",
        filters={
            "supplier": supplier_name,
            "docstatus": ["!=", 2],
            "name": ["in", refs],
        },
        fields=["name"],
        limit_page_length=max(len(refs), 1),
    )
    by_name_set = {str(row.get("name") or "").strip() for row in by_name_rows}

    plot_id_to_name = {}
    if has_plot_id:
        by_plot_id_rows = frappe.get_all(
            "Land Plot",
            filters={
                "supplier": supplier_name,
                "docstatus": ["!=", 2],
                "plot_id": ["in", refs],
            },
            fields=["name", "plot_id"],
            limit_page_length=max(len(refs), 1),
        )
        for row in by_plot_id_rows:
            pid = str(row.get("plot_id") or "").strip()
            name = str(row.get("name") or "").strip()
            if pid and name and pid not in plot_id_to_name:
                plot_id_to_name[pid] = name

    resolved_names = []
    seen_names = set()
    for ref in refs:
        resolved = ref if ref in by_name_set else plot_id_to_name.get(ref)
        if resolved and resolved not in seen_names:
            seen_names.add(resolved)
            resolved_names.append(resolved)

    return resolved_names

def _collect_pending_risk_plot_names(customer: str, analyzed_plot_names: set[str]) -> list[str]:
    query = """
        SELECT r.name, r.supplier, r.shared_plots_json, r.purchase_order_data
        FROM `tabRequest` r
        WHERE r.customer = %s
        AND (
            (r.shared_plots_json IS NOT NULL AND r.shared_plots_json != '')
            OR (r.purchase_order_data IS NOT NULL AND r.purchase_order_data != '')
        )
    """
    requests_with_plots = frappe.db.sql(query, (customer,), as_dict=True)

    matched_names = set()
    for req in requests_with_plots:
        refs = _parse_request_plot_ids(req)
        if not refs:
            continue
        supplier_name = str(req.get("supplier") or "").strip()
        if not supplier_name:
            continue
        resolved = _resolve_supplier_plot_names(supplier_name, refs)
        matched_names.update(resolved)

    if not matched_names:
        return []

    # Pending state must be driven by explicit risk-analysis state (cache + persistent store).
    # Land Plot numeric fields can be present with defaults (0/0) before analysis,
    # so treating non-null persisted values as "already analyzed" causes false LOW risk.
    effective_analyzed = {str(n).strip() for n in analyzed_plot_names if n}
    pending = [name for name in matched_names if name not in effective_analyzed]
    pending = [str(n).strip() for n in pending if n]
    pending.sort()
    return pending


def _collect_customer_shared_plot_names(customer: str) -> list[str]:
    """Collect unique plot docnames shared with a customer across requests."""
    query = """
        SELECT r.name, r.supplier, r.shared_plots_json, r.purchase_order_data
        FROM `tabRequest` r
        WHERE r.customer = %s
        AND (
            (r.shared_plots_json IS NOT NULL AND r.shared_plots_json != '')
            OR (r.purchase_order_data IS NOT NULL AND r.purchase_order_data != '')
        )
    """
    requests_with_plots = frappe.db.sql(query, (customer,), as_dict=True)

    matched_names = set()
    for req in requests_with_plots:
        refs = _parse_request_plot_ids(req)
        if not refs:
            continue
        supplier_name = str(req.get("supplier") or "").strip()
        if not supplier_name:
            continue
        resolved = _resolve_supplier_plot_names(supplier_name, refs)
        matched_names.update(resolved)

    names = [str(name).strip() for name in matched_names if str(name).strip()]
    names.sort()
    return names

def _as_list(val):
    if not val:
        return []
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return []
    return val if isinstance(val, list) else []

def _get_user_email(user: str) -> str | None:
    try:
        return frappe.db.get_value("User", user, "email")
    except Exception:
        return None

def _link_by_contact_email(user: str, target_doctype: str) -> str | None:
    """Fallback: User -> Contact (by email) -> Dynamic Link -> (Customer/Supplier)."""
    email = _get_user_email(user)
    if not email:
        return None

    contacts = frappe.get_all("Contact Email", filters={"email_id": email}, fields=["parent"])
    if not contacts:
        return None
    contact_names = [c["parent"] for c in contacts]

    dl = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Contact",
            "parent": ["in", contact_names],
            "link_doctype": target_doctype,
        },
        fields=["link_name"],
        limit=1,
    )
    return dl[0]["link_name"] if dl else None

def _link_by_user_field(doctype: str, user: str) -> str | None:
    """
    Try mapping via a Link field on the target doctype that points to User.
    Priority defined in USER_LINK_FIELDS.
    """
    try:
        meta = frappe.get_meta(doctype)
    except Exception:
        return None

    for fieldname in USER_LINK_FIELDS.get(doctype, []):
        if meta.has_field(fieldname):
            name = frappe.db.get_value(doctype, {fieldname: user}, "name")
            if name:
                return name
    return None

def _get_party_from_user(user: str) -> tuple[str | None, str | None]:
    """
    Resolve (customer_name, supplier_name) for this User.
    1) Try custom_user/user_id/user on the target doctype
    2) Fallback via Contact email -> Dynamic Link
    """
    customer = _link_by_user_field("Customer", user) or _link_by_contact_email(user, "Customer")
    supplier = _link_by_user_field("Supplier", user) or _link_by_contact_email(user, "Supplier")
    return customer, supplier

# (the rest of your file: get_customer_requests, get_supplier_requests,
#  create_request, respond_to_request) stays the same


# @frappe.whitelist()
# def get_customer_requests():
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     try:
#         customer, supplier = _get_party_from_user(user)
#         # Two-type rule: Supplier shouldn't see the customer endpoint
#         if supplier and not customer:
#             return {"requests": []}
#         if not customer:
#             # No mapping found; don't crash—return empty
#             return {"requests": []}

#         rows = frappe.get_all(
#             DT,
#             filters={"customer": customer},
#             # fields=[
#             #     "name as id", "status", "request_type", "message",
#             #     "customer", "supplier", "creation", "modified"
#             # ],
#             fields=[
#                 "name as id", "status", "request_type", "message",
#                 "customer", "supplier", "response_message",   # <— add this
#                 "creation", "modified"
#             ],
#             order_by="creation desc",
#             limit_page_length=200
#         )
#         for r in rows:
#             r["customer_info"] = {"name": r.get("customer")}
#             r["supplier_info"] = {"name": r.get("supplier")}
#         return {"requests": rows}
#     except Exception:
#         frappe.log_error(frappe.get_traceback(), "get_customer_requests error")
#         return {"requests": []}

# @frappe.whitelist()
# def get_supplier_requests():
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     try:
#         customer, supplier = _get_party_from_user(user)
#         if not supplier:
#             return {"requests": []}

#         rows = frappe.get_all(
#             DT,
#             filters={"supplier": supplier},
#             # fields=[
#             #     "name as id", "status", "request_type", "message",
#             #     "customer", "supplier", "creation", "modified"
#             # ],
#             fields=[
#                 "name as id", "status", "request_type", "message",
#                 "customer", "supplier", "response_message",   # <— add this
#                 "creation", "modified"
#             ],
#             order_by="creation desc",
#             limit_page_length=200
#         )
#         for r in rows:
#             r["customer_info"] = {"name": r.get("customer")}
#             r["supplier_info"] = {"name": r.get("supplier")}
#         return {"requests": rows}
#     except Exception:
#         frappe.log_error(frappe.get_traceback(), "get_supplier_requests error")
#         return {"requests": []}

@frappe.whitelist()
def get_customer_requests(page=1, page_size=25, status=None):
    """Get all requests for the current customer"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)
    
    try:
        customer, supplier = _get_party_from_user(user)
        if not customer:
            frappe.throw(_("Customer not found for this user"), frappe.PermissionError)
        _require_customer_request_permission(user, customer)
        
        page_no = _coerce_page(page, default=1)
        page_len = _coerce_page_size(page_size, default=25, max_size=100)
        offset = (page_no - 1) * page_len

        filters = {"customer": customer}
        status_values = _parse_status_filters(status)
        if status_values:
            filters["status"] = ["in", status_values]

        total = int(frappe.db.count("Request", filters=filters) or 0)

        requests = frappe.get_all("Request", 
            filters=filters,
            fields=[
                "name", "customer", "supplier", "request_type", "status", 
                "creation", "response_message", "shared_plots_json", 
                "message", "requested_by", "responded_by",
                "purchase_order_number"  # ✅ Add this field
            ],
            order_by="creation desc",
            limit_start=offset,
            limit_page_length=page_len,
        )
        return {
            "requests": requests,
            "pagination": _build_pagination(page_no, page_len, total),
        }
        
    except frappe.PermissionError:
        raise
    except Exception as e:
        print(f"Error in get_customer_requests: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "get_customer_requests error")
        return {"requests": []}


@frappe.whitelist()
def get_supplier_requests(page=1, page_size=25, status=None):
    """Get all requests for the current supplier"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)
    
    try:
        customer, supplier = _get_party_from_user(user)
        if not supplier:
            frappe.throw(_("Supplier not found for this user"), frappe.PermissionError)
        _require_supplier_request_permission(user, supplier)
        
        page_no = _coerce_page(page, default=1)
        page_len = _coerce_page_size(page_size, default=25, max_size=100)
        offset = (page_no - 1) * page_len

        filters = {"supplier": supplier}
        status_values = _parse_status_filters(status)
        if status_values:
            filters["status"] = ["in", status_values]

        total = int(frappe.db.count("Request", filters=filters) or 0)

        requests = frappe.get_all("Request", 
            filters=filters,
            fields=[
                "name", "customer", "supplier", "request_type", "status", 
                "creation", "response_message", "shared_plots_json", 
                "message", "requested_by", "responded_by",
                "purchase_order_number"  # ✅ Add this field
            ],
            order_by="creation desc",
            limit_start=offset,
            limit_page_length=page_len,
        )
        return {
            "requests": requests,
            "pagination": _build_pagination(page_no, page_len, total),
        }
        
    except frappe.PermissionError:
        raise
    except Exception as e:
        print(f"Error in get_supplier_requests: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "get_supplier_requests error")
        return {"requests": []}


# @frappe.whitelist()
# def create_request(
#     supplier_id: str,
#     request_type: str,
#     message: str | None = None,
#     requested_products: list[dict] | str | None = None,
#     customer_id: str | None = None,  # <-- optional explicit override
# ):
#     """Customer-side: create a Request to a Supplier."""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     customer, supplier_flag = _get_party_from_user(user)
#     # Two-type rule: a true Supplier shouldn't be able to create customer requests
#     if supplier_flag and not customer and not customer_id:
#         frappe.throw(_("Suppliers cannot create requests"), frappe.PermissionError)

#     # Allow explicit customer override if you pass it from the client
#     if customer_id:
#         customer = customer_id

#     if not customer:
#         frappe.throw(_("No Customer linked to your user"), frappe.PermissionError)

#     doc = frappe.new_doc(DT)
#     doc.customer = customer
#     doc.supplier = supplier_id
#     doc.request_type = request_type
#     doc.message = message
#     doc.requested_by = user
#     doc.status = "Pending"

#     items = _as_list(requested_products)
#     if items and doc.meta.get_field("requested_products"):
#         for it in items:
#             row = doc.append("requested_products", {})
#             row.item_code = it.get("item_code")
#             row.qty = it.get("qty")
#             row.uom = it.get("uom")

#     if request_type == "purchase_order":
#         if not purchase_order_number:
#             frappe.throw(_("Purchase Order Number is required"))
#         doc.purchase_order_number = purchase_order_number

#     doc.insert(ignore_permissions=True)
#     frappe.db.commit()
#     return {"name": doc.name, "message": _("Request created")}
@frappe.whitelist()
def create_request(supplier_id, request_type, message=None, purchase_order_number=None, requested_products=None, customer_id=None):
    """Create a new request from customer to supplier"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    try:
        customer, supplier = _get_party_from_user(user)
        if not customer:
            frappe.throw(_("Customer not found for this user"), frappe.PermissionError)
        _require_customer_request_permission(user, customer, request_type=request_type)

        # Validate required fields
        if not supplier_id:
            frappe.throw(_("Supplier is required"))
        if not request_type:
            frappe.throw(_("Request type is required"))

        # Special validation for purchase order requests
        if request_type == "purchase_order" and not purchase_order_number:
            frappe.throw(_("Purchase Order Number is required for Purchase Order requests"))

        print(f"🔍 Creating request: type={request_type}, supplier={supplier_id}, customer={customer}")
        if purchase_order_number:
            print(f"📦 Purchase Order Number: {purchase_order_number}")

        # Do not allow tenant override of customer from request payload.
        # The authenticated user context determines ownership.
        if customer_id and str(customer_id).strip() and str(customer_id).strip() != str(customer):
            frappe.throw(_("Not allowed to create requests for another importer"), frappe.PermissionError)

        # Create the request document
        doc = frappe.new_doc("Request")
        doc.customer = customer
        doc.supplier = supplier_id
        doc.request_type = request_type
        doc.message = message or ""
        doc.status = "Pending"
        doc.requested_by = user

        # Add purchase order number for purchase order requests
        if request_type == "purchase_order" and purchase_order_number:
            # Check if the custom field exists
            if hasattr(doc, 'purchase_order_number'):
                doc.purchase_order_number = purchase_order_number
            else:
                # If custom field doesn't exist yet, store in message for now
                doc.message = f"Purchase Order: {purchase_order_number}\n{message or ''}"
                print(f"⚠️ Custom field 'purchase_order_number' not found, storing in message")

        # Handle requested products if provided
        items = _as_list(requested_products)
        if items and doc.meta.get_field("requested_products"):
            for it in items:
                if isinstance(it, dict):
                    item_code = it.get("item_code") or it.get("productCode") or it.get("itemCode") or it.get("id") or it.get("name")
                    qty = it.get("qty") or it.get("quantity")
                    uom = it.get("uom")
                else:
                    item_code = it
                    qty = None
                    uom = None
                if not item_code:
                    continue
                row = doc.append("requested_products", {})
                row.item_code = item_code
                if qty is not None:
                    row.qty = qty
                if uom:
                    row.uom = uom

        # Save the document
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        print(f"✅ Request created successfully: {doc.name}")

        return {
            "id": doc.name,
            "customer": doc.customer,
            "supplier": doc.supplier,
            "request_type": doc.request_type,
            "status": doc.status,
            "purchase_order_number": purchase_order_number,
            "message": _("Request created successfully"),
        }

    except frappe.PermissionError:
        raise
    except Exception as e:
        print(f"❌ Error creating request: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "create_request error")
        frappe.throw(_("Failed to create request: {0}").format(str(e)))


# @frappe.whitelist()
# def respond_to_request(request_id, action=None, message=None, shared_plots=None, status=None):
#     """Supplier-side: respond to a Request."""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     customer, supplier = _get_party_from_user(user)
#     if not supplier:
#         frappe.throw(_("Only Suppliers can respond"), frappe.PermissionError)

#     doc = frappe.get_doc(DT, request_id)

#     if doc.supplier != supplier:
#         frappe.throw(_("Not permitted to respond to this request"), frappe.PermissionError)

#     final_status = (status or "").strip().lower()
#     if action:
#         act = action.strip().lower()
#         if act == "accept":
#             final_status = "completed"
#         elif act == "reject":
#             final_status = "rejected"

#     if final_status in ("completed", "rejected"):
#         doc.status = final_status.capitalize()

#     if message:
#         doc.response_message = message

#     if shared_plots:
#         try:
#             as_json = json.dumps(shared_plots) if not isinstance(shared_plots, str) else shared_plots
#             doc.shared_plots_json = as_json
#         except Exception:
#             pass

#     doc.responded_by = user
#     doc.save(ignore_permissions=True)
#     frappe.db.commit()
#     return {"message": _("Response saved"), "status": doc.status}

# @frappe.whitelist()
# def respond_to_request(request_id, action=None, message=None, shared_plots=None, status=None):
#     """Supplier-side: respond to a Request."""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     customer, supplier = _get_party_from_user(user)
#     if not supplier:
#         frappe.throw(_("Only Suppliers can respond"), frappe.PermissionError)

#     doc = frappe.get_doc(DT, request_id)

#     if doc.supplier != supplier:
#         frappe.throw(_("Not permitted to respond to this request"), frappe.PermissionError)

#     # --- Normalize action/status very liberally ---
#     s = (status or "").strip().lower()
#     a = (action or "").strip().lower()

#     print(a, s)

#     # map many variants to final statuses
#     if a in {"accepted", "approved", "approve", "ok"}:
#         s = "accepted"
#     elif a in {"reject", "decline", "declined", "no"}:
#         s = "rejected"

#     if s in {"completed", "complete", "accepted", "accept"}:
#         doc.status = "Completed"
#     elif s in {"rejected", "reject"}:
#         doc.status = "Rejected"
#     # else: leave as-is (e.g., Pending) if nothing matched

#     if message is not None:
#         doc.response_message = message

#     if shared_plots:
#         try:
#             as_json = json.dumps(shared_plots) if not isinstance(shared_plots, str) else shared_plots
#             doc.shared_plots_json = as_json
#         except Exception:
#             pass

#     doc.responded_by = user
#     doc.save(ignore_permissions=True)
#     frappe.db.commit()

#     # Return fresh, useful fields so UI can update instantly
#     return {
#         "id": doc.name,
#         "status": doc.status,
#         "response_message": doc.response_message,
#         "customer": doc.customer,
#         "supplier": doc.supplier,
#         "message": _("Response saved"),
#     }


@frappe.whitelist()
def respond_to_request(request_id, action=None, message=None, shared_plots=None, status=None):
    """Supplier-side: respond to a Request."""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can respond"), frappe.PermissionError)

    doc = frappe.get_doc(DT, request_id)

    if doc.supplier != supplier:
        frappe.throw(_("Not permitted to respond to this request"), frappe.PermissionError)
    _require_supplier_request_permission(user, supplier, request_type=doc.get("request_type"))

    request_type = str(doc.get("request_type") or "").strip().lower()
    if request_type == "purchase_order":
        _require_supplier_permission(
            user,
            SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER,
            supplier_hint=supplier,
            message=_("You are not allowed to manage purchase orders"),
        )

    # --- Normalize inputs ---
    a = (action or "").strip().lower()
    s = (status or "").strip().lower()

    # Accept / reject synonyms (cover both action and status)
    ACCEPT = {"accept", "accepted", "approve", "approved", "ok", "yes", "y", "complete", "completed", "done"}
    REJECT = {"reject", "rejected", "decline", "declined", "no", "n"}

    # Pick a single token to decide with
    token = a or s  # prefer explicit action, else status

    if token in ACCEPT:
        doc.status = "Accepted"
    elif token in REJECT:
        doc.status = "Rejected"
    # else: leave doc.status as-is (e.g., Pending) if nothing matched

    if message is not None:
        doc.response_message = message

    if shared_plots:
        try:
            as_json = json.dumps(shared_plots) if not isinstance(shared_plots, str) else shared_plots
            doc.shared_plots_json = as_json
        except Exception:
            pass

    doc.responded_by = user
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Return fresh fields for optimistic UI update
    return {
        "id": doc.name,
        "status": doc.status,
        "response_message": doc.response_message,
        "customer": doc.customer,
        "supplier": doc.supplier,
        "message": _("Response saved"),
    }


@frappe.whitelist()
def get_dashboard_stats():
    """Return per-user request counts + a few extras without fetching all rows."""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    def _doctype_exists(dt):
        try:
            frappe.get_meta(dt)
            return True
        except Exception:
            return False

    def _count_if_exists(dt, filters=None):
        try:
            if not _doctype_exists(dt):
                return 0
            return frappe.db.count(dt, filters=filters or {})
        except Exception:
            return 0

    customer, supplier = _get_party_from_user(user)

    # Decide whose dashboard this is
    filters = {}
    role = None
    if supplier and not customer:
        role = "supplier"
        filters = {"supplier": supplier}
    elif customer:
        role = "customer"
        filters = {"customer": customer}
    else:
        # No mapping found; return zeros
        return {
            "stats": {
                "totalRequests": 0,
                "pendingRequests": 0,
                "completedRequests": 0,
                "landPlots": 0,
                "products": 0,
                "complianceRate": 0,
            },
            "recent": [],
            "role": None,
        }

    COMPLETED = ["Completed", "Accepted"]
    PENDING = ["Pending"]

    total = frappe.db.count("Request", filters=filters)
    completed = frappe.db.count("Request", filters={**filters, "status": ["in", COMPLETED]})
    pending = frappe.db.count("Request", filters={**filters, "status": ["in", PENDING]})


    # Optional extras (safe if doctypes don’t exist)
    if role == "supplier":
        land_plots = _count_if_exists("Land Plot", filters)
    else:
        try:
            land_plots = len(_collect_customer_shared_plot_names(customer))
        except Exception:
            land_plots = 0
    products = _count_if_exists("Item", {"disabled": 0}) if role == "supplier" else 0

    compliance_rate = round((completed / total * 100), 0) if total else 0

    recent = frappe.get_all(
        "Request",
        filters=filters,
        fields=["name as id", "status", "request_type", "message", "creation"],
        order_by="creation desc",
        limit=5,
    )

    return {
        "stats": {
            "totalRequests": total,
            "pendingRequests": pending,
            "completedRequests": completed,
            "landPlots": land_plots,
            "products": products,
            "complianceRate": compliance_rate,
        },
        "recent": recent,
        "role": role,
    }

# @frappe.whitelist()
# def get_supplier_land_plots():
#     """Get land plots for the current supplier user to share with requests"""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     customer, supplier = _get_party_from_user(user)
#     if not supplier:
#         frappe.throw(_("Only Suppliers can access land plots"), frappe.PermissionError)

#     try:
#         # Get land plots for this supplier
#         plots = frappe.get_all(
#             "Land Plot",
#             filters={"supplier": supplier, "docstatus": ["!=", 2]},  # Not cancelled
#             fields=[
#                 "name as id",
#                 "plot_id",
#                 "plot_name", 
#                 "country",
#                 "area",
#                 "coordinates",
#                 "commodities",
#                 "products",
#                 "deforestation_percentage",
#                 "deforested_area"
#             ],
#             order_by="creation desc",
#             limit_page_length=500
#         )

#         # Process the plots data
#         for plot in plots:
#             # Handle commodities/products that might be stored as JSON strings
#             if plot.get("commodities") and isinstance(plot["commodities"], str):
#                 try:
#                     plot["commodities"] = json.loads(plot["commodities"])
#                 except:
#                     plot["commodities"] = plot["commodities"].split(",") if plot["commodities"] else []
            
#             if plot.get("products") and isinstance(plot["products"], str):
#                 try:
#                     plot["products"] = json.loads(plot["products"])
#                 except:
#                     plot["products"] = plot["products"].split(",") if plot["products"] else []

#         return {"plots": plots}
    
#     except Exception as e:
#         frappe.log_error(frappe.get_traceback(), "get_supplier_land_plots error")
#         return {"plots": []}
@frappe.whitelist()
def get_supplier_land_plots():
    """Get land plots for the current supplier user to share with requests"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can access land plots"), frappe.PermissionError)
    _require_supplier_request_permission(user, supplier)

    try:
        # Get land plots for this supplier - REMOVED 'products' field
        plot_meta = frappe.get_meta("Land Plot")
        has_plot_id = plot_meta.has_field("plot_id")
        name_field = "farmer_name" if plot_meta.has_field("farmer_name") else ("plot_name" if plot_meta.has_field("plot_name") else None)

        fields = [
            "name as id",
            "country",
            "area",
            "coordinates",
            "commodities",  # This field exists
            "deforestation_percentage",
            "deforested_area"
        ]
        if has_plot_id:
            fields.insert(1, "plot_id")
        if name_field:
            fields.insert(2 if has_plot_id else 1, f"{name_field} as plot_name")

        plots = frappe.get_all(
            "Land Plot",
            filters={"supplier": supplier, "docstatus": ["!=", 2]},
            fields=fields,
            order_by="creation desc",
            limit_page_length=500
        )

        print(f"📍 Found {len(plots)} plots for supplier {supplier}")

        # Process the plots data
        for plot in plots:
            # Handle commodities that might be stored as JSON strings
            if plot.get("commodities") and isinstance(plot["commodities"], str):
                try:
                    plot["commodities"] = json.loads(plot["commodities"])
                except:
                    plot["commodities"] = plot["commodities"].split(",") if plot["commodities"] else []
            elif not plot.get("commodities"):
                plot["commodities"] = []
            
            # Set products same as commodities (since products field doesn't exist)
            plot["products"] = plot["commodities"]

        return {"plots": plots}
    
    except Exception as e:
        print(f"❌ Error in get_supplier_land_plots: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "get_supplier_land_plots error")
        return {"plots": []}


# @frappe.whitelist()
# def get_shared_plots(request_id):
#     """Get shared land plots for a specific request"""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     try:
#         # Get the request
#         request_doc = frappe.get_doc("Request", request_id)
        
#         # Check if user has access (either customer or supplier of this request)
#         customer, supplier = _get_party_from_user(user)
#         if request_doc.customer != customer and request_doc.supplier != supplier:
#             frappe.throw(_("Not permitted to view this request"), frappe.PermissionError)

#         # Get shared plots from the request
#         shared_plots_json = request_doc.get("shared_plots_json")
#         if not shared_plots_json:
#             return {"plots": [], "request": {"id": request_doc.name, "status": request_doc.status}}

#         try:
#             plot_ids = json.loads(shared_plots_json) if isinstance(shared_plots_json, str) else shared_plots_json
#         except:
#             return {"plots": [], "request": {"id": request_doc.name, "status": request_doc.status}}

#         # Get the actual land plot data
#         if plot_ids:
#             plots = frappe.get_all(
#                 "Land Plot",
#                 filters={"name": ["in", plot_ids]},
#                 fields=[
#                     "name as id",
#                     "plot_id",
#                     "plot_name",
#                     "country", 
#                     "area",
#                     "coordinates",
#                     "commodities",
#                     "products",
#                     "deforestation_percentage",
#                     "deforested_area",
#                     "geojson"
#                 ]
#             )

#             # Process the plots data
#             for plot in plots:
#                 if plot.get("commodities") and isinstance(plot["commodities"], str):
#                     try:
#                         plot["commodities"] = json.loads(plot["commodities"])
#                     except:
#                         plot["commodities"] = plot["commodities"].split(",") if plot["commodities"] else []
                
#                 if plot.get("products") and isinstance(plot["products"], str):
#                     try:
#                         plot["products"] = json.loads(plot["products"])
#                     except:
#                         plot["products"] = plot["products"].split(",") if plot["products"] else []

#         else:
#             plots = []

#         return {
#             "plots": plots,
#             "request": {
#                 "id": request_doc.name,
#                 "status": request_doc.status,
#                 "customer": request_doc.customer,
#                 "supplier": request_doc.supplier,
#                 "message": request_doc.message,
#                 "response_message": request_doc.response_message
#             }
#         }

#     except Exception as e:
#         frappe.log_error(frappe.get_traceback(), f"get_shared_plots error for {request_id}")
#         return {"plots": [], "request": None}

@frappe.whitelist()
def get_shared_plots(request_id):
    """Get shared land plots for a specific request"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    try:
        # Get the request
        request_doc = frappe.get_doc("Request", request_id)
        
        print(f"🔍 Getting shared plots for request: {request_id}")
        print(f"📦 Raw shared_plots_json field: {request_doc.shared_plots_json}")
        
        # Check if user has access
        customer, supplier = _get_party_from_user(user)
        if request_doc.customer != customer and request_doc.supplier != supplier:
            frappe.throw(_("Not permitted to view this request"), frappe.PermissionError)
        if request_doc.customer == customer:
            _require_customer_request_permission(
                user,
                customer,
                request_type=request_doc.get("request_type"),
            )
        elif request_doc.supplier == supplier:
            _require_supplier_request_permission(
                user,
                supplier,
                request_type=request_doc.get("request_type"),
            )

        plot_ids = []

        # 1) Shared plots JSON (land plot requests)
        shared_plots_json = request_doc.get("shared_plots_json")
        if shared_plots_json:
            try:
                parsed = json.loads(shared_plots_json) if isinstance(shared_plots_json, str) else shared_plots_json
                if isinstance(parsed, list):
                    plot_ids.extend(parsed)
                else:
                    plot_ids.append(parsed)
                print(f"📍 Parsed plot IDs from shared_plots_json: {plot_ids}")
            except Exception as parse_error:
                try:
                    import ast
                    parsed = ast.literal_eval(shared_plots_json) if isinstance(shared_plots_json, str) else shared_plots_json
                    if isinstance(parsed, list):
                        plot_ids.extend(parsed)
                    else:
                        plot_ids.append(parsed)
                    print(f"📍 Parsed plot IDs via literal_eval: {plot_ids}")
                except Exception:
                    print(f"❌ Error parsing shared plots JSON: {str(parse_error)}")
                    raw = str(shared_plots_json)
                    plot_ids.extend([p.strip().strip("'").strip('"') for p in raw.strip("[](){}").split(",") if p.strip()])
                    print(f"📍 Parsed plot IDs via fallback split: {plot_ids}")

        # 2) Purchase order data (selected plots)
        if request_doc.purchase_order_data:
            try:
                po_data = json.loads(request_doc.purchase_order_data) if isinstance(request_doc.purchase_order_data, str) else request_doc.purchase_order_data
                po_plots = (
                    po_data.get("selected_plots")
                    or po_data.get("selectedPlots")
                    or po_data.get("plots")
                    or []
                )
                if isinstance(po_plots, str):
                    try:
                        po_plots = json.loads(po_plots)
                    except Exception:
                        po_plots = [p.strip() for p in po_plots.split(",") if p.strip()]
                if isinstance(po_plots, list) and po_plots and isinstance(po_plots[0], dict):
                    po_plots = [p.get("id") or p.get("plot_id") or p.get("name") for p in po_plots]
                    po_plots = [p for p in po_plots if p]
                if isinstance(po_plots, list):
                    plot_ids.extend(po_plots)
            except Exception:
                pass

        # Deduplicate
        seen = set()
        plot_ids = [p for p in plot_ids if p and not (p in seen or seen.add(p))]

        if not plot_ids:
            print(f"⚠️ No shared plots found in shared_plots_json or purchase_order_data")
            return {"plots": [], "request": {"id": request_doc.name, "status": request_doc.status}}

        # Enforce supplier boundary to prevent cross-supplier plot leakage.
        valid_plot_names = _resolve_supplier_plot_names(request_doc.supplier, plot_ids)
        if not valid_plot_names:
            return {"plots": [], "request": {"id": request_doc.name, "status": request_doc.status}}

        # Get the actual land plot data
        plots = []
        if plot_ids:
            if isinstance(plot_ids, str):
                plot_ids = [plot_ids]

            plot_meta = frappe.get_meta("Land Plot")
            fields = [
                "name as id",
                "plot_id",
                "country",
                "area",
                "coordinates",
                "commodities",
                "deforestation_percentage",
                "deforested_area"
            ]
            if not plot_meta.has_field("plot_id"):
                fields.remove("plot_id")
            if plot_meta.has_field("plot_name"):
                fields.append("plot_name")
            if plot_meta.has_field("farmer_name"):
                fields.append("farmer_name")

            plots = frappe.get_all(
                "Land Plot",
                filters={
                    "supplier": request_doc.supplier,
                    "name": ["in", valid_plot_names],
                },
                fields=fields
            )
            
            print(f"✅ Found {len(plots)} matching plots")

        return {
            "plots": plots,
            "request": {
                "id": request_doc.name,
                "status": request_doc.status,
                "customer": request_doc.customer,
                "supplier": request_doc.supplier,
                "message": request_doc.message,
                "response_message": request_doc.response_message
            }
        }

    except Exception as e:
        print(f"❌ Error in get_shared_plots: {str(e)}")
        frappe.log_error(frappe.get_traceback(), f"get_shared_plots error for {request_id}")
        return {"plots": [], "request": None}



# Update the respond_to_request function to handle plot names instead of IDs
# @frappe.whitelist()
# def respond_to_request(request_id, action=None, message=None, shared_plots=None, status=None):
#     """Supplier-side: respond to a Request with optional land plot sharing."""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     customer, supplier = _get_party_from_user(user)
#     if not supplier:
#         frappe.throw(_("Only Suppliers can respond"), frappe.PermissionError)

#     doc = frappe.get_doc("Request", request_id)

#     if doc.supplier != supplier:
#         frappe.throw(_("Not permitted to respond to this request"), frappe.PermissionError)

#     # --- Normalize inputs ---
#     a = (action or "").strip().lower()
#     s = (status or "").strip().lower()

#     # Accept / reject synonyms
#     ACCEPT = {"accept", "accepted", "approve", "approved", "ok", "yes", "y", "complete", "completed", "done"}
#     REJECT = {"reject", "rejected", "decline", "declined", "no", "n"}

#     token = a or s

#     if token in ACCEPT:
#         doc.status = "Accepted"
#     elif token in REJECT:
#         doc.status = "Rejected"

#     if message is not None:
#         doc.response_message = message

#     # Handle shared plots - expect plot names/IDs from frontend
#     if shared_plots:
#         try:
#             # shared_plots should be a list of land plot names/IDs
#             plot_list = shared_plots if isinstance(shared_plots, list) else json.loads(shared_plots)
#             doc.shared_plots_json = json.dumps(plot_list)
#         except Exception as e:
#             frappe.log_error(f"Error processing shared plots: {str(e)}")

#     doc.responded_by = user
#     doc.save(ignore_permissions=True)
#     frappe.db.commit()

#     return {
#         "id": doc.name,
#         "status": doc.status,
#         "response_message": doc.response_message,
#         "customer": doc.customer,
#         "supplier": doc.supplier,
#         "shared_plots_count": len(json.loads(doc.shared_plots_json)) if doc.shared_plots_json else 0,
#         "message": _("Response saved"),
#     }
@frappe.whitelist()
def respond_to_request(request_id, action=None, message=None, shared_plots=None, status=None):
    """Supplier-side: respond to a Request with optional land plot sharing."""

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can respond"), frappe.PermissionError)

    doc = frappe.get_doc("Request", request_id)

    if doc.supplier != supplier:
        frappe.throw(_("Not permitted to respond to this request"), frappe.PermissionError)
    _require_supplier_request_permission(user, supplier, request_type=doc.get("request_type"))

    # Simple status update
    if action == "accept":
        doc.status = "Accepted"
    elif action == "reject":
        doc.status = "Rejected"

    if message:
        doc.response_message = message

    # Shared plots handling with strict supplier ownership validation
    if shared_plots:
        requested_plot_refs = _coerce_plot_refs(shared_plots)
        valid_plot_names = _resolve_supplier_plot_names(supplier, requested_plot_refs)
        if not valid_plot_names:
            frappe.throw(
                _("No valid supplier-owned land plots found in shared_plots"),
                frappe.PermissionError,
            )
        doc.shared_plots_json = json.dumps(valid_plot_names)

    doc.responded_by = user

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "id": doc.name,
        "status": doc.status,
        "message": "Response saved"
    }


#for risk dashboard
# Add to your requests.py file

@frappe.whitelist()
def get_risk_dashboard_data():
    """Get risk analysis data for customer dashboard"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    try:
        customer, supplier = _get_party_from_user(user)
        if not customer:
            return {"suppliers": [], "summary": {}}

        # Risk analysis state: combine fast cache + persistent DB-backed state.
        keys = _risk_cache_keys(customer)
        parsed_analyzed = _cache_get_json(keys["analyzed"], []) or []
        cached_analyzed_plot_names = {str(p).strip() for p in parsed_analyzed if p}
        persistent_analyzed_plot_names = _load_persistent_analyzed_plot_names(customer)
        analyzed_plot_names = cached_analyzed_plot_names | persistent_analyzed_plot_names
        if persistent_analyzed_plot_names and not cached_analyzed_plot_names:
            _cache_set_json(keys["analyzed"], sorted(analyzed_plot_names))

        # Get all requests for this customer with shared plots
        requests_with_plots = frappe.db.sql("""
            SELECT 
                r.name,
                r.supplier,
                r.request_type,
                r.shared_plots_json,
                r.purchase_order_data,
                r.status,
                r.creation,
                r.response_message
            FROM `tabRequest` r
            WHERE r.customer = %s 
            AND (
                (r.shared_plots_json IS NOT NULL AND r.shared_plots_json != '')
                OR (r.purchase_order_data IS NOT NULL AND r.purchase_order_data != '')
            )
            ORDER BY r.creation DESC
        """, (customer,), as_dict=True)

        suppliers_data = {}
        
        for request in requests_with_plots:
            supplier_name = request.supplier
            
            if supplier_name not in suppliers_data:
                # Get supplier info
                supplier_info = frappe.db.get_value(
                    "Supplier",
                    supplier_name,
                    ["supplier_name", "country", "supplier_group"],
                    as_dict=True
                )

                suppliers_data[supplier_name] = {
                    "name": supplier_name,
                    "supplier_name": supplier_info.get("supplier_name") if supplier_info else supplier_name,
                    "country": supplier_info.get("country") if supplier_info else "Unknown",
                    "supplier_group": supplier_info.get("supplier_group") if supplier_info else "",
                    "unique_plots": {},  # ✅ Use dict to store unique plots by plot ID
                    "requests": [],
                    "total_area": 0,
                    "total_deforestation": 0,
                    "high_risk_plots": 0,
                    "medium_risk_plots": 0,
                    "low_risk_plots": 0,
                    "last_analysis": request.creation,
                    "status": "active"
                }
            
            # Parse shared plots (land plot requests + purchase order responses)
            try:
                plot_ids = []

                if request.shared_plots_json:
                    parsed = json.loads(request.shared_plots_json) if isinstance(request.shared_plots_json, str) else request.shared_plots_json
                    if isinstance(parsed, list):
                        plot_ids.extend(parsed)

                if request.purchase_order_data:
                    try:
                        po_data = json.loads(request.purchase_order_data) if isinstance(request.purchase_order_data, str) else request.purchase_order_data
                        po_plots = (
                            po_data.get("selected_plots")
                            or po_data.get("selectedPlots")
                            or po_data.get("plots")
                            or []
                        )
                        # Normalize list payloads (could be list of objects or JSON string)
                        if isinstance(po_plots, str):
                            try:
                                po_plots = json.loads(po_plots)
                            except Exception:
                                po_plots = [p.strip() for p in po_plots.split(',') if p.strip()]
                        if isinstance(po_plots, list) and po_plots and isinstance(po_plots[0], dict):
                            po_plots = [p.get("id") or p.get("plot_id") or p.get("name") for p in po_plots]
                            po_plots = [p for p in po_plots if p]
                        plot_ids.extend(po_plots or [])
                    except Exception:
                        pass

                # Deduplicate while preserving order
                seen = set()
                plot_ids = [p for p in plot_ids if p and not (p in seen or seen.add(p))]

                # Get plot details
                if plot_ids:
                    plot_meta = frappe.get_meta("Land Plot")
                    has_plot_id = plot_meta.has_field("plot_id")
                    plot_fields = [
                        "name", "country", "area",
                        "deforestation_percentage", "deforested_area", 
                        "commodities", "coordinates"
                    ]
                    if has_plot_id:
                        plot_fields.insert(1, "plot_id")
                    if plot_meta.has_field("farmer_name"):
                        plot_fields.append("farmer_name")
                    if plot_meta.has_field("plot_name"):
                        plot_fields.append("plot_name")
                    if plot_meta.has_field("custom_risk_mitigated"):
                        plot_fields.append("custom_risk_mitigated")
                    if plot_meta.has_field("custom_risk_mitigation_note"):
                        plot_fields.append("custom_risk_mitigation_note")
                    if plot_meta.has_field("custom_risk_mitigation_on"):
                        plot_fields.append("custom_risk_mitigation_on")
                    if plot_meta.has_field("custom_risk_mitigation_by"):
                        plot_fields.append("custom_risk_mitigation_by")
                    attachment_field_candidates = [
                        "custom_risk_mitigation_attachment",
                        "custom_risk_mitigation_file",
                        "custom_risk_mitigation_document",
                        "risk_mitigation_attachment",
                    ]
                    attachment_name_field_candidates = [
                        "custom_risk_mitigation_attachment_name",
                        "custom_risk_mitigation_file_name",
                        "custom_risk_mitigation_document_name",
                        "risk_mitigation_attachment_name",
                    ]
                    mitigation_attachment_field = next(
                        (field for field in attachment_field_candidates if plot_meta.has_field(field)),
                        None,
                    )
                    mitigation_attachment_name_field = next(
                        (field for field in attachment_name_field_candidates if plot_meta.has_field(field)),
                        None,
                    )
                    if mitigation_attachment_field:
                        plot_fields.append(mitigation_attachment_field)
                    if mitigation_attachment_name_field:
                        plot_fields.append(mitigation_attachment_name_field)

                    plots = frappe.get_all("Land Plot", 
                        filters={"name": ["in", plot_ids]},
                        fields=plot_fields
                    )
                    if not plots and has_plot_id:
                        plots = frappe.get_all("Land Plot", 
                            filters={"supplier": request.supplier, "plot_id": ["in", plot_ids]},
                            fields=plot_fields
                        )

                    plot_names_for_files = [
                        str(p.get("name") or "").strip()
                        for p in plots
                        if p.get("name")
                    ]
                    fallback_attachment_by_plot = {}
                    if plot_names_for_files:
                        file_rows = frappe.get_all(
                            "File",
                            filters={
                                "attached_to_doctype": "Land Plot",
                                "attached_to_name": ["in", plot_names_for_files],
                            },
                            fields=["name", "attached_to_name", "file_url", "file_name", "creation"],
                            order_by="creation desc",
                            limit_page_length=5000,
                        )
                        for row in file_rows:
                            attached_to_name = str(row.get("attached_to_name") or "").strip()
                            if attached_to_name and attached_to_name not in fallback_attachment_by_plot:
                                fallback_attachment_by_plot[attached_to_name] = row
                    
                    for plot in plots:
                        plot_unique_id = plot["name"]  # Use plot name as unique identifier
                        
                        # Calculate risk level
                        deforestation = plot.get("deforestation_percentage", 0)
                        risk_level = "high" if deforestation > 0 else "low"

                        if plot.get("custom_risk_mitigated"):
                            risk_level = "low"
                        
                        plot_label = plot.get("farmer_name") or plot.get("plot_name") or plot.get("plot_id") or plot.get("name")
                        plot["risk_level"] = risk_level
                        plot["mitigated"] = bool(plot.get("custom_risk_mitigated"))
                        plot["mitigation_note"] = plot.get("custom_risk_mitigation_note")
                        plot["mitigation_on"] = plot.get("custom_risk_mitigation_on")
                        plot["mitigation_by"] = plot.get("custom_risk_mitigation_by")
                        fallback_attachment = fallback_attachment_by_plot.get(str(plot.get("name") or "").strip()) or {}
                        plot_attachment_url = (
                            plot.get(mitigation_attachment_field) if mitigation_attachment_field else ""
                        ) or fallback_attachment.get("file_url") or ""
                        plot_attachment_name = (
                            plot.get(mitigation_attachment_name_field) if mitigation_attachment_name_field else ""
                        ) or fallback_attachment.get("file_name") or ""
                        plot_attachment_docname = fallback_attachment.get("name") or ""
                        plot["mitigation_attachment"] = plot_attachment_url
                        plot["mitigation_attachment_name"] = plot_attachment_name
                        plot["mitigation_attachment_file_name"] = plot_attachment_docname
                        
                        # ✅ DEDUPLICATION LOGIC
                        if plot_unique_id in suppliers_data[supplier_name]["unique_plots"]:
                            # Plot already exists, add this request to the sharing history
                            existing_plot = suppliers_data[supplier_name]["unique_plots"][plot_unique_id]
                            existing_plot["shared_in_requests"].append({
                                "request_id": request.name,
                                "request_date": request.creation,
                                "status": request.status
                            })
                            existing_plot["total_shares"] += 1

                            # Always refresh mitigation & risk flags (independent of request date)
                            existing_plot["risk_level"] = risk_level
                            existing_plot["mitigated"] = plot.get("mitigated")
                            existing_plot["mitigation_note"] = plot.get("mitigation_note")
                            existing_plot["mitigation_on"] = plot.get("mitigation_on")
                            existing_plot["mitigation_by"] = plot.get("mitigation_by")
                            existing_plot["mitigation_attachment"] = plot.get("mitigation_attachment")
                            existing_plot["mitigation_attachment_name"] = plot.get("mitigation_attachment_name")
                            existing_plot["mitigation_attachment_file_name"] = plot.get("mitigation_attachment_file_name")
                            existing_plot["plot_name"] = plot_label

                            # Update with latest data if this request is more recent
                            if request.creation > existing_plot["last_shared_date"]:
                                existing_plot.update({
                                    "plot_id": plot.get("plot_id"),
                                    "country": plot.get("country"),
                                    "area": plot.get("area", 0),
                                    "deforestation_percentage": plot.get("deforestation_percentage", 0),
                                    "deforested_area": plot.get("deforested_area", 0),
                                    "commodities": plot.get("commodities"),
                                    "coordinates": plot.get("coordinates"),
                                    "last_shared_date": request.creation,
                                    "latest_request_id": request.name
                                })
                        else:
                            # New unique plot
                            suppliers_data[supplier_name]["unique_plots"][plot_unique_id] = {
                                "name": plot["name"],
                                "plot_id": plot.get("plot_id"),
                                "plot_name": plot_label,
                                "country": plot.get("country"),
                                "area": plot.get("area", 0),
                                "deforestation_percentage": plot.get("deforestation_percentage", 0),
                                "deforested_area": plot.get("deforested_area", 0),
                                "commodities": plot.get("commodities"),
                                "coordinates": plot.get("coordinates"),
                                "risk_level": risk_level,
                                "mitigated": plot.get("mitigated"),
                                "mitigation_note": plot.get("mitigation_note"),
                                "mitigation_on": plot.get("mitigation_on"),
                                "mitigation_by": plot.get("mitigation_by"),
                                "mitigation_attachment": plot.get("mitigation_attachment"),
                                "mitigation_attachment_name": plot.get("mitigation_attachment_name"),
                                "mitigation_attachment_file_name": plot.get("mitigation_attachment_file_name"),
                                "shared_in_requests": [{
                                    "request_id": request.name,
                                    "request_date": request.creation,
                                    "status": request.status
                                }],
                                "total_shares": 1,
                                "first_shared_date": request.creation,
                                "last_shared_date": request.creation,
                                "latest_request_id": request.name
                            }
                            
            except Exception as e:
                print(f"Error parsing shared plots for request {request.name}: {str(e)}")

            suppliers_data[supplier_name]["requests"].append({
                "id": request.name,
                "status": request.status,
                "creation": request.creation,
                "response_message": request.response_message
            })

        # ✅ Calculate metrics based on UNIQUE plots only
        for supplier_name, data in suppliers_data.items():
            unique_plots_list = list(data["unique_plots"].values())
            data["shared_plots"] = unique_plots_list  # Convert to list for frontend compatibility
            
            total_plots = len(unique_plots_list)
            
            # Reset counters
            data["total_area"] = sum([(plot.get("area") or 0) for plot in unique_plots_list])
            data["total_deforestation"] = 0
            data["high_risk_plots"] = 0
            data["medium_risk_plots"] = 0
            data["low_risk_plots"] = 0
            data["pending_plots"] = 0
            analyzed_plots = []

            # Plot-level analysis status:
            # use cache + persisted field values so status survives cache/server restarts.
            for plot in unique_plots_list:
                plot_name = str(plot.get("name") or "").strip()
                # Use cache-driven analyzed state only; persisted numeric defaults (0/0)
                # must not auto-mark fresh shares as analyzed.
                plot_analysis_required = not plot_name or (plot_name not in analyzed_plot_names)
                plot["analysis_required"] = bool(plot_analysis_required)

                if not plot_analysis_required and plot_name:
                    analyzed_plot_names.add(plot_name)

                if plot_analysis_required:
                    plot["risk_level"] = "not_analyzed"
                    plot["deforestation_percentage"] = None
                    plot["deforested_area"] = None
                    data["pending_plots"] += 1
                    continue

                analyzed_plots.append(plot)
                data["total_deforestation"] += (plot.get("deforested_area") or 0)

                risk_level = (plot.get("risk_level") or "").lower()
                if risk_level == "high":
                    data["high_risk_plots"] += 1
                elif risk_level == "medium":
                    data["medium_risk_plots"] += 1
                elif risk_level == "low":
                    data["low_risk_plots"] += 1

            data["analysis_required"] = data["pending_plots"] > 0
            
            analyzed_count = len(analyzed_plots)
            analyzed_area = sum([(plot.get("area") or 0) for plot in analyzed_plots])

            if analyzed_count > 0:
                # Strict rule: any deforestation/high-risk plot => supplier is high risk.
                if data["high_risk_plots"] > 0:
                    data["overall_risk"] = "high"
                elif data["medium_risk_plots"] > 0:
                    data["overall_risk"] = "medium"
                else:
                    data["overall_risk"] = "low"

                # Calculate compliance score (100 - deforestation impact) using analyzed area
                avg_deforestation = (data["total_deforestation"] / analyzed_area) * 100 if analyzed_area > 0 else 0
                data["compliance_score"] = max(0, min(100, 100 - (avg_deforestation * 2)))
                data["avg_deforestation"] = avg_deforestation

                # Add summary info
                data["total_unique_plots"] = total_plots
                data["total_sharing_instances"] = sum([plot["total_shares"] for plot in unique_plots_list])
                data["analyzed_plots"] = analyzed_count
            else:
                data["overall_risk"] = "unknown"
                data["compliance_score"] = 0
                data["avg_deforestation"] = 0
                data["total_unique_plots"] = total_plots
                data["total_sharing_instances"] = sum([plot["total_shares"] for plot in unique_plots_list])
                data["analyzed_plots"] = 0

            # Remove the dict version, keep only the list for frontend
            del data["unique_plots"]

        # Keep analyzed cache in sync with persisted plot data across restarts.
        _cache_set_json(keys["analyzed"], sorted(analyzed_plot_names))
        # Convert to list
        suppliers_list = list(suppliers_data.values())
        
        # Calculate summary based on unique plots
        summary = {
            "total_suppliers": len(suppliers_list),
            "high_risk": len([s for s in suppliers_list if s.get("overall_risk") == "high"]),
            "medium_risk": len([s for s in suppliers_list if s.get("overall_risk") == "medium"]),
            "low_risk": len([s for s in suppliers_list if s.get("overall_risk") == "low"]),
            "unknown_risk": len([s for s in suppliers_list if s.get("overall_risk") == "unknown"]),
            "total_plots": sum([s.get("total_unique_plots", 0) for s in suppliers_list]),
            "total_sharing_instances": sum([s.get("total_sharing_instances", 0) for s in suppliers_list]),
            "total_area": sum([s["total_area"] for s in suppliers_list]),
            "total_deforestation": sum([s["total_deforestation"] for s in suppliers_list]),
            "avg_compliance": sum([s["compliance_score"] for s in suppliers_list]) / len(suppliers_list) if suppliers_list else 0
        }

        print(f"✅ Risk Dashboard: {summary['total_suppliers']} suppliers, {summary['total_plots']} unique plots, {summary['total_sharing_instances']} sharing instances")
        
        return {"suppliers": suppliers_list, "summary": summary}
        
    except Exception as e:
        print(f"Error in get_risk_dashboard_data: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "get_risk_dashboard_data error")
        return {"suppliers": [], "summary": {}}


def _run_risk_analysis_job(customer: str, pending_names: list[str] | None = None):
    """Background job worker for risk analysis."""
    keys = _risk_cache_keys(customer)
    progress = _normalize_progress_payload(_cache_get_json(keys["progress"], {}))
    progress["status"] = "running"
    progress["started_on"] = progress.get("started_on") or now_datetime().isoformat()
    progress["updated_on"] = now_datetime().isoformat()
    progress["message"] = "Risk analysis in progress"
    _cache_set_json(keys["progress"], progress)

    try:
        from farmportal.api.landplots import calculate_deforestation_data, init_earth_engine
    except Exception:
        frappe.log_error(frappe.get_traceback(), "trigger_risk_analysis import error")
        progress.update({
            "status": "failed",
            "updated_on": now_datetime().isoformat(),
            "message": "Unable to load deforestation engine",
        })
        _cache_set_json(keys["progress"], progress)
        return

    try:
        analyzed_raw = _cache_get_json(keys["analyzed"], []) or []
        cached_analyzed_plot_names = {str(p).strip() for p in analyzed_raw if p}
        persistent_analyzed_plot_names = _load_persistent_analyzed_plot_names(customer)
        analyzed_plot_names = cached_analyzed_plot_names | persistent_analyzed_plot_names

        pending_names = pending_names or _collect_pending_risk_plot_names(customer, analyzed_plot_names)
        if not pending_names:
            progress.update({
                "status": "completed",
                "total": 0,
                "processed": 0,
                "updated": 0,
                "skipped": 0,
                "failed": 0,
                "updated_on": now_datetime().isoformat(),
                "completed_on": now_datetime().isoformat(),
                "message": "No new plots to analyze",
            })
            _cache_set_json(keys["progress"], progress)
            return

        plots = frappe.get_all(
            "Land Plot",
            filters={"name": ["in", list(pending_names)]},
            fields=["name", "plot_id", "coordinates", "area"],
        )

        total = len(plots)
        updated = 0
        skipped = 0
        failed = 0
        failed_plots = []

        progress.update({
            "status": "running",
            "total": total,
            "processed": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "updated_on": now_datetime().isoformat(),
            "message": "Risk analysis in progress",
        })
        _cache_set_json(keys["progress"], progress)

        init_earth_engine()

        for idx, plot in enumerate(plots, start=1):
            coords = plot.get("coordinates")
            if isinstance(coords, str):
                try:
                    coords = json.loads(coords)
                except Exception:
                    coords = None

            if not coords or not isinstance(coords, list):
                skipped += 1
            else:
                try:
                    stats = calculate_deforestation_data(
                        coords,
                        area_ha=plot.get("area"),
                        ensure_init=False,
                    )
                    if not stats:
                        failed += 1
                        if len(failed_plots) < 20:
                            failed_plots.append({"plot": plot.get("name"), "reason": "No stats returned"})
                    else:
                        frappe.db.set_value(
                            "Land Plot",
                            plot.get("name"),
                            {
                                "deforestation_percentage": stats.get("deforestation_percent", 0),
                                "deforested_area": stats.get("loss_area_ha", 0),
                            },
                            update_modified=False,
                        )
                        updated += 1
                        analyzed_plot_names.add(str(plot.get("name")).strip())
                except Exception as e:
                    failed += 1
                    if len(failed_plots) < 20:
                        failed_plots.append({"plot": plot.get("name"), "reason": str(e)})

            # Update progress frequently for frontend polling.
            progress.update({
                "status": "running",
                "total": total,
                "processed": idx,
                "updated": updated,
                "skipped": skipped,
                "failed": failed,
                "updated_on": now_datetime().isoformat(),
                "message": "Risk analysis in progress",
            })
            _cache_set_json(keys["progress"], progress)

        frappe.db.commit()
        frappe.cache().set_value(keys["analysis"], now_datetime().isoformat())
        _cache_set_json(keys["analyzed"], sorted(analyzed_plot_names))
        _save_persistent_analyzed_plot_names(customer, analyzed_plot_names)

        progress.update({
            "status": "completed",
            "total": total,
            "processed": total,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
            "failed_plots": failed_plots,
            "updated_on": now_datetime().isoformat(),
            "completed_on": now_datetime().isoformat(),
            "message": "Risk analysis completed",
        })
        _cache_set_json(keys["progress"], progress)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Risk Analysis Background Job Error")
        progress.update({
            "status": "failed",
            "updated_on": now_datetime().isoformat(),
            "message": f"Risk analysis failed: {str(e)}",
        })
        _cache_set_json(keys["progress"], progress)


@frappe.whitelist()
def get_risk_analysis_progress():
    """Get current risk analysis progress for logged-in customer."""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, _supplier = _get_party_from_user(user)
    if not customer:
        return {"status": "idle", "total": 0, "processed": 0, "percent": 0}

    keys = _risk_cache_keys(customer)
    progress = _normalize_progress_payload(_cache_get_json(keys["progress"], None))
    if not progress:
        return {"status": "idle", "total": 0, "processed": 0, "percent": 0}
    return progress


@frappe.whitelist(methods=["POST"])
def trigger_risk_analysis():
    """Queue risk analysis and return immediately; progress is exposed via polling endpoint."""
    def _is_truthy(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return False

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, _supplier = _get_party_from_user(user)
    if not customer:
        frappe.throw(_("Only Customers can analyze risk"), frappe.PermissionError)

    keys = _risk_cache_keys(customer)
    progress = _normalize_progress_payload(_cache_get_json(keys["progress"], None))

    if progress and progress.get("status") in {"queued", "running"}:
        progress["ok"] = True
        progress["accepted"] = False
        progress["already_running"] = True
        return progress

    form = frappe.form_dict or {}
    force_requested = any(
        _is_truthy(form.get(flag))
        for flag in (
            "force",
            "include_all",
            "reanalyze_all",
            "force_reanalysis",
            "analyze_all",
            "all_plots",
            "full_refresh",
            "refresh_existing",
            "recalculate_all",
        )
    )

    if force_requested:
        _cache_set_json(keys["analyzed"], [])
        _save_persistent_analyzed_plot_names(customer, set())
        analyzed_plot_names = set()
    else:
        analyzed_raw = _cache_get_json(keys["analyzed"], []) or []
        cached_analyzed_plot_names = {str(p).strip() for p in analyzed_raw if p}
        persistent_analyzed_plot_names = _load_persistent_analyzed_plot_names(customer)
        analyzed_plot_names = cached_analyzed_plot_names | persistent_analyzed_plot_names
        if persistent_analyzed_plot_names and not cached_analyzed_plot_names:
            _cache_set_json(keys["analyzed"], sorted(analyzed_plot_names))
        if cached_analyzed_plot_names and not persistent_analyzed_plot_names:
            _save_persistent_analyzed_plot_names(customer, analyzed_plot_names)
    pending_names = _collect_pending_risk_plot_names(customer, analyzed_plot_names)

    if not pending_names:
        done_payload = {
            "status": "completed",
            "total": 0,
            "processed": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "message": "No new plots to analyze",
            "updated_on": now_datetime().isoformat(),
            "completed_on": now_datetime().isoformat(),
        }
        _cache_set_json(keys["progress"], done_payload)
        out = _normalize_progress_payload(done_payload)
        out["ok"] = True
        out["accepted"] = False
        return out

    queued_payload = {
        "status": "queued",
        "total": len(pending_names),
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "message": "Risk analysis queued",
        "started_on": now_datetime().isoformat(),
        "updated_on": now_datetime().isoformat(),
    }
    _cache_set_json(keys["progress"], queued_payload)

    job = frappe.enqueue(
        "farmportal.api.requests._run_risk_analysis_job",
        queue="long",
        timeout=60 * 60,
        enqueue_after_commit=True,
        customer=customer,
        pending_names=pending_names,
    )

    response = _normalize_progress_payload(queued_payload)
    response.update({
        "ok": True,
        "accepted": True,
        "job_id": getattr(job, "id", None),
        "message": "Risk analysis started",
    })
    return response



@frappe.whitelist(methods=["POST"])
def submit_risk_mitigation(
    plot_name: str,
    note: str | None = None,
    attachment_url: str | None = None,
    attachment_name: str | None = None
):
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier_link = _get_party_from_user(user)
    if not customer:
        frappe.throw(_("Only Customers can submit mitigation"), frappe.PermissionError)

    if not plot_name:
        frappe.throw(_("plot_name is required"))

    if not frappe.db.exists("Land Plot", plot_name):
        frappe.throw(_("Land Plot not found"))

    frappe.get_doc("Land Plot", plot_name)

    # Ensure this customer has a request that includes this plot
    requests_with_plots = frappe.db.sql(
        """
        SELECT r.name, r.supplier, r.shared_plots_json, r.purchase_order_data
        FROM `tabRequest` r
        WHERE r.customer = %s
        AND (
            (r.shared_plots_json IS NOT NULL AND r.shared_plots_json != '')
            OR (r.purchase_order_data IS NOT NULL AND r.purchase_order_data != '')
        )
        """,
        (customer,),
        as_dict=True
    )

    allowed = False
    for req in requests_with_plots:
        plot_ids = _parse_request_plot_ids(req)
        if not plot_ids:
            continue
        valid_plot_names = _resolve_supplier_plot_names(req.get("supplier"), plot_ids)
        if plot_name in valid_plot_names:
            allowed = True
            break

    if not allowed:
        frappe.throw(_("You are not allowed to mitigate this plot"), frappe.PermissionError)

    meta = frappe.get_meta("Land Plot")
    required_fields = [
        "custom_risk_mitigated",
        "custom_risk_mitigation_note",
        "custom_risk_mitigation_on",
        "custom_risk_mitigation_by",
    ]
    missing = [f for f in required_fields if not meta.has_field(f)]
    if missing:
        frappe.throw(_("Missing Land Plot fields: {0}. Please create these custom fields first.").format(", ".join(missing)))

    attachment_field_candidates = [
        "custom_risk_mitigation_attachment",
        "custom_risk_mitigation_file",
        "custom_risk_mitigation_document",
        "risk_mitigation_attachment",
    ]
    attachment_name_field_candidates = [
        "custom_risk_mitigation_attachment_name",
        "custom_risk_mitigation_file_name",
        "custom_risk_mitigation_document_name",
        "risk_mitigation_attachment_name",
    ]
    mitigation_attachment_field = next(
        (field for field in attachment_field_candidates if meta.has_field(field)),
        None,
    )
    mitigation_attachment_name_field = next(
        (field for field in attachment_name_field_candidates if meta.has_field(field)),
        None,
    )

    doc = frappe.get_doc("Land Plot", plot_name)
    doc.set("custom_risk_mitigated", 1)
    doc.set("custom_risk_mitigation_note", note or "")
    doc.set("custom_risk_mitigation_on", now_datetime())
    doc.set("custom_risk_mitigation_by", user)
    if mitigation_attachment_field and attachment_url is not None:
        doc.set(mitigation_attachment_field, attachment_url or "")
    if mitigation_attachment_name_field and attachment_name is not None:
        doc.set(mitigation_attachment_name_field, attachment_name or "")
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {"ok": True, "plot_name": plot_name}


# Add to your requests.py file

@frappe.whitelist()
def download_request_attachment(request_id, file_url=None, file_name=None):
    """Download a Request attachment for the Request's customer or supplier."""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    request_doc = frappe.get_doc("Request", request_id)

    def _resolve_linked_names(target_doctype: str) -> set[str]:
        names = set()

        direct = _link_by_user_field(target_doctype, user)
        if direct:
            names.add(str(direct).strip())

        email = _get_user_email(user)
        if not email:
            return {n for n in names if n}

        contacts = frappe.get_all("Contact Email", filters={"email_id": email}, fields=["parent"])
        contact_names = [c.get("parent") for c in contacts if c.get("parent")]
        if not contact_names:
            return {n for n in names if n}

        links = frappe.get_all(
            "Dynamic Link",
            filters={
                "parenttype": "Contact",
                "parent": ["in", contact_names],
                "link_doctype": target_doctype,
            },
            fields=["link_name"],
            limit_page_length=500,
        )

        for row in links:
            link_name = str(row.get("link_name") or "").strip()
            if link_name:
                names.add(link_name)

        return names

    customer_names = _resolve_linked_names("Customer")
    supplier_names = _resolve_linked_names("Supplier")

    request_customer = str(request_doc.customer or "").strip()
    request_supplier = str(request_doc.supplier or "").strip()

    is_customer_owner = bool(request_customer and request_customer in customer_names)
    is_supplier_owner = bool(request_supplier and request_supplier in supplier_names)
    is_admin_reader = frappe.has_permission("Request", "read", doc=request_doc)

    if not (is_customer_owner or is_supplier_owner or is_admin_reader):
        frappe.throw(_("Not permitted to download this attachment"), frappe.PermissionError)

    filters = {
        "attached_to_doctype": "Request",
        "attached_to_name": request_id,
    }
    if file_name:
        filters["name"] = file_name
    elif file_url:
        filters["file_url"] = file_url
    else:
        frappe.throw(_("file_url or file_name is required"))

    file_rows = frappe.get_all(
        "File",
        filters=filters,
        fields=["name", "file_name"],
        limit=1,
    )
    if not file_rows:
        frappe.throw(_("Attachment not found"), frappe.DoesNotExistError)

    file_doc = frappe.get_doc("File", file_rows[0]["name"])
    frappe.local.response.filename = file_rows[0].get("file_name") or file_doc.file_name or file_doc.name
    frappe.local.response.filecontent = file_doc.get_content()
    frappe.local.response.type = "download"


@frappe.whitelist()
def download_risk_mitigation_attachment(plot_name, file_url=None, file_name=None):
    """Download a mitigation attachment for a Land Plot shared with the logged-in customer."""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier_link = _get_party_from_user(user)
    if not customer:
        frappe.throw(_("Only Customers can download mitigation attachments"), frappe.PermissionError)

    if not plot_name:
        frappe.throw(_("plot_name is required"))

    if not frappe.db.exists("Land Plot", plot_name):
        frappe.throw(_("Land Plot not found"))

    frappe.get_doc("Land Plot", plot_name)

    requests_with_plots = frappe.db.sql(
        """
        SELECT r.name, r.supplier, r.shared_plots_json, r.purchase_order_data
        FROM `tabRequest` r
        WHERE r.customer = %s
        AND (
            (r.shared_plots_json IS NOT NULL AND r.shared_plots_json != '')
            OR (r.purchase_order_data IS NOT NULL AND r.purchase_order_data != '')
        )
        """,
        (customer,),
        as_dict=True,
    )

    allowed = False
    for req in requests_with_plots:
        plot_ids = _parse_request_plot_ids(req)
        if not plot_ids:
            continue
        valid_plot_names = _resolve_supplier_plot_names(req.get("supplier"), plot_ids)
        if plot_name in valid_plot_names:
            allowed = True
            break

    if not allowed:
        frappe.throw(_("You are not allowed to download this mitigation attachment"), frappe.PermissionError)

    filters = {
        "attached_to_doctype": "Land Plot",
        "attached_to_name": plot_name,
    }

    if file_name:
        filters["name"] = file_name
    elif file_url:
        normalized_url = str(file_url).strip()
        if normalized_url.startswith(("http://", "https://")):
            parsed = urlparse(normalized_url)
            normalized_url = parsed.path or normalized_url
        filters["file_url"] = normalized_url

    file_rows = frappe.get_all(
        "File",
        filters=filters,
        fields=["name", "file_name"],
        order_by="creation desc",
        limit=1,
    )
    if not file_rows:
        frappe.throw(_("Attachment not found"), frappe.DoesNotExistError)

    file_doc = frappe.get_doc("File", file_rows[0]["name"])
    frappe.local.response.filename = file_rows[0].get("file_name") or file_doc.file_name or file_doc.name
    frappe.local.response.filecontent = file_doc.get_content()
    frappe.local.response.type = "download"


@frappe.whitelist()
def get_purchase_order_details(request_id):
    """Get purchase order details for supplier response"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    try:
        customer, supplier = _get_party_from_user(user)
        if not supplier:
            frappe.throw(_("Only Suppliers can access PO details"), frappe.PermissionError)
        _require_supplier_request_permission(user, supplier, request_type="purchase_order")

        # Get the request details
        request_doc = frappe.get_doc("Request", request_id)
        if request_doc.supplier != supplier:
            frappe.throw(_("Not authorized for this request"), frappe.PermissionError)

        # Get purchase order number from request message or additional fields
        po_number = request_doc.get("purchase_order_number") or "N/A"

        # Get supplier's existing data
        plot_meta = frappe.get_meta("Land Plot")
        has_plot_id = plot_meta.has_field("plot_id")
        name_field = "farmer_name" if plot_meta.has_field("farmer_name") else ("plot_name" if plot_meta.has_field("plot_name") else None)

        fields = [
            "name as id",
            "area",
            "country",
            "commodities"
        ]
        if has_plot_id:
            fields.insert(1, "plot_id")
        if name_field:
            fields.insert(2 if has_plot_id else 1, f"{name_field} as plot_name")

        plots = frappe.get_all(
            "Land Plot",
            filters={"supplier": supplier},
            fields=fields
        )
        items = frappe.get_all(
            "Item",
            filters={"item_group": "EUDR Commodities", "disabled": 0},
            fields=["name", "item_name", "item_group"],
            order_by="item_name asc"
        )

        products = [
            {"id": i.name, "name": i.item_name or i.name, "category": i.item_group}
            for i in items
        ]

        request_message = (request_doc.get("message") or "").strip()

        attachments = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Request",
                "attached_to_name": request_id,
            },
            fields=["name", "file_name", "file_url", "is_private", "creation"],
            order_by="creation asc"
        )

        for att in attachments:
            url = att.get("file_url")
            if url and not str(url).startswith(("http://", "https://")):
                att["absolute_url"] = frappe.utils.get_url(url)
            else:
                att["absolute_url"] = url

        purchase_order_attachment = attachments[0] if attachments else None

        return {
            "request_id": request_id,
            "purchase_order_number": po_number,
            "supplier": supplier,
            "customer": request_doc.customer,
            "request_message": request_message,
            "purchase_order_attachment": purchase_order_attachment,
            "attachments": attachments,
            "plots": plots,
            "products": products,
            "existing_batches": []  # Can be populated from a Batch doctype if exists
        }

    except Exception as e:
        print(f"Error in get_purchase_order_details: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "get_purchase_order_details error")
        return {"error": str(e)}


@frappe.whitelist()
def submit_purchase_order_data(request_id, po_data):
    """Submit comprehensive purchase order data"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    try:
        customer, supplier = _get_party_from_user(user)
        if not supplier:
            frappe.throw(_("Only Suppliers can submit PO data"), frappe.PermissionError)
        _require_supplier_permission(
            user,
            SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER,
            supplier_hint=supplier,
            message=_("You are not allowed to manage purchase orders"),
        )

        # Parse the PO data
        if isinstance(po_data, str):
            po_data = json.loads(po_data)

        print(f"📦 Received PO data: {po_data}")

        # Update the request with PO response
        request_doc = frappe.get_doc("Request", request_id)
        if request_doc.supplier != supplier:
            frappe.throw(_("Not authorized"), frappe.PermissionError)

        # Store PO data as JSON in response_data field (add this field to Request doctype)
        request_doc.status = "Accepted"
        request_doc.response_message = f"Purchase order data submitted with {len(po_data.get('batches', []))} batches"
        
        # Store comprehensive PO data
        request_doc.purchase_order_data = json.dumps(po_data)
        
        request_doc.responded_by = user
        request_doc.save(ignore_permissions=True)

        # Create Batch records for selected products (if provided)
        try:
            batches = po_data.get("batches") or []
            product_ids = po_data.get("products") or []

            for batch in batches:
                batch_no = batch.get("batchNumber") or batch.get("batch_id")
                expiry_date = batch.get("validityDate") or batch.get("expiry_date")
                manufacturing_date = batch.get("manufacturingDate") or batch.get("manufacturing_date")

                if not batch_no:
                    continue

                for product_id in product_ids:
                    if not product_id:
                        continue

                    # Resolve Item name (Batch.item links to Item.name)
                    item_name = product_id
                    if not frappe.db.exists("Item", item_name):
                        item_name = frappe.db.get_value("Item", {"item_code": product_id}, "name") or item_name

                    if not frappe.db.exists("Item", item_name):
                        continue

                    # Ensure item allows batch tracking (ERPNext validation)
                    has_batch = frappe.db.get_value("Item", item_name, "has_batch_no")
                    if has_batch in (0, "0", None):
                        frappe.db.set_value("Item", item_name, "has_batch_no", 1, update_modified=False)

                    target_batch_id = batch_no
                    existing_item = frappe.db.get_value("Batch", {"batch_id": target_batch_id}, "item")

                    if existing_item and existing_item != item_name:
                        target_batch_id = f"{batch_no}-{item_name}"

                    if frappe.db.exists("Batch", {"batch_id": target_batch_id}):
                        continue

                    batch_doc = frappe.get_doc({
                        "doctype": "Batch",
                        "item": item_name,
                        "batch_id": target_batch_id,
                        "expiry_date": expiry_date,
                        "manufacturing_date": manufacturing_date,
                    })
                    batch_doc.insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "PO Batch Create Error")

        frappe.db.commit()

        return {
            "message": "Purchase order data submitted successfully",
            "status": "Accepted",
            "batches_count": len(po_data.get('batches', [])),
            "plots_count": len(po_data.get('selected_plots', [])),
            "products_count": len(po_data.get('products', []))
        }

    except Exception as e:
        print(f"Error in submit_purchase_order_data: {str(e)}")
        frappe.throw(_("Failed to submit PO data"))


@frappe.whitelist()
def get_purchase_order_response(request_id):
    """Get detailed purchase order response data for customers"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    try:
        customer, supplier = _get_party_from_user(user)
        
        # Get the request
        request_doc = frappe.get_doc("Request", request_id)
        
        # Check permissions - customer or supplier can view
        if request_doc.customer == customer:
            _require_customer_request_permission(user, customer, request_type="purchase_order")
        elif request_doc.supplier == supplier:
            _require_supplier_request_permission(user, supplier, request_type="purchase_order")
        else:
            frappe.throw(_("Not authorized to view this request"), frappe.PermissionError)

        if request_doc.request_type != "purchase_order":
            frappe.throw(_("This is not a purchase order request"))

        if not request_doc.get("purchase_order_data"):
            return {
                "request": {
                    "id": request_doc.name,
                    "purchase_order_number": request_doc.get("purchase_order_number") or "N/A",
                    "status": request_doc.status,
                    "supplier": request_doc.supplier,
                    "customer": request_doc.customer
                },
                "data": None,
                "message": "Purchase order data not yet submitted by supplier"
            }

        # Parse the stored JSON data
        try:
            po_data = json.loads(request_doc.purchase_order_data)
        except Exception as e:
            print(f"Error parsing PO data: {str(e)}")
            frappe.throw(_("Error reading purchase order data"))

        # Get detailed plot information
        detailed_plots = []
        if po_data.get("selected_plots"):
            plot_ids = po_data.get("selected_plots") or []
            plot_meta = frappe.get_meta("Land Plot")
            has_plot_id = plot_meta.has_field("plot_id")
            name_field = "farmer_name" if plot_meta.has_field("farmer_name") else ("plot_name" if plot_meta.has_field("plot_name") else None)
            attachment_field_candidates = [
                "custom_risk_mitigation_attachment",
                "custom_risk_mitigation_file",
                "custom_risk_mitigation_document",
                "risk_mitigation_attachment",
            ]
            attachment_name_field_candidates = [
                "custom_risk_mitigation_attachment_name",
                "custom_risk_mitigation_file_name",
                "custom_risk_mitigation_document_name",
                "risk_mitigation_attachment_name",
            ]
            mitigation_attachment_field = next(
                (field for field in attachment_field_candidates if plot_meta.has_field(field)),
                None,
            )
            mitigation_attachment_name_field = next(
                (field for field in attachment_name_field_candidates if plot_meta.has_field(field)),
                None,
            )

            fields = [
                "name as id",
                "country",
                "area",
                "coordinates",
                "commodities",
                "deforestation_percentage",
                "deforested_area",
                "supplier"
            ]
            if has_plot_id:
                fields.insert(1, "plot_id")
            if name_field:
                fields.insert(2 if has_plot_id else 1, f"{name_field} as plot_name")
            if plot_meta.has_field("custom_risk_mitigated"):
                fields.append("custom_risk_mitigated")
            if plot_meta.has_field("custom_risk_mitigation_note"):
                fields.append("custom_risk_mitigation_note")
            if mitigation_attachment_field:
                fields.append(mitigation_attachment_field)
            if mitigation_attachment_name_field:
                fields.append(mitigation_attachment_name_field)

            plots = frappe.get_all(
                "Land Plot",
                filters={"name": ["in", plot_ids]},
                fields=fields
            )
            if not plots and has_plot_id:
                plots = frappe.get_all(
                    "Land Plot",
                    filters={"supplier": request_doc.supplier, "plot_id": ["in", plot_ids]},
                    fields=fields
                )

            plot_names_for_files = [
                str(p.get("id") or "").strip()
                for p in plots
                if p.get("id")
            ]
            fallback_attachment_by_plot = {}
            if plot_names_for_files:
                file_rows = frappe.get_all(
                    "File",
                    filters={
                        "attached_to_doctype": "Land Plot",
                        "attached_to_name": ["in", plot_names_for_files],
                    },
                    fields=["name", "attached_to_name", "file_url", "file_name", "creation"],
                    order_by="creation desc",
                    limit_page_length=5000,
                )
                for row in file_rows:
                    attached_to_name = str(row.get("attached_to_name") or "").strip()
                    if attached_to_name and attached_to_name not in fallback_attachment_by_plot:
                        fallback_attachment_by_plot[attached_to_name] = row

            for plot in plots:
                plot["mitigated"] = bool(plot.get("custom_risk_mitigated"))
                fallback_attachment = fallback_attachment_by_plot.get(str(plot.get("id") or "").strip()) or {}
                plot_attachment_url = (
                    plot.get(mitigation_attachment_field) if mitigation_attachment_field else ""
                ) or fallback_attachment.get("file_url") or ""
                plot_attachment_name = (
                    plot.get(mitigation_attachment_name_field) if mitigation_attachment_name_field else ""
                ) or fallback_attachment.get("file_name") or ""
                plot_attachment_docname = fallback_attachment.get("name") or ""
                plot["mitigation_attachment"] = plot_attachment_url
                plot["mitigation_attachment_name"] = plot_attachment_name
                plot["mitigation_attachment_file_name"] = plot_attachment_docname
            detailed_plots = plots

        request_attachments = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Request",
                "attached_to_name": request_id,
            },
            fields=["name", "file_name", "file_url", "is_private", "creation"],
            order_by="creation asc",
        )

        # Get detailed product information  
        detailed_products = []
        if po_data.get("products"):
            product_ids = po_data["products"]
            items = frappe.get_all(
                "Item",
                filters={"name": ["in", product_ids]},
                fields=["name", "item_name", "item_group"]
            )
            item_map = {i.name: i for i in items}
            detailed_products = [
                {"id": pid, "name": item_map[pid].item_name or pid, "category": item_map[pid].item_group}
                for pid in product_ids if pid in item_map
            ]

        # Calculate summary statistics
        total_plots = len(detailed_plots)
        total_area = sum([plot.get("area", 0) for plot in detailed_plots])
        total_batches = len(po_data.get("batches", []))
        total_products = len(detailed_products)
        
        # EUDR compliance summary
        eudr_relevant_batches = len([b for b in po_data.get("batches", []) if b.get("eudrRelevant", True)])
        high_risk_plots = len([p for p in detailed_plots if p.get("deforestation_percentage", 0) > 0])

        response_data = {
            "request": {
                "id": request_doc.name,
                "purchase_order_number": request_doc.get("purchase_order_number") or "N/A",
                "status": request_doc.status,
                "supplier": request_doc.supplier,
                "customer": request_doc.customer,
                "creation": request_doc.creation,
                "response_message": request_doc.response_message
            },
            "data": {
                "batches": po_data.get("batches", []),
                "plots": detailed_plots,
                "production_dates": po_data.get("production_dates", []),
                "production_date_scope": po_data.get("production_date_scope", "per_plot"),
                "products": detailed_products
            },
            "request_attachments": request_attachments,
            "summary": {
                "total_batches": total_batches,
                "total_plots": total_plots,
                "total_area": total_area,
                "total_products": total_products,
                "eudr_relevant_batches": eudr_relevant_batches,
                "high_risk_plots": high_risk_plots,
                "compliance_rate": (eudr_relevant_batches / total_batches * 100) if total_batches > 0 else 0
            }
        }

        return response_data

    except Exception as e:
        print(f"Error in get_purchase_order_response: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "get_purchase_order_response error")
        frappe.throw(_("Failed to retrieve purchase order data"))

@frappe.whitelist()
def get_customer_purchase_order_plots(request_id):
    """Get purchase order plots that customers are allowed to view"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    try:
        customer, supplier = _get_party_from_user(user)
        
        # Get the request
        request_doc = frappe.get_doc("Request", request_id)
        
        # Only the customer of this request can view
        if request_doc.customer != customer:
            frappe.throw(_("Not authorized to view this request"), frappe.PermissionError)
        _require_customer_request_permission(user, customer, request_type="purchase_order")

        if request_doc.request_type != "purchase_order":
            frappe.throw(_("This is not a purchase order request"))

        if request_doc.status != "Accepted":
            return {"plots": [], "message": "Purchase order not yet accepted by supplier"}

        if not request_doc.get("purchase_order_data"):
            return {"plots": [], "message": "Purchase order data not yet submitted"}

        # Parse PO data to get shared plot IDs
        try:
            po_data = json.loads(request_doc.purchase_order_data)
            raw_plot_refs = (
                po_data.get("selected_plots")
                or po_data.get("selectedPlots")
                or po_data.get("plots")
                or []
            )
            plot_ids = _coerce_plot_refs(raw_plot_refs)
        except:
            return {"plots": [], "message": "Error reading purchase order data"}

        if not plot_ids:
            return {"plots": [], "message": "No plots shared in this purchase order"}

        # Enforce supplier boundary to prevent cross-supplier plot leakage.
        valid_plot_names = _resolve_supplier_plot_names(request_doc.supplier, plot_ids)
        if not valid_plot_names:
            return {"plots": [], "message": "No valid supplier-owned plots shared in this purchase order"}

        # Get the plot details that were shared with this customer
        plot_meta = frappe.get_meta("Land Plot")
        has_plot_id = plot_meta.has_field("plot_id")
        name_field = "farmer_name" if plot_meta.has_field("farmer_name") else ("plot_name" if plot_meta.has_field("plot_name") else None)

        fields = [
            "name as id",
            "country",
            "area",
            "coordinates",
            "commodities",
            "deforestation_percentage",
            "deforested_area"
        ]
        if has_plot_id:
            fields.insert(1, "plot_id")
        if name_field:
            fields.insert(2 if has_plot_id else 1, f"{name_field} as plot_name")

        plots = frappe.get_all(
            "Land Plot",
            filters={
                "supplier": request_doc.supplier,
                "name": ["in", valid_plot_names],
            },
            fields=fields
        )

        # Process commodities
        for plot in plots:
            if plot.get("commodities") and isinstance(plot["commodities"], str):
                try:
                    plot["commodities"] = json.loads(plot["commodities"])
                except:
                    plot["commodities"] = plot["commodities"].split(",") if plot["commodities"] else []
            elif not plot.get("commodities"):
                plot["commodities"] = []

        return {
            "plots": plots,
            "request": {
                "id": request_doc.name,
                "purchase_order_number": request_doc.get("purchase_order_number"),
                "supplier": request_doc.supplier,
                "status": request_doc.status
            }
        }

    except Exception as e:
        print(f"Error in get_customer_purchase_order_plots: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "get_customer_purchase_order_plots error")
        return {"plots": [], "message": "Failed to load plot data"}
