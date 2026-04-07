import frappe
from farmportal.api.organization_profile import (
    _get_customer_permission_context,
    _get_supplier_permission_context,
)


def _normalize_verification_status(value):
    raw = str(value or "").strip().lower()
    if raw in {"verified", "verify", "approved", "done", "complete", "completed"}:
        return "Verified"
    if raw in {"rejected", "reject", "declined"}:
        return "Rejected"
    return "Pending"


def _supplier_verification_key(supplier_name):
    return f"supplier_verification_status::{str(supplier_name or '').strip()}"


def _get_supplier_verification_status(supplier_name):
    supplier_name = str(supplier_name or "").strip()
    if not supplier_name:
        return "Pending"

    value = None
    try:
        meta = frappe.get_meta("Supplier")
        for fieldname in ("custom_verification_status", "verification_status"):
            if meta.has_field(fieldname):
                value = frappe.db.get_value("Supplier", supplier_name, fieldname)
                break
    except Exception:
        value = None

    if value is None or str(value).strip() == "":
        value = frappe.defaults.get_global_default(_supplier_verification_key(supplier_name))

    return _normalize_verification_status(value)


@frappe.whitelist()
def get_current_user():
    """Return info about the currently logged-in user and linked party context."""
    user_id = frappe.session.user
    if user_id in ("Guest", None):
        frappe.throw("Not logged in", frappe.PermissionError)

    user_doc = frappe.get_doc("User", user_id)
    roles = [r.role for r in user_doc.roles]
    role_set = set(roles)

    employee = get_employee_for_user(user_id)
    supplier = get_supplier_for_user(user_doc) if "Supplier" in role_set else None
    customer = get_customer_for_user(user_doc) if "Customer" in role_set else None

    account_type = _resolve_account_type(role_set, customer, supplier, employee)

    # Keep frontend mode unambiguous: expose only the active account context.
    if account_type == "Customer":
        supplier = None
    elif account_type == "Supplier":
        customer = None

    verification_status = _get_supplier_verification_status(
        supplier.get("name") if isinstance(supplier, dict) else None
    )
    if account_type == "Customer":
        account_permissions = _get_customer_permission_context(
            user_id,
            customer.get("name") if isinstance(customer, dict) else None,
        )
    else:
        account_permissions = _get_supplier_permission_context(
            user_id,
            supplier.get("name") if isinstance(supplier, dict) else None,
        )

    return {
        "user": {
            "name": user_doc.name,
            "full_name": user_doc.full_name,
            "email": user_doc.email,
            "roles": roles,
        },
        "employee": employee,
        "supplier": supplier,
        "customer": customer,
        "account_type": account_type,
        "verification_status": verification_status,
        "member_permissions": account_permissions.get("permissions", {}),
        "member_permission_labels": account_permissions.get("permission_labels", []),
        "member_role": account_permissions.get("member_role", "viewer"),
        "member_role_label": account_permissions.get("member_role_label", "Viewer"),
        "is_owner_account": bool(account_permissions.get("is_owner")),
    }


def _resolve_account_type(role_set, customer, supplier, employee):
    """Choose one active account type when user has multiple links/roles."""
    if "Customer" in role_set and customer:
        return "Customer"
    if "Supplier" in role_set and supplier:
        return "Supplier"
    if "Employee" in role_set and employee:
        return "Employee"
    # Link-first fallback even if role records are inconsistent.
    if customer:
        return "Customer"
    if supplier:
        return "Supplier"
    if employee:
        return "Employee"
    # Final role-only fallback: prefer Supplier when both exist without links.
    if "Supplier" in role_set and "Customer" in role_set:
        return "Supplier"
    if "Supplier" in role_set:
        return "Supplier"
    if "Customer" in role_set:
        return "Customer"
    if "Employee" in role_set:
        return "Employee"
    return "User"


def get_employee_for_user(user_id: str):
    """Standard ERPNext link: Employee.user_id -> User.name"""
    return frappe.db.get_value(
        "Employee",
        {"user_id": user_id},
        ["name", "employee_name"],
        as_dict=True
    )


