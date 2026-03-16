# apps/farmportal/farmportal/api/requests.py

import json
import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime

DT = "Request"

# NEW: preferred user link fields per doctype (ordered by priority)
USER_LINK_FIELDS = {
    "Customer": ["custom_user", "user_id", "user"],
    "Supplier": ["custom_user", "user_id", "user"],
}

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
def get_customer_requests():
    """Get all requests for the current customer"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)
    
    try:
        customer, supplier = _get_party_from_user(user)
        if not customer:
            frappe.throw(_("Customer not found for this user"), frappe.PermissionError)
        
        print(f"🔍 Getting requests for customer: {customer}")
        
        # Get requests for this customer with PO number
        requests = frappe.get_all("Request", 
            filters={"customer": customer},
            fields=[
                "name", "customer", "supplier", "request_type", "status", 
                "creation", "response_message", "shared_plots_json", 
                "message", "requested_by", "responded_by",
                "purchase_order_number"  # ✅ Add this field
            ],
            order_by="creation desc"
        )
        
        print(f"📊 Found {len(requests)} requests for customer {customer}")
        
        return {"requests": requests}
        
    except Exception as e:
        print(f"Error in get_customer_requests: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "get_customer_requests error")
        return {"requests": []}


@frappe.whitelist()
def get_supplier_requests():
    """Get all requests for the current supplier"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)
    
    try:
        customer, supplier = _get_party_from_user(user)
        if not supplier:
            frappe.throw(_("Supplier not found for this user"), frappe.PermissionError)
        
        print(f"🔍 Getting requests for supplier: {supplier}")
        
        # Get requests for this supplier with PO number
        requests = frappe.get_all("Request", 
            filters={"supplier": supplier},
            fields=[
                "name", "customer", "supplier", "request_type", "status", 
                "creation", "response_message", "shared_plots_json", 
                "message", "requested_by", "responded_by",
                "purchase_order_number"  # ✅ Add this field
            ],
            order_by="creation desc"
        )
        
        print(f"📊 Found {len(requests)} requests for supplier {supplier}")
        
        return {"requests": requests}
        
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

        # Create the request document
        doc = frappe.new_doc("Request")
        doc.customer = customer_id or customer  # Allow override for admin
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
    land_plots = _count_if_exists("Land Plot", filters)
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

        # Get the actual land plot data
        plots = []
        if plot_ids:
            if isinstance(plot_ids, str):
                plot_ids = [plot_ids]

            plot_meta = frappe.get_meta("Land Plot")
            has_plot_id = plot_meta.has_field("plot_id")
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
            if plot_meta.has_field("plot_name"):
                fields.append("plot_name")
            if plot_meta.has_field("farmer_name"):
                fields.append("farmer_name")

            plots = frappe.get_all(
                "Land Plot",
                filters={"name": ["in", plot_ids]},
                fields=fields
            )

            # Fallback: if stored IDs are plot_id instead of doc name
            if not plots and has_plot_id:
                plots = frappe.get_all(
                    "Land Plot",
                    filters={"plot_id": ["in", plot_ids]},
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
    
    # FIRST - ALWAYS print this to confirm function is called
    print(f"🚨 RESPOND_TO_REQUEST CALLED: {request_id}")
    print(f"🚨 ALL PARAMS: request_id={request_id}, action={action}, message={message}, shared_plots={shared_plots}, status={status}")
    
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can respond"), frappe.PermissionError)

    doc = frappe.get_doc("Request", request_id)

    if doc.supplier != supplier:
        frappe.throw(_("Not permitted to respond to this request"), frappe.PermissionError)

    # Simple status update
    if action == "accept":
        doc.status = "Accepted"
    elif action == "reject":
        doc.status = "Rejected"

    if message:
        doc.response_message = message

    # SIMPLE shared plots handling
    if shared_plots:
        print(f"🔥 SHARED PLOTS RECEIVED: {shared_plots}")
        print(f"🔥 TYPE: {type(shared_plots)}")

        plots_list = None
        if isinstance(shared_plots, list):
            plots_list = shared_plots
        elif isinstance(shared_plots, str):
            try:
                plots_list = json.loads(shared_plots)
            except Exception:
                try:
                    import ast
                    plots_list = ast.literal_eval(shared_plots)
                except Exception:
                    plots_list = [shared_plots]
        else:
            plots_list = [shared_plots]

        if isinstance(plots_list, str):
            plots_list = [plots_list]
        if not isinstance(plots_list, list):
            plots_list = [plots_list]

        plots_json = json.dumps(plots_list)
        doc.shared_plots_json = plots_json
        print(f"🔥 SETTING shared_plots_json TO: {plots_json}")
    else:
        print(f"🔥 NO SHARED PLOTS RECEIVED")

    doc.responded_by = user
    
    print(f"🔥 SAVING DOCUMENT...")
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    print(f"🔥 DOCUMENT SAVED!")

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

        # Risk analysis state: keep a per-customer set of already analyzed plot names.
        analyzed_plots_cache_key = f"risk_analyzed_plots::{customer}"
        analyzed_plots_raw = frappe.cache().get_value(analyzed_plots_cache_key)
        analyzed_plot_names = set()
        if analyzed_plots_raw:
            try:
                parsed = json.loads(analyzed_plots_raw) if isinstance(analyzed_plots_raw, str) else analyzed_plots_raw
                if isinstance(parsed, list):
                    analyzed_plot_names = {str(p).strip() for p in parsed if p}
            except Exception:
                analyzed_plot_names = set()

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

                    plots = frappe.get_all("Land Plot", 
                        filters={"name": ["in", plot_ids]},
                        fields=plot_fields
                    )
                    if not plots and has_plot_id:
                        plots = frappe.get_all("Land Plot", 
                            filters={"plot_id": ["in", plot_ids]},
                            fields=plot_fields
                        )
                    
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
            # keep already analyzed plots visible, and mark only new plot names as pending.
            for plot in unique_plots_list:
                plot_name = str(plot.get("name") or "").strip()
                plot_analysis_required = not plot_name or plot_name not in analyzed_plot_names
                plot["analysis_required"] = bool(plot_analysis_required)

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


@frappe.whitelist(methods=["POST"])
def trigger_risk_analysis():
    """Recalculate deforestation metrics for plots shared with the current customer."""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, _supplier = _get_party_from_user(user)
    if not customer:
        frappe.throw(_("Only Customers can analyze risk"), frappe.PermissionError)

    analysis_cache_key = f"risk_analysis_completed_on::{customer}"
    analyzed_plots_cache_key = f"risk_analyzed_plots::{customer}"
    analyzed_plots_raw = frappe.cache().get_value(analyzed_plots_cache_key)
    analyzed_plot_names = set()
    if analyzed_plots_raw:
        try:
            parsed = json.loads(analyzed_plots_raw) if isinstance(analyzed_plots_raw, str) else analyzed_plots_raw
            if isinstance(parsed, list):
                analyzed_plot_names = {str(p).strip() for p in parsed if p}
        except Exception:
            analyzed_plot_names = set()

    try:
        from farmportal.api.landplots import calculate_deforestation_data, init_earth_engine
    except Exception:
        frappe.log_error(frappe.get_traceback(), "trigger_risk_analysis import error")
        frappe.throw(_("Unable to load deforestation engine"))

    query = """
        SELECT r.name, r.shared_plots_json, r.purchase_order_data
        FROM `tabRequest` r
        WHERE r.customer = %s
        AND (
            (r.shared_plots_json IS NOT NULL AND r.shared_plots_json != '')
            OR (r.purchase_order_data IS NOT NULL AND r.purchase_order_data != '')
        )
    """
    requests_with_plots = frappe.db.sql(query, (customer,), as_dict=True)

    plot_ids = []
    for req in requests_with_plots:
        try:
            if req.shared_plots_json:
                parsed = json.loads(req.shared_plots_json) if isinstance(req.shared_plots_json, str) else req.shared_plots_json
                if isinstance(parsed, list):
                    plot_ids.extend(parsed)
                elif parsed:
                    plot_ids.append(parsed)
        except Exception:
            pass

        if req.purchase_order_data:
            try:
                po_data = json.loads(req.purchase_order_data) if isinstance(req.purchase_order_data, str) else req.purchase_order_data
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

    normalized_ids = []
    seen = set()
    for pid in plot_ids:
        key = str(pid).strip()
        if key and key not in seen:
            seen.add(key)
            normalized_ids.append(key)

    if not normalized_ids:
        return {
            "ok": True,
            "message": "No new shared plots to analyze",
            "total": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0
        }

    plot_meta = frappe.get_meta("Land Plot")
    has_plot_id = plot_meta.has_field("plot_id")

    matched_names = set()
    by_name = frappe.get_all(
        "Land Plot",
        filters={"name": ["in", normalized_ids]},
        fields=["name"]
    )
    matched_names.update([p.name for p in by_name])

    unresolved_ids = [pid for pid in normalized_ids if pid not in matched_names]
    if has_plot_id and unresolved_ids:
        by_plot_id = frappe.get_all(
            "Land Plot",
            filters={"plot_id": ["in", unresolved_ids]},
            fields=["name"]
        )
        matched_names.update([p.name for p in by_plot_id])

    if not matched_names:
        return {
            "ok": True,
            "message": "No matching Land Plots found",
            "total": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0
        }

    pending_names = [name for name in matched_names if name not in analyzed_plot_names]
    if not pending_names:
        return {
            "ok": True,
            "message": "No new plots to analyze",
            "total": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0
        }

    plots = frappe.get_all(
        "Land Plot",
        filters={"name": ["in", list(pending_names)]},
        fields=["name", "plot_id", "coordinates"]
    )

    init_earth_engine()

    updated = 0
    skipped = 0
    failed = []

    for plot in plots:
        coords = plot.get("coordinates")
        if isinstance(coords, str):
            try:
                coords = json.loads(coords)
            except Exception:
                coords = None

        if not coords or not isinstance(coords, list):
            skipped += 1
            continue

        try:
            stats = calculate_deforestation_data(coords)
            if not stats:
                failed.append({"plot": plot.get("name"), "reason": "No stats returned"})
                continue

            doc = frappe.get_doc("Land Plot", plot.get("name"))
            doc.set("deforestation_percentage", stats.get("deforestation_percent", 0))
            doc.set("deforested_area", stats.get("loss_area_ha", 0))
            doc.save(ignore_permissions=True)
            updated += 1
            analyzed_plot_names.add(str(plot.get("name")).strip())
        except Exception as e:
            failed.append({"plot": plot.get("name"), "reason": str(e)})

    frappe.db.commit()
    frappe.cache().set_value(analysis_cache_key, now_datetime().isoformat())
    frappe.cache().set_value(analyzed_plots_cache_key, json.dumps(sorted(analyzed_plot_names)))

    return {
        "ok": True,
        "message": "Risk analysis completed",
        "total": len(plots),
        "updated": updated,
        "skipped": skipped,
        "failed": len(failed),
        "failed_plots": failed[:20]
    }



@frappe.whitelist(methods=["POST"])
def submit_risk_mitigation(plot_name: str, note: str | None = None):
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

    plot_doc = frappe.get_doc("Land Plot", plot_name)
    plot_id_value = plot_doc.get("plot_id")

    # Ensure this customer has a request that includes this plot
    requests_with_plots = frappe.db.sql(
        """
        SELECT r.name, r.shared_plots_json, r.purchase_order_data
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
        plot_ids = []
        try:
            if req.shared_plots_json:
                parsed = json.loads(req.shared_plots_json) if isinstance(req.shared_plots_json, str) else req.shared_plots_json
                if isinstance(parsed, list):
                    plot_ids.extend(parsed)
                else:
                    plot_ids.append(parsed)
        except Exception:
            pass

        if req.purchase_order_data:
            try:
                po_data = json.loads(req.purchase_order_data) if isinstance(req.purchase_order_data, str) else req.purchase_order_data
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

        if not plot_ids:
            continue

        if plot_name in plot_ids or (plot_id_value and plot_id_value in plot_ids):
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

    doc = frappe.get_doc("Land Plot", plot_name)
    doc.set("custom_risk_mitigated", 1)
    doc.set("custom_risk_mitigation_note", note or "")
    doc.set("custom_risk_mitigation_on", now_datetime())
    doc.set("custom_risk_mitigation_by", user)
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {"ok": True, "plot_name": plot_name}


# Add to your requests.py file

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

        return {
            "request_id": request_id,
            "purchase_order_number": po_number,
            "supplier": supplier,
            "customer": request_doc.customer,
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
        if request_doc.customer != customer and request_doc.supplier != supplier:
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

            plots = frappe.get_all(
                "Land Plot",
                filters={"name": ["in", plot_ids]},
                fields=fields
            )
            if not plots and has_plot_id:
                plots = frappe.get_all(
                    "Land Plot",
                    filters={"plot_id": ["in", plot_ids]},
                    fields=fields
                )
            detailed_plots = plots

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

        if request_doc.request_type != "purchase_order":
            frappe.throw(_("This is not a purchase order request"))

        if request_doc.status != "Accepted":
            return {"plots": [], "message": "Purchase order not yet accepted by supplier"}

        if not request_doc.get("purchase_order_data"):
            return {"plots": [], "message": "Purchase order data not yet submitted"}

        # Parse PO data to get shared plot IDs
        try:
            po_data = json.loads(request_doc.purchase_order_data)
            plot_ids = po_data.get("selected_plots", [])
        except:
            return {"plots": [], "message": "Error reading purchase order data"}

        if not plot_ids:
            return {"plots": [], "message": "No plots shared in this purchase order"}

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
            filters={"name": ["in", plot_ids]},
            fields=fields
        )
        if not plots and has_plot_id:
            plots = frappe.get_all(
                "Land Plot",
                filters={"plot_id": ["in", plot_ids]},
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