def get_supplier_for_user(user_doc):
    """Find Supplier for a user via custom fields or Contact linkage"""
    # Try custom field approach first
    for fieldname in ("custom_user", "user_id", "user"):
        try:
            sup = frappe.db.get_value(
                "Supplier",
                {fieldname: user_doc.name},
                ["name", "supplier_name"],
                as_dict=True,
            )
            if sup:
                return sup
        except Exception:
            pass

    # Try Supplier User child table membership
    try:
        child_meta = frappe.get_meta("Supplier User")
        clauses = []
        params = []

        user_norm = (user_doc.name or "").strip().lower()
        email_norm = (user_doc.email or "").strip().lower()

        if child_meta.has_field("user_link") and user_norm:
            clauses.append("LOWER(COALESCE(`user_link`, '')) = %s")
            params.append(user_norm)
        if child_meta.has_field("user") and user_norm:
            clauses.append("LOWER(COALESCE(`user`, '')) = %s")
            params.append(user_norm)
        if child_meta.has_field("email") and email_norm:
            clauses.append("LOWER(COALESCE(`email`, '')) = %s")
            params.append(email_norm)

        if clauses:
            rows = frappe.db.sql(
                f"""
                SELECT parent
                FROM `tabSupplier User`
                WHERE parenttype = 'Supplier'
                  AND ({' OR '.join(clauses)})
                ORDER BY modified DESC
                LIMIT 1
                """,
                tuple(params),
                as_dict=True,
            )
            if rows:
                supplier_name = rows[0].get("parent")
                if supplier_name:
                    sup = frappe.db.get_value(
                        "Supplier",
                        supplier_name,
                        ["name", "supplier_name"],
                        as_dict=True,
                    )
                    if sup:
                        return sup
    except Exception:
        pass

    # Standard ERPNext: Contact -> Dynamic Link -> Supplier
    if not user_doc.email:
        return None

    contact_names = frappe.get_all(
        "Contact",
        filters={"email_id": user_doc.email},
        pluck="name",
        limit=10
    )

    if not contact_names:
        return None

    link = frappe.get_all(
        "Dynamic Link",
        filters={
            "parent": ["in", contact_names],
            "link_doctype": "Supplier",
        },
        fields=["link_name"],
        limit=1,
    )

    if not link:
        return None

    supplier_name = link[0].link_name
    return frappe.db.get_value(
        "Supplier",
        supplier_name,
        ["name", "supplier_name"],
        as_dict=True
    )


def get_customer_for_user(user_doc):
    """Find Customer for a user via custom fields or Contact linkage"""
    for fieldname in ("custom_user", "user_id", "user"):
        try:
            customer = frappe.db.get_value(
                "Customer",
                {fieldname: user_doc.name},
                ["name", "customer_name"],
                as_dict=True,
            )
            if customer:
                return customer
        except Exception:
            pass

    try:
        child_meta = frappe.get_meta("Customer User")
        clauses = []
        params = []

        user_norm = (user_doc.name or "").strip().lower()
        email_norm = (user_doc.email or "").strip().lower()

        if child_meta.has_field("user_link") and user_norm:
            clauses.append("LOWER(COALESCE(`user_link`, '')) = %s")
            params.append(user_norm)
        if child_meta.has_field("user") and user_norm:
            clauses.append("LOWER(COALESCE(`user`, '')) = %s")
            params.append(user_norm)
        if child_meta.has_field("email") and email_norm:
            clauses.append("LOWER(COALESCE(`email`, '')) = %s")
            params.append(email_norm)

        if clauses:
            rows = frappe.db.sql(
                f"""
                SELECT parent
                FROM `tabCustomer User`
                WHERE parenttype = 'Customer'
                  AND ({' OR '.join(clauses)})
                ORDER BY modified DESC
                LIMIT 1
                """,
                tuple(params),
                as_dict=True,
            )
            if rows:
                customer_name = rows[0].get("parent")
                if customer_name:
                    customer = frappe.db.get_value(
                        "Customer",
                        customer_name,
                        ["name", "customer_name"],
                        as_dict=True,
                    )
                    if customer:
                        return customer
    except Exception:
        pass

    if not user_doc.email:
        return None

    contact_names = frappe.get_all(
        "Contact",
        filters={"email_id": user_doc.email},
        pluck="name",
        limit=10,
    )

    if not contact_names:
        return None

    link = frappe.get_all(
        "Dynamic Link",
        filters={
            "parent": ["in", contact_names],
            "link_doctype": "Customer",
        },
        fields=["link_name"],
        limit=1,
    )

    if not link:
        return None

    customer_name = link[0].link_name
    return frappe.db.get_value(
        "Customer",
        customer_name,
        ["name", "customer_name"],
        as_dict=True,
    )
