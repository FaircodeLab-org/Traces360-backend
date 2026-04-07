import frappe, json
from frappe import _

MAX_SUPPLIER_MEMBERS = 5
MAX_CUSTOMER_MEMBERS = 5

SUPPLIER_PERMISSION_ADMINISTRATOR = "administrator"
SUPPLIER_PERMISSION_SUPPLIER_ACCOUNT_MANAGER = "supplier_account_manager"
SUPPLIER_PERMISSION_USER_MANAGER = "user_manager"
SUPPLIER_PERMISSION_CERTIFICATE_MANAGER = "certificate_manager"
SUPPLIER_PERMISSION_QUESTIONNAIRE_MANAGER = "questionnaire_manager"
SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES = "own_questionnaires"
SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER = "purchase_order_manager"
SUPPLIER_PERMISSION_PLOT_MANAGER = "plot_manager"

SUPPLIER_PERMISSION_KEYS = (
    SUPPLIER_PERMISSION_ADMINISTRATOR,
    SUPPLIER_PERMISSION_SUPPLIER_ACCOUNT_MANAGER,
    SUPPLIER_PERMISSION_USER_MANAGER,
    SUPPLIER_PERMISSION_CERTIFICATE_MANAGER,
    SUPPLIER_PERMISSION_QUESTIONNAIRE_MANAGER,
    SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES,
    SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER,
    SUPPLIER_PERMISSION_PLOT_MANAGER,
)

SUPPLIER_MEMBER_ROLE_LABELS = {
    "operations_manager": "Operations Manager",
    "supplier_account_manager": "Supplier Account Manager",
    "certificate_manager": "Certificate Manager",
    "questionnaire_manager": "Questionnaire Manager",
    "purchase_order_manager": "Purchase Order Manager",
    "plot_manager": "Plot Manager",
    "viewer": "Viewer",
}

SUPPLIER_MEMBER_ROLE_ALIASES = {
    "operations manager": "operations_manager",
    "operations_manager": "operations_manager",
    "supplier account manager": "supplier_account_manager",
    "supplier_account_manager": "supplier_account_manager",
    "certificate manager": "certificate_manager",
    "certificate_manager": "certificate_manager",
    "questionnaire manager": "questionnaire_manager",
    "questionnaire_manager": "questionnaire_manager",
    "purchase order manager": "purchase_order_manager",
    "purchase_order_manager": "purchase_order_manager",
    "plot manager": "plot_manager",
    "plot_manager": "plot_manager",
    "viewer": "viewer",
}

SUPPLIER_MEMBER_ROLE_CAPABILITIES = {
    "operations_manager": {
        SUPPLIER_PERMISSION_SUPPLIER_ACCOUNT_MANAGER,
        SUPPLIER_PERMISSION_CERTIFICATE_MANAGER,
        SUPPLIER_PERMISSION_QUESTIONNAIRE_MANAGER,
        SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER,
        SUPPLIER_PERMISSION_PLOT_MANAGER,
    },
    "supplier_account_manager": {SUPPLIER_PERMISSION_SUPPLIER_ACCOUNT_MANAGER},
    "certificate_manager": {SUPPLIER_PERMISSION_CERTIFICATE_MANAGER},
    "questionnaire_manager": {SUPPLIER_PERMISSION_QUESTIONNAIRE_MANAGER},
    "purchase_order_manager": {SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER},
    "plot_manager": {SUPPLIER_PERMISSION_PLOT_MANAGER},
    "viewer": set(),
}

SUPPLIER_OWNER_CAPABILITIES = {
    SUPPLIER_PERMISSION_ADMINISTRATOR,
    SUPPLIER_PERMISSION_SUPPLIER_ACCOUNT_MANAGER,
    SUPPLIER_PERMISSION_USER_MANAGER,
    SUPPLIER_PERMISSION_CERTIFICATE_MANAGER,
    SUPPLIER_PERMISSION_QUESTIONNAIRE_MANAGER,
    SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER,
    SUPPLIER_PERMISSION_PLOT_MANAGER,
}

SUPPLIER_PERMISSION_LABELS = {
    SUPPLIER_PERMISSION_ADMINISTRATOR: "Administrator",
    SUPPLIER_PERMISSION_SUPPLIER_ACCOUNT_MANAGER: "Supplier Account Manager",
    SUPPLIER_PERMISSION_USER_MANAGER: "User Manager",
    SUPPLIER_PERMISSION_CERTIFICATE_MANAGER: "Certificate Manager",
    SUPPLIER_PERMISSION_QUESTIONNAIRE_MANAGER: "Questionnaire Manager",
    SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES: "Own Questionnaires",
    SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER: "Purchase Order Manager",
    SUPPLIER_PERMISSION_PLOT_MANAGER: "Plot Manager",
}

SUPPLIER_ASSIGNABLE_PERMISSION_KEYS = (
    SUPPLIER_PERMISSION_SUPPLIER_ACCOUNT_MANAGER,
    SUPPLIER_PERMISSION_CERTIFICATE_MANAGER,
    SUPPLIER_PERMISSION_QUESTIONNAIRE_MANAGER,
    SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER,
    SUPPLIER_PERMISSION_PLOT_MANAGER,
    SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES,
)

SUPPLIER_ROW_PERMISSION_FIELDS = {
    SUPPLIER_PERMISSION_SUPPLIER_ACCOUNT_MANAGER: "can_manage_supplier_account",
    SUPPLIER_PERMISSION_CERTIFICATE_MANAGER: "can_manage_certificates",
    SUPPLIER_PERMISSION_QUESTIONNAIRE_MANAGER: "can_manage_questionnaires",
    SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER: "can_manage_purchase_orders",
    SUPPLIER_PERMISSION_PLOT_MANAGER: "can_manage_plots",
}

# @frappe.whitelist(allow_guest=False)
# def get_profile_for_user():
#     """
#     Fetch Organization Module document linked to the logged-in user.
#     Returns full document JSON if found, else None.
#     """
#     user = frappe.session.user
#     existing = frappe.db.exists("Organization Module", {"user": user})
#     if not existing:
#         return None

#     doc = frappe.get_doc("Organization Module", existing)
#     return doc.as_dict()

def _find_supplier_by_org_name(org_name):
    if not org_name:
        return None

    supplier_name = frappe.db.get_value("Supplier", {"supplier_name": org_name}, "name")
    if supplier_name:
        return supplier_name

    if frappe.db.exists("Supplier", org_name):
        return org_name

    return None


def _find_customer_by_org_name(org_name):
    if not org_name:
        return None

    customer_name = frappe.db.get_value("Customer", {"customer_name": org_name}, "name")
    if customer_name:
        return customer_name

    if frappe.db.exists("Customer", org_name):
        return org_name

    return None


def _normalize_email(value):
    return (value or "").strip().lower()


def _parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _normalize_supplier_member_role(value) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "operations_manager"
    return SUPPLIER_MEMBER_ROLE_ALIASES.get(raw, "viewer")


def _resolve_requested_member_role(data: dict) -> str:
    requested = (
        data.get("memberRole")
        or data.get("member_role")
        or data.get("role")
        or ""
    )
    requested_raw = str(requested or "").strip().lower()
    if requested_raw in {"administrator", "admin", "user manager", "user_manager"}:
        frappe.throw(
            _("Administrator and User Manager permissions are reserved for the parent supplier account"),
            frappe.PermissionError,
        )
    if requested_raw and requested_raw not in SUPPLIER_MEMBER_ROLE_ALIASES:
        frappe.throw(_("Invalid member role selected"))
    return _normalize_supplier_member_role(requested_raw)


def _supplier_permissions_map(capabilities: set[str], own_questionnaires_only: bool) -> dict:
    permissions = {key: key in capabilities for key in SUPPLIER_PERMISSION_KEYS}
    permissions[SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES] = bool(own_questionnaires_only)
    return permissions


def _parse_requested_permission_keys(raw_permissions) -> set[str]:
    if raw_permissions is None:
        return set()

    parsed = raw_permissions
    if isinstance(raw_permissions, str):
        text = raw_permissions.strip()
        if not text:
            return set()
        try:
            loaded = json.loads(text)
            parsed = loaded
        except Exception:
            parsed = [p.strip() for p in text.split(",") if p.strip()]

    values = parsed if isinstance(parsed, (list, tuple, set)) else []
    normalized = set()
    for value in values:
        token = str(value or "").strip().lower()
        if not token:
            continue
        normalized.add(token)

    reserved = {SUPPLIER_PERMISSION_ADMINISTRATOR, SUPPLIER_PERMISSION_USER_MANAGER}
    if normalized.intersection(reserved):
        frappe.throw(
            _("Administrator and User Manager permissions are reserved for the parent supplier account"),
            frappe.PermissionError,
        )

    invalid = [key for key in normalized if key not in SUPPLIER_ASSIGNABLE_PERMISSION_KEYS]
    if invalid:
        frappe.throw(_("Invalid permission(s): {0}").format(", ".join(sorted(invalid))))

    return normalized


def _permission_labels(permission_keys) -> list[str]:
    labels = []
    for key in SUPPLIER_PERMISSION_KEYS:
        if key in (permission_keys or set()):
            labels.append(SUPPLIER_PERMISSION_LABELS.get(key, key))
    return labels


def _get_member_row_permission_keys(row, row_meta=None) -> set[str]:
    keys = set()
    meta = row_meta
    if not meta:
        try:
            meta = frappe.get_meta(getattr(row, "doctype", "") or "")
        except Exception:
            meta = None

    for permission_key, fieldname in SUPPLIER_ROW_PERMISSION_FIELDS.items():
        has_field = bool(meta and meta.has_field(fieldname))
        if has_field and _parse_bool(getattr(row, fieldname, None), default=False):
            keys.add(permission_key)

    own_only = _parse_bool(getattr(row, "own_questionnaires_only", None), default=False)
    if own_only:
        keys.add(SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES)

    # Backward compatibility for legacy row-based role model.
    if not keys:
        role_key = _normalize_supplier_member_role(getattr(row, "member_role", None))
        keys.update(SUPPLIER_MEMBER_ROLE_CAPABILITIES.get(role_key, set()))
        if own_only:
            keys.add(SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES)

    return keys


def _resolve_user_name(value):
    if not value:
        return None

    raw_value = value.strip()
    if frappe.db.exists("User", raw_value):
        return raw_value

    user_from_username = frappe.db.get_value("User", {"username": raw_value}, "name")
    if user_from_username:
        return user_from_username

    email_norm = _normalize_email(raw_value)
    if not email_norm:
        return None

    if frappe.db.exists("User", email_norm):
        return email_norm

    user_from_username = frappe.db.get_value("User", {"username": email_norm}, "name")
    if user_from_username:
        return user_from_username

    return frappe.db.get_value("User", {"email": email_norm}, "name")


def _get_user_email(user: str) -> str | None:
    try:
        return frappe.db.get_value("User", user, "email")
    except Exception:
        return None


def _find_supplier_from_contact(user: str) -> str | None:
    """Fallback mapping: User -> Contact(Email) -> Dynamic Link -> Supplier."""
    email = _get_user_email(user)
    if not email:
        return None

    contact_names = frappe.get_all("Contact Email", filters={"email_id": email}, pluck="parent")
    if not contact_names:
        contact_names = frappe.get_all("Contact", filters={"email_id": email}, pluck="name")
    if not contact_names:
        return None

    links = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Contact",
            "parent": ["in", contact_names],
            "link_doctype": "Supplier",
        },
        fields=["link_name"],
        limit_page_length=50,
    )
    if not links:
        return None

    for row in links:
        link_name = row.get("link_name")
        if link_name and frappe.db.exists("Supplier", link_name):
            return link_name
    return None


def _find_customer_from_contact(user: str) -> str | None:
    """Fallback mapping: User -> Contact(Email) -> Dynamic Link -> Customer."""
    email = _get_user_email(user)
    if not email:
        return None

    contact_names = frappe.get_all("Contact Email", filters={"email_id": email}, pluck="parent")
    if not contact_names:
        contact_names = frappe.get_all("Contact", filters={"email_id": email}, pluck="name")
    if not contact_names:
        return None

    links = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Contact",
            "parent": ["in", contact_names],
            "link_doctype": "Customer",
        },
        fields=["link_name"],
        limit_page_length=50,
    )
    if not links:
        return None

    for row in links:
        link_name = row.get("link_name")
        if link_name and frappe.db.exists("Customer", link_name):
            return link_name
    return None


def _find_supplier_from_member_rows(user: str) -> str | None:
    """
    Fallback mapping via Supplier member child rows.
    This is important for invited supplier users who may not have
    a direct Supplier.user/custom_user link.
    """
    resolved_user = _resolve_user_name(user) or str(user or "").strip()
    email = _get_user_email(resolved_user) or _get_user_email(user) or ""

    candidates = []
    for value in (user, resolved_user, email):
        normalized = _normalize_email(value)
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    if not candidates:
        return None

    try:
        meta = frappe.get_meta("Supplier User")
    except Exception:
        return None

    placeholders = ", ".join(["%s"] * len(candidates))
    select_columns = ["parent", "modified"]
    where_clauses = []

    if meta.has_field("email"):
        select_columns.append("email")
        where_clauses.append(f"LOWER(COALESCE(email, '')) IN ({placeholders})")
    if meta.has_field("user_link"):
        select_columns.append("user_link")
        where_clauses.append(f"LOWER(COALESCE(user_link, '')) IN ({placeholders})")
    if meta.has_field("user"):
        select_columns.append("`user`")
        where_clauses.append(f"LOWER(COALESCE(`user`, '')) IN ({placeholders})")

    if not where_clauses:
        return None

    query = f"""
        SELECT {", ".join(select_columns)}
        FROM `tabSupplier User`
        WHERE parenttype = 'Supplier'
          AND ({' OR '.join(where_clauses)})
        ORDER BY modified DESC
        LIMIT 200
    """
    params = tuple(candidates * len(where_clauses))

    try:
        rows = frappe.db.sql(query, params, as_dict=True)
    except Exception:
        return None

    for row in rows:
        parent = str(row.get("parent") or "").strip()
        if parent and frappe.db.exists("Supplier", parent):
            return parent

    return None


def _find_customer_from_member_rows(user: str) -> str | None:
    """
    Fallback mapping via Customer member child rows.
    """
    resolved_user = _resolve_user_name(user) or str(user or "").strip()
    email = _get_user_email(resolved_user) or _get_user_email(user) or ""

    candidates = []
    for value in (user, resolved_user, email):
        normalized = _normalize_email(value)
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    if not candidates:
        return None

    try:
        meta = frappe.get_meta("Customer User")
    except Exception:
        return None

    placeholders = ", ".join(["%s"] * len(candidates))
    select_columns = ["parent", "modified"]
    where_clauses = []

    if meta.has_field("email"):
        select_columns.append("email")
        where_clauses.append(f"LOWER(COALESCE(email, '')) IN ({placeholders})")
    if meta.has_field("user_link"):
        select_columns.append("user_link")
        where_clauses.append(f"LOWER(COALESCE(user_link, '')) IN ({placeholders})")
    if meta.has_field("user"):
        select_columns.append("`user`")
        where_clauses.append(f"LOWER(COALESCE(`user`, '')) IN ({placeholders})")

    if not where_clauses:
        return None

    query = f"""
        SELECT {", ".join(select_columns)}
        FROM `tabCustomer User`
        WHERE parenttype = 'Customer'
          AND ({' OR '.join(where_clauses)})
        ORDER BY modified DESC
        LIMIT 200
    """
    params = tuple(candidates * len(where_clauses))

    try:
        rows = frappe.db.sql(query, params, as_dict=True)
    except Exception:
        return None

    for row in rows:
        parent = str(row.get("parent") or "").strip()
        if parent and frappe.db.exists("Customer", parent):
            return parent

    return None


def _get_supplier_owner_user(supplier_doc) -> str | None:
    for fieldname in ("custom_user", "user_id", "user"):
        value = _resolve_user_name(str(supplier_doc.get(fieldname) or "").strip())
        if value:
            return value
    return None


def _get_supplier_user_link_fields() -> list[str]:
    """Return only Supplier link fields that exist on this site."""
    candidates = ("custom_user", "user_id", "user")
    try:
        meta = frappe.get_meta("Supplier")
    except Exception:
        return ["custom_user"]
    return [fieldname for fieldname in candidates if meta.has_field(fieldname)]


def _get_customer_owner_user(customer_doc) -> str | None:
    for fieldname in ("custom_user", "user_id", "user"):
        value = _resolve_user_name(str(customer_doc.get(fieldname) or "").strip())
        if value:
            return value
    return None


def _get_customer_user_link_fields() -> list[str]:
    """Return only Customer link fields that exist on this site."""
    candidates = ("custom_user", "user_id", "user")
    try:
        meta = frappe.get_meta("Customer")
    except Exception:
        return ["custom_user"]
    return [fieldname for fieldname in candidates if meta.has_field(fieldname)]


def _resolve_supplier_hint_to_name(supplier_hint=None) -> str | None:
    """
    Resolve a frontend hint (supplier id/name or org profile id) to Supplier.name.
    This does not imply permission; caller must still verify user linkage.
    """
    hint = str(supplier_hint or "").strip()
    if not hint:
        return None

    if frappe.db.exists("Supplier", hint):
        return hint

    org_name = frappe.db.get_value("Organization Module", hint, "organization_name")
    supplier_from_org = _find_supplier_by_org_name(org_name)
    if supplier_from_org:
        return supplier_from_org

    return _find_supplier_by_org_name(hint)


def _resolve_customer_hint_to_name(customer_hint=None) -> str | None:
    """
    Resolve a frontend hint (customer id/name or org profile id) to Customer.name.
    This does not imply permission; caller must still verify user linkage.
    """
    hint = str(customer_hint or "").strip()
    if not hint:
        return None

    if frappe.db.exists("Customer", hint):
        return hint

    org_name = frappe.db.get_value("Organization Module", hint, "organization_name")
    customer_from_org = _find_customer_by_org_name(org_name)
    if customer_from_org:
        return customer_from_org

    return _find_customer_by_org_name(hint)


def _collect_linked_suppliers_for_user(user_candidates: list[str], email_candidates: list[str]) -> list[str]:
    """
    Collect Suppliers that are actually linked to this user via supported mapping paths.
    Ordered by current fallback priority to preserve existing behavior.
    """
    linked_suppliers = []

    def _add_supplier(candidate_name):
        supplier_name = str(candidate_name or "").strip()
        if not supplier_name:
            return
        if supplier_name in linked_suppliers:
            return
        if frappe.db.exists("Supplier", supplier_name):
            linked_suppliers.append(supplier_name)

    # 1) Direct Supplier.user link fields
    for fieldname in _get_supplier_user_link_fields():
        for candidate_user in user_candidates:
            _add_supplier(frappe.db.get_value("Supplier", {fieldname: candidate_user}, "name"))
        for email_candidate in email_candidates:
            _add_supplier(frappe.db.get_value("Supplier", {fieldname: email_candidate}, "name"))

    # 2) Supplier User child table membership
    for candidate_user in user_candidates:
        _add_supplier(_find_supplier_from_member_rows(candidate_user))

    # 3) Legacy/fallback mapping paths
    for candidate_user in user_candidates:
        if frappe.db.exists("Supplier", candidate_user):
            _add_supplier(candidate_user)

        org_name = frappe.db.get_value("Organization Module", {"user": candidate_user}, "organization_name")
        _add_supplier(_find_supplier_by_org_name(org_name))
        _add_supplier(_find_supplier_from_contact(candidate_user))

    return linked_suppliers


def _collect_linked_customers_for_user(user_candidates: list[str], email_candidates: list[str]) -> list[str]:
    """
    Collect Customers that are actually linked to this user via supported mapping paths.
    Ordered by current fallback priority to preserve existing behavior.
    """
    linked_customers = []

    def _add_customer(candidate_name):
        customer_name = str(candidate_name or "").strip()
        if not customer_name:
            return
        if customer_name in linked_customers:
            return
        if frappe.db.exists("Customer", customer_name):
            linked_customers.append(customer_name)

    # 1) Direct Customer.user link fields
    for fieldname in _get_customer_user_link_fields():
        for candidate_user in user_candidates:
            _add_customer(frappe.db.get_value("Customer", {fieldname: candidate_user}, "name"))
        for email_candidate in email_candidates:
            _add_customer(frappe.db.get_value("Customer", {fieldname: email_candidate}, "name"))

    # 2) Customer User child table membership
    for candidate_user in user_candidates:
        _add_customer(_find_customer_from_member_rows(candidate_user))

    # 3) Legacy/fallback mapping paths
    for candidate_user in user_candidates:
        if frappe.db.exists("Customer", candidate_user):
            _add_customer(candidate_user)

        org_name = frappe.db.get_value("Organization Module", {"user": candidate_user}, "organization_name")
        _add_customer(_find_customer_by_org_name(org_name))
        _add_customer(_find_customer_from_contact(candidate_user))

    return linked_customers


def _get_supplier_for_user(user, supplier_hint=None):
    resolved_user = _resolve_user_name(user) or str(user or "").strip()
    user_candidates = []
    for candidate in (resolved_user, str(user or "").strip()):
        if candidate and candidate not in user_candidates:
            user_candidates.append(candidate)

    email_candidates = []
    for candidate_user in user_candidates:
        email = _get_user_email(candidate_user)
        normalized = _normalize_email(email)
        if normalized and normalized not in email_candidates:
            email_candidates.append(normalized)

    linked_suppliers = _collect_linked_suppliers_for_user(user_candidates, email_candidates)
    hint_supplier = _resolve_supplier_hint_to_name(supplier_hint)

    # Trust hint only when it belongs to this user context.
    if hint_supplier and hint_supplier in linked_suppliers:
        return hint_supplier

    # If hint is provided but not linked, ignore it and safely fall back.
    if linked_suppliers:
        return linked_suppliers[0]

    return None


def _get_customer_for_user(user, customer_hint=None):
    resolved_user = _resolve_user_name(user) or str(user or "").strip()
    user_candidates = []
    for candidate in (resolved_user, str(user or "").strip()):
        if candidate and candidate not in user_candidates:
            user_candidates.append(candidate)

    email_candidates = []
    for candidate_user in user_candidates:
        email = _get_user_email(candidate_user)
        normalized = _normalize_email(email)
        if normalized and normalized not in email_candidates:
            email_candidates.append(normalized)

    linked_customers = _collect_linked_customers_for_user(user_candidates, email_candidates)
    hint_customer = _resolve_customer_hint_to_name(customer_hint)

    # Trust hint only when it belongs to this user context.
    if hint_customer and hint_customer in linked_customers:
        return hint_customer

    # If hint is provided but not linked, ignore it and safely fall back.
    if linked_customers:
        return linked_customers[0]

    return None


def _get_member_table_fieldname(supplier_doc=None):
    """
    Resolve the Supplier child table field used to store organization members.
    Supports legacy and current field names across sites.
    """
    meta = supplier_doc.meta if supplier_doc else frappe.get_meta("Supplier")

    # Preferred explicit field names first.
    for fieldname in ("custom_organization_members", "organization_members", "supplier_users"):
        df = meta.get_field(fieldname)
        if df and df.fieldtype == "Table":
            return fieldname

    # Fallback: any table field using the Supplier User child doctype.
    for df in (meta.fields or []):
        if getattr(df, "fieldtype", None) == "Table" and getattr(df, "options", None) == "Supplier User":
            return df.fieldname

    return None


def _get_customer_member_table_fieldname(customer_doc=None):
    """
    Resolve the Customer child table field used to store organization members.
    """
    meta = customer_doc.meta if customer_doc else frappe.get_meta("Customer")

    for fieldname in ("custom_organization_members", "organization_members", "customer_users", "custom_members"):
        df = meta.get_field(fieldname)
        if df and df.fieldtype == "Table":
            return fieldname

    for df in (meta.fields or []):
        if getattr(df, "fieldtype", None) == "Table" and getattr(df, "options", None) == "Customer User":
            return df.fieldname

    return None


def _get_supplier_member_user_ids(supplier_doc) -> list[str]:
    """Resolve User IDs for all rows in the supplier member child table."""
    member_table_fieldname = _get_member_table_fieldname(supplier_doc)
    if not member_table_fieldname:
        return []

    user_ids = []
    for row in (supplier_doc.get(member_table_fieldname) or []):
        resolved = _resolve_user_name(
            getattr(row, "user_link", None) or getattr(row, "user", None) or getattr(row, "email", None)
        )
        if resolved and resolved not in user_ids:
            user_ids.append(resolved)
    return user_ids


def _get_customer_member_user_ids(customer_doc) -> list[str]:
    """Resolve User IDs for all rows in the customer member child table."""
    member_table_fieldname = _get_customer_member_table_fieldname(customer_doc)
    if not member_table_fieldname:
        return []

    user_ids = []
    for row in (customer_doc.get(member_table_fieldname) or []):
        resolved = _resolve_user_name(
            getattr(row, "user_link", None) or getattr(row, "user", None) or getattr(row, "email", None)
        )
        if resolved and resolved not in user_ids:
            user_ids.append(resolved)
    return user_ids


def _find_supplier_member_row(supplier_doc, user: str):
    """Find matching Supplier User row for this user."""
    member_table_fieldname = _get_member_table_fieldname(supplier_doc)
    if not member_table_fieldname:
        return None

    resolved_user = _resolve_user_name(user) or str(user or "").strip()
    user_email = _normalize_email(_get_user_email(resolved_user) or _get_user_email(user) or "")
    candidates = {
        _normalize_email(user),
        _normalize_email(resolved_user),
        user_email,
    }
    candidates = {c for c in candidates if c}

    for row in (supplier_doc.get(member_table_fieldname) or []):
        row_candidates = {
            _normalize_email(getattr(row, "email", None)),
            _normalize_email(getattr(row, "user_link", None)),
            _normalize_email(getattr(row, "user", None)),
        }
        if candidates.intersection({c for c in row_candidates if c}):
            return row
    return None


def _find_customer_member_row(customer_doc, user: str):
    """Find matching Customer User row for this user."""
    member_table_fieldname = _get_customer_member_table_fieldname(customer_doc)
    if not member_table_fieldname:
        return None

    resolved_user = _resolve_user_name(user) or str(user or "").strip()
    user_email = _normalize_email(_get_user_email(resolved_user) or _get_user_email(user) or "")
    candidates = {
        _normalize_email(user),
        _normalize_email(resolved_user),
        user_email,
    }
    candidates = {c for c in candidates if c}

    for row in (customer_doc.get(member_table_fieldname) or []):
        row_candidates = {
            _normalize_email(getattr(row, "email", None)),
            _normalize_email(getattr(row, "user_link", None)),
            _normalize_email(getattr(row, "user", None)),
        }
        if candidates.intersection({c for c in row_candidates if c}):
            return row
    return None


def _get_supplier_permission_context(user: str, supplier_hint=None) -> dict:
    """
    Resolve supplier-scoped permissions for the acting user.
    Parent supplier user always has administrator + user manager privileges.
    """
    supplier_name, supplier_doc, owner_user, supplier_org_name = _get_supplier_context_for_user(user, supplier_hint)
    if not supplier_name or not supplier_doc:
        return {
            "has_supplier": False,
            "supplier_name": None,
            "supplier_org_name": None,
            "owner_user": None,
            "is_owner": False,
            "is_member": False,
            "member_row_name": None,
            "member_role": "viewer",
            "member_role_label": SUPPLIER_MEMBER_ROLE_LABELS["viewer"],
            "own_questionnaires_only": False,
            "permission_labels": [],
            "capabilities": set(),
            "permissions": _supplier_permissions_map(set(), False),
        }

    resolved_user = _resolve_user_name(user) or str(user or "").strip()
    owner_resolved = _resolve_user_name(owner_user) if owner_user else None
    is_owner = bool(owner_resolved and resolved_user == owner_resolved)
    is_system_manager = "System Manager" in set(frappe.get_roles(user) or [])

    if is_owner or is_system_manager:
        capabilities = set(SUPPLIER_OWNER_CAPABILITIES)
        return {
            "has_supplier": True,
            "supplier_name": supplier_name,
            "supplier_org_name": supplier_org_name,
            "owner_user": owner_resolved or owner_user,
            "is_owner": True if is_owner else False,
            "is_member": True,
            "member_row_name": None,
            "member_role": "operations_manager",
            "member_role_label": "Owner",
            "own_questionnaires_only": False,
            "permission_labels": _permission_labels(set(SUPPLIER_OWNER_CAPABILITIES)),
            "capabilities": capabilities,
            "permissions": _supplier_permissions_map(capabilities, False),
        }

    member_row = _find_supplier_member_row(supplier_doc, user)
    if member_row:
        row_doctype = str(getattr(member_row, "doctype", "") or "Supplier User")
        row_meta = frappe.get_meta(row_doctype)
        row_permission_keys = _get_member_row_permission_keys(member_row, row_meta=row_meta)
        own_questionnaires_only = SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES in row_permission_keys
        capabilities = set(
            permission_key
            for permission_key in row_permission_keys
            if permission_key != SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES
        )
        role_key = _normalize_supplier_member_role(getattr(member_row, "member_role", None))
    else:
        role_key = "viewer"
        own_questionnaires_only = False
        capabilities = set()

    return {
        "has_supplier": True,
        "supplier_name": supplier_name,
        "supplier_org_name": supplier_org_name,
        "owner_user": owner_resolved or owner_user,
        "is_owner": False,
        "is_member": bool(member_row),
        "member_row_name": getattr(member_row, "name", None) if member_row else None,
        "member_role": role_key,
        "member_role_label": SUPPLIER_MEMBER_ROLE_LABELS.get(role_key, SUPPLIER_MEMBER_ROLE_LABELS["viewer"]),
        "own_questionnaires_only": own_questionnaires_only,
        "permission_labels": _permission_labels(set(capabilities) | ({SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES} if own_questionnaires_only else set())),
        "capabilities": capabilities,
        "permissions": _supplier_permissions_map(capabilities, own_questionnaires_only),
    }


def _get_customer_permission_context(user: str, customer_hint=None) -> dict:
    """
    Resolve customer/importer-scoped permissions for the acting user.
    Parent importer user always has administrator + user manager privileges.
    """
    customer_name, customer_doc, owner_user, customer_org_name = _get_customer_context_for_user(user, customer_hint)
    if not customer_name or not customer_doc:
        return {
            "has_customer": False,
            "customer_name": None,
            "customer_org_name": None,
            "owner_user": None,
            "is_owner": False,
            "is_member": False,
            "member_row_name": None,
            "member_role": "viewer",
            "member_role_label": SUPPLIER_MEMBER_ROLE_LABELS["viewer"],
            "own_questionnaires_only": False,
            "permission_labels": [],
            "capabilities": set(),
            "permissions": _supplier_permissions_map(set(), False),
        }

    resolved_user = _resolve_user_name(user) or str(user or "").strip()
    owner_resolved = _resolve_user_name(owner_user) if owner_user else None
    is_owner = bool(owner_resolved and resolved_user == owner_resolved)
    is_system_manager = "System Manager" in set(frappe.get_roles(user) or [])

    if is_owner or is_system_manager:
        capabilities = set(SUPPLIER_OWNER_CAPABILITIES)
        return {
            "has_customer": True,
            "customer_name": customer_name,
            "customer_org_name": customer_org_name,
            "owner_user": owner_resolved or owner_user,
            "is_owner": True if is_owner else False,
            "is_member": True,
            "member_row_name": None,
            "member_role": "operations_manager",
            "member_role_label": "Owner",
            "own_questionnaires_only": False,
            "permission_labels": _permission_labels(set(SUPPLIER_OWNER_CAPABILITIES)),
            "capabilities": capabilities,
            "permissions": _supplier_permissions_map(capabilities, False),
        }

    member_row = _find_customer_member_row(customer_doc, user)
    if member_row:
        row_doctype = str(getattr(member_row, "doctype", "") or "Customer User")
        row_meta = frappe.get_meta(row_doctype)
        row_permission_keys = _get_member_row_permission_keys(member_row, row_meta=row_meta)
        own_questionnaires_only = SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES in row_permission_keys
        capabilities = set(
            permission_key
            for permission_key in row_permission_keys
            if permission_key != SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES
        )
        role_key = _normalize_supplier_member_role(getattr(member_row, "member_role", None))
    else:
        role_key = "viewer"
        own_questionnaires_only = False
        capabilities = set()

    return {
        "has_customer": True,
        "customer_name": customer_name,
        "customer_org_name": customer_org_name,
        "owner_user": owner_resolved or owner_user,
        "is_owner": False,
        "is_member": bool(member_row),
        "member_row_name": getattr(member_row, "name", None) if member_row else None,
        "member_role": role_key,
        "member_role_label": SUPPLIER_MEMBER_ROLE_LABELS.get(role_key, SUPPLIER_MEMBER_ROLE_LABELS["viewer"]),
        "own_questionnaires_only": own_questionnaires_only,
        "permission_labels": _permission_labels(set(capabilities) | ({SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES} if own_questionnaires_only else set())),
        "capabilities": capabilities,
        "permissions": _supplier_permissions_map(capabilities, own_questionnaires_only),
    }


def _has_supplier_permission(user: str, permission_key: str, supplier_hint=None) -> bool:
    context = _get_supplier_permission_context(user, supplier_hint)
    if not context.get("has_supplier"):
        return False
    return bool(context.get("permissions", {}).get(permission_key))


def _require_supplier_permission(user: str, permission_key: str, supplier_hint=None, message: str | None = None) -> dict:
    context = _get_supplier_permission_context(user, supplier_hint)
    if context.get("has_supplier") and context.get("permissions", {}).get(permission_key):
        return context
    frappe.throw(
        message or _("You are not allowed to perform this action"),
        frappe.PermissionError,
    )


def _has_customer_permission(user: str, permission_key: str, customer_hint=None) -> bool:
    context = _get_customer_permission_context(user, customer_hint)
    if not context.get("has_customer"):
        return False
    return bool(context.get("permissions", {}).get(permission_key))


def _require_customer_permission(user: str, permission_key: str, customer_hint=None, message: str | None = None) -> dict:
    context = _get_customer_permission_context(user, customer_hint)
    if context.get("has_customer") and context.get("permissions", {}).get(permission_key):
        return context
    frappe.throw(
        message or _("You are not allowed to perform this action"),
        frappe.PermissionError,
    )


def _can_manage_supplier_members(supplier_doc, user: str) -> bool:
    supplier_name = str(getattr(supplier_doc, "name", "") or "").strip()
    if not supplier_name:
        return False
    return _has_supplier_permission(user, SUPPLIER_PERMISSION_USER_MANAGER, supplier_hint=supplier_name)


def _can_manage_customer_members(customer_doc, user: str) -> bool:
    customer_name = str(getattr(customer_doc, "name", "") or "").strip()
    if not customer_name:
        return False
    return _has_customer_permission(user, SUPPLIER_PERMISSION_USER_MANAGER, customer_hint=customer_name)


def _get_supplier_context_for_user(user: str, supplier_hint=None):
    supplier_name = _get_supplier_for_user(user, supplier_hint)
    if not supplier_name:
        return None, None, None, None

    supplier_doc = frappe.get_doc("Supplier", supplier_name)
    owner_user = _get_supplier_owner_user(supplier_doc)
    supplier_org_name = str(supplier_doc.get("supplier_name") or "").strip()
    return supplier_name, supplier_doc, owner_user, supplier_org_name


def _get_customer_context_for_user(user: str, customer_hint=None):
    customer_name = _get_customer_for_user(user, customer_hint)
    if not customer_name:
        return None, None, None, None

    customer_doc = frappe.get_doc("Customer", customer_name)
    owner_user = _get_customer_owner_user(customer_doc)
    customer_org_name = str(customer_doc.get("customer_name") or "").strip()
    return customer_name, customer_doc, owner_user, customer_org_name


def _get_preferred_party_type(user: str, data: dict | None = None) -> str | None:
    data = data or {}
    requested = str(data.get("partyType") or data.get("accountType") or "").strip().lower()
    if requested in {"supplier", "customer"}:
        return requested

    roles = set(frappe.get_roles(user) or [])
    if "Customer" in roles:
        return "customer"
    if "Supplier" in roles:
        return "supplier"
    return None


def _get_role_aware_party_contexts(user: str, hint=None, data: dict | None = None):
    preferred = _get_preferred_party_type(user, data)

    supplier_ctx = (None, None, None, None)
    customer_ctx = (None, None, None, None)

    if preferred == "customer":
        customer_ctx = _get_customer_context_for_user(user, hint)
        # Fallback when role hint says customer but user is actually supplier-linked.
        if not customer_ctx[0]:
            supplier_ctx = _get_supplier_context_for_user(user, hint)
    elif preferred == "supplier":
        supplier_ctx = _get_supplier_context_for_user(user, hint)
        # Fallback when role hint says supplier but user is actually customer-linked.
        if not supplier_ctx[0]:
            customer_ctx = _get_customer_context_for_user(user, hint)
    else:
        supplier_ctx = _get_supplier_context_for_user(user, hint)
        customer_ctx = _get_customer_context_for_user(user, hint)

    return preferred, supplier_ctx, customer_ctx


def _get_canonical_org_profile_name(
    user: str,
    supplier_doc=None,
    owner_user: str | None = None,
    customer_doc=None,
    customer_owner_user: str | None = None,
):
    """
    Return the one Organization Module record that should be shared by all users
    under the same supplier/customer account.
    """
    profile_owner_user = owner_user or customer_owner_user
    party_doc = supplier_doc or customer_doc
    org_name = ""
    member_user_ids = []

    if supplier_doc:
        org_name = str(supplier_doc.get("supplier_name") or "").strip()
        member_user_ids = _get_supplier_member_user_ids(supplier_doc)
    elif customer_doc:
        org_name = str(customer_doc.get("customer_name") or "").strip()
        member_user_ids = _get_customer_member_user_ids(customer_doc)

    if party_doc:
        if profile_owner_user:
            owner_doc = frappe.db.exists("Organization Module", {"user": profile_owner_user})
            if owner_doc:
                return owner_doc

        if org_name:
            org_docs = frappe.get_all(
                "Organization Module",
                filters={"organization_name": org_name},
                fields=["name", "user", "modified"],
                order_by="modified desc",
                limit_page_length=200,
            )
            chosen = _pick_best_org_profile_name(org_docs, preferred_user=profile_owner_user)
            if chosen:
                return chosen

        # Legacy recovery: choose best profile among known account users.
        candidate_users = []
        for candidate in [profile_owner_user, _resolve_user_name(user) or user]:
            if candidate and candidate not in candidate_users:
                candidate_users.append(candidate)
        for member_user in member_user_ids:
            if member_user and member_user not in candidate_users:
                candidate_users.append(member_user)

        if candidate_users:
            profile_rows = frappe.get_all(
                "Organization Module",
                filters={"user": ["in", candidate_users]},
                fields=["name", "user", "modified"],
                order_by="modified desc",
                limit_page_length=500,
            )
            chosen = _pick_best_org_profile_name(profile_rows, preferred_user=profile_owner_user)
            if chosen:
                return chosen

    return frappe.db.exists("Organization Module", {"user": user})


def _apply_profile_fields(doc, data):
    """Map mixed camelCase/snake_case payload into Organization Module fields."""
    field_map = {
        "organization_name": ("organization_name", "organizationName"),
        "website": ("website",),
        "phone": ("phone",),
        "street": ("street",),
        "house_no": ("house_no", "houseNumber"),
        "postal_code": ("postal_code", "postalCode"),
        "city": ("city",),
        "country": ("country",),
        "type_of_market_operator": ("type_of_market_operator", "operatorType"),
        "logo": ("logo",),
    }

    for target_field, candidate_keys in field_map.items():
        value_found = False
        value = None
        for key in candidate_keys:
            if key in data:
                value = data.get(key)
                value_found = True
                break
        if value_found:
            doc.set(target_field, value)


def _organization_profile_score(doc) -> int:
    """Prefer complete profile docs over empty drafts."""
    score = 0
    for fieldname in (
        "organization_name",
        "website",
        "phone",
        "street",
        "house_no",
        "postal_code",
        "city",
        "country",
        "type_of_market_operator",
        "logo",
    ):
        if str(doc.get(fieldname) or "").strip():
            score += 1
    score += len(doc.get("certificates") or []) * 3
    return score


def _pick_best_org_profile_name(profile_rows, preferred_user: str | None = None) -> str | None:
    """
    Choose canonical profile among candidates:
    1) preferred user profile (owner) if present
    2) highest completeness score
    3) latest modified
    """
    if not profile_rows:
        return None

    preferred_norm = _normalize_email(preferred_user)
    if preferred_norm:
        for row in profile_rows:
            if _normalize_email(row.get("user")) == preferred_norm:
                return row.get("name")

    best_name = None
    best_score = -1
    best_modified = ""

    for row in profile_rows:
        name = row.get("name")
        if not name:
            continue
        try:
            doc = frappe.get_doc("Organization Module", name)
        except Exception:
            continue

        score = _organization_profile_score(doc)
        modified = str(row.get("modified") or "")
        if score > best_score or (score == best_score and modified > best_modified):
            best_name = name
            best_score = score
            best_modified = modified

    return best_name


def _merge_legacy_member_profile_certificates(
    canonical_profile_name,
    supplier_doc=None,
    customer_doc=None,
    owner_user=None,
):
    """
    Backfill certificates from old per-member Organization Module records into the
    canonical account-shared profile (supplier/customer).
    """
    if not canonical_profile_name:
        return

    try:
        if supplier_doc:
            member_user_ids = _get_supplier_member_user_ids(supplier_doc)
        elif customer_doc:
            member_user_ids = _get_customer_member_user_ids(customer_doc)
        else:
            member_user_ids = []

        if owner_user and owner_user not in member_user_ids:
            member_user_ids.insert(0, owner_user)
        if not member_user_ids:
            return

        source_profile_names = []
        for user_id in member_user_ids:
            for profile_name in frappe.get_all("Organization Module", filters={"user": user_id}, pluck="name"):
                if profile_name and profile_name != canonical_profile_name and profile_name not in source_profile_names:
                    source_profile_names.append(profile_name)

        if not source_profile_names:
            return

        canonical_doc = frappe.get_doc("Organization Module", canonical_profile_name)
        existing_keys = {
            (
                c.certificate_name,
                c.valid_from,
                c.valid_to,
                c.attachment,
            )
            for c in (canonical_doc.get("certificates") or [])
        }

        changed = False
        for source_name in source_profile_names:
            source_doc = frappe.get_doc("Organization Module", source_name)
            for cert in (source_doc.get("certificates") or []):
                cert_key = (cert.certificate_name, cert.valid_from, cert.valid_to, cert.attachment)
                if cert_key in existing_keys:
                    continue

                canonical_doc.append("certificates", {
                    "certificate_name": cert.certificate_name,
                    "evidence_type": cert.evidence_type,
                    "valid_from": cert.valid_from,
                    "valid_to": cert.valid_to,
                    "attachment": cert.attachment,
                })
                existing_keys.add(cert_key)
                changed = True

        if changed:
            canonical_doc.save(ignore_permissions=True)
            frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Legacy Organization Profile Certificate Merge Error")


@frappe.whitelist(allow_guest=False)
def get_profile_for_user():
    """
    Fetch Organization Module document linked to the logged-in user,
    including its certificate child records.
    """
    user = frappe.session.user
    organization_members = []
    can_manage_members = False
    can_manage_profile = False
    can_manage_certificates = False
    can_manage_questionnaires = False
    can_manage_purchase_orders = False
    can_manage_plots = False
    member_permissions = _supplier_permissions_map(set(), False)
    member_role = "viewer"
    member_role_label = SUPPLIER_MEMBER_ROLE_LABELS["viewer"]
    is_owner_account = False

    _preferred, supplier_ctx, customer_ctx = _get_role_aware_party_contexts(user)
    supplier_name, supplier_doc, owner_user, _supplier_org_name = supplier_ctx
    customer_name, customer_doc, customer_owner_user, _customer_org_name = customer_ctx

    if supplier_doc:
        supplier_permission_ctx = _get_supplier_permission_context(user, supplier_name)
        member_permissions = supplier_permission_ctx.get("permissions") or member_permissions
        member_role = supplier_permission_ctx.get("member_role") or member_role
        member_role_label = supplier_permission_ctx.get("member_role_label") or member_role_label
        is_owner_account = bool(supplier_permission_ctx.get("is_owner"))
        can_manage_members = bool(member_permissions.get(SUPPLIER_PERMISSION_USER_MANAGER))
        can_manage_profile = bool(member_permissions.get(SUPPLIER_PERMISSION_SUPPLIER_ACCOUNT_MANAGER))
        can_manage_certificates = bool(member_permissions.get(SUPPLIER_PERMISSION_CERTIFICATE_MANAGER))
        can_manage_questionnaires = bool(member_permissions.get(SUPPLIER_PERMISSION_QUESTIONNAIRE_MANAGER))
        can_manage_purchase_orders = bool(member_permissions.get(SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER))
        can_manage_plots = bool(member_permissions.get(SUPPLIER_PERMISSION_PLOT_MANAGER))
    elif customer_doc:
        customer_permission_ctx = _get_customer_permission_context(user, customer_name)
        member_permissions = customer_permission_ctx.get("permissions") or member_permissions
        member_role = customer_permission_ctx.get("member_role") or member_role
        member_role_label = customer_permission_ctx.get("member_role_label") or member_role_label
        is_owner_account = bool(customer_permission_ctx.get("is_owner"))
        can_manage_members = bool(member_permissions.get(SUPPLIER_PERMISSION_USER_MANAGER))
        can_manage_profile = bool(member_permissions.get(SUPPLIER_PERMISSION_SUPPLIER_ACCOUNT_MANAGER))
        can_manage_certificates = bool(member_permissions.get(SUPPLIER_PERMISSION_CERTIFICATE_MANAGER))
        can_manage_questionnaires = bool(member_permissions.get(SUPPLIER_PERMISSION_QUESTIONNAIRE_MANAGER))
        can_manage_purchase_orders = bool(member_permissions.get(SUPPLIER_PERMISSION_PURCHASE_ORDER_MANAGER))
        can_manage_plots = bool(member_permissions.get(SUPPLIER_PERMISSION_PLOT_MANAGER))

    if supplier_name:
        member_table_fieldname = _get_member_table_fieldname(supplier_doc)
        member_rows = supplier_doc.get(member_table_fieldname, []) if member_table_fieldname else []
        supplier_member_meta = frappe.get_meta("Supplier User")
        organization_members = []
        for m in member_rows:
            permission_keys = _get_member_row_permission_keys(m, row_meta=supplier_member_meta)
            role_key = _normalize_supplier_member_role(getattr(m, "member_role", None))
            organization_members.append(
                {
                    "name": m.name,
                    "first_name": m.first_name,
                    "last_name": m.last_name,
                    "email": m.email,
                    "designation": m.designation,
                    "user_link": m.user_link,
                    "member_role": role_key,
                    "member_role_label": SUPPLIER_MEMBER_ROLE_LABELS.get(
                        role_key,
                        SUPPLIER_MEMBER_ROLE_LABELS["viewer"],
                    ),
                    "own_questionnaires_only": SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES in permission_keys,
                    "permissions": sorted(permission_keys),
                    "permission_labels": _permission_labels(permission_keys),
                }
            )
    elif customer_name:
        member_table_fieldname = _get_customer_member_table_fieldname(customer_doc)
        member_rows = customer_doc.get(member_table_fieldname, []) if member_table_fieldname else []
        customer_member_meta = frappe.get_meta("Customer User")
        organization_members = []
        for m in member_rows:
            permission_keys = _get_member_row_permission_keys(m, row_meta=customer_member_meta)
            role_key = _normalize_supplier_member_role(getattr(m, "member_role", None))
            organization_members.append(
                {
                    "name": m.name,
                    "first_name": m.first_name,
                    "last_name": m.last_name,
                    "email": m.email,
                    "designation": m.designation,
                    "user_link": m.user_link,
                    "member_role": role_key,
                    "member_role_label": SUPPLIER_MEMBER_ROLE_LABELS.get(
                        role_key,
                        SUPPLIER_MEMBER_ROLE_LABELS["viewer"],
                    ),
                    "own_questionnaires_only": SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES in permission_keys,
                    "permissions": sorted(permission_keys),
                    "permission_labels": _permission_labels(permission_keys),
                }
            )

    existing = _get_canonical_org_profile_name(
        user,
        supplier_doc=supplier_doc,
        owner_user=owner_user,
        customer_doc=customer_doc,
        customer_owner_user=customer_owner_user,
    )
    if not existing:
        organization_name = ""
        if supplier_doc:
            organization_name = str(supplier_doc.get("supplier_name") or "").strip()
        elif customer_doc:
            organization_name = str(customer_doc.get("customer_name") or "").strip()

        return {
            "name": "",
            "organization_name": organization_name,
            "website": "",
            "phone": "",
            "street": "",
            "house_no": "",
            "postal_code": "",
            "city": "",
            "country": "",
            "type_of_market_operator": "",
            "logo": "",
            "user": owner_user or customer_owner_user or user,
            "certificates": [],
            "custom_organization_members": organization_members,
            "can_manage_members": can_manage_members,
            "can_manage_profile": can_manage_profile,
            "can_manage_certificates": can_manage_certificates,
            "can_manage_questionnaires": can_manage_questionnaires,
            "can_manage_purchase_orders": can_manage_purchase_orders,
            "can_manage_plots": can_manage_plots,
            "member_permissions": member_permissions,
            "member_permission_labels": _permission_labels(
                {key for key, enabled in member_permissions.items() if enabled}
            ),
            "member_role": member_role,
            "member_role_label": member_role_label,
            "is_owner_account": is_owner_account,
        }

    if supplier_doc or customer_doc:
        _merge_legacy_member_profile_certificates(
            existing,
            supplier_doc=supplier_doc,
            customer_doc=customer_doc,
            owner_user=owner_user or customer_owner_user,
        )

    doc = frappe.get_doc("Organization Module", existing)

    # Return both organization info and certificates
    return {
        "name": doc.name,
        "organization_name": doc.organization_name,
        "website": doc.website,
        "phone": doc.phone,
        "street": doc.street,
        "house_no": doc.house_no,
        "postal_code": doc.postal_code,
        "city": doc.city,
        "country": doc.country,
        "type_of_market_operator": doc.type_of_market_operator,
        "logo": doc.logo,
        "user": doc.user,
        "certificates": [
            {
                "certificate_name": c.certificate_name,
                "evidence_type": c.evidence_type,
                "valid_from": c.valid_from,
                "valid_to": c.valid_to,
                "attachment": c.attachment,
            }
            for c in doc.get("certificates", [])
        ],
        "custom_organization_members": organization_members,
        "can_manage_members": can_manage_members,
        "can_manage_profile": can_manage_profile,
        "can_manage_certificates": can_manage_certificates,
        "can_manage_questionnaires": can_manage_questionnaires,
        "can_manage_purchase_orders": can_manage_purchase_orders,
        "can_manage_plots": can_manage_plots,
        "member_permissions": member_permissions,
        "member_permission_labels": _permission_labels(
            {key for key, enabled in member_permissions.items() if enabled}
        ),
        "member_role": member_role,
        "member_role_label": member_role_label,
        "is_owner_account": is_owner_account,
    }



@frappe.whitelist(methods=["POST"])
def save_profile(**payload):
    try:
        frappe.logger().info(f"Incoming payload: {payload}")
        data = payload.get("data", payload)
        if isinstance(data, str):
            data = json.loads(data)
        data = frappe._dict(data or {})

        frappe.logger().info(f"Parsed data: {data}")

        user = frappe.session.user
        frappe.logger().info(f"Session user: {user}")

        supplier_hint = (
            data.get("supplierName")
            or data.get("supplier_name")
            or data.get("customerName")
            or data.get("customer_name")
            or data.get("organizationName")
            or data.get("organization_name")
            or data.get("docname")
        )
        _preferred, supplier_ctx, customer_ctx = _get_role_aware_party_contexts(user, supplier_hint, data)
        _supplier_name, supplier_doc, owner_user, supplier_org_name = supplier_ctx
        _customer_name, customer_doc, customer_owner_user, customer_org_name = customer_ctx

        if supplier_doc:
            _require_supplier_permission(
                user,
                SUPPLIER_PERMISSION_SUPPLIER_ACCOUNT_MANAGER,
                supplier_hint=_supplier_name or supplier_hint,
                message=_("You are not allowed to manage supplier account settings"),
            )
        elif customer_doc:
            _require_customer_permission(
                user,
                SUPPLIER_PERMISSION_SUPPLIER_ACCOUNT_MANAGER,
                customer_hint=_customer_name or supplier_hint,
                message=_("You are not allowed to manage importer account settings"),
            )

        existing = _get_canonical_org_profile_name(
            user,
            supplier_doc=supplier_doc,
            owner_user=owner_user,
            customer_doc=customer_doc,
            customer_owner_user=customer_owner_user,
        )

        organization_name = str(data.get("organizationName") or data.get("organization_name") or "").strip()
        if not organization_name:
            organization_name = supplier_org_name or customer_org_name or ""

        if not organization_name and not existing:
            frappe.throw("Organization Name is required")

        if existing:
            doc = frappe.get_doc("Organization Module", existing)
            if not organization_name:
                organization_name = str(doc.get("organization_name") or "").strip()
        else:
            doc = frappe.new_doc("Organization Module")
            doc.user = owner_user or customer_owner_user or user

        if supplier_doc and owner_user:
            # Keep one supplier-shared profile owned by the primary supplier user.
            doc.user = owner_user
        elif customer_doc and customer_owner_user:
            # Keep one customer-shared profile owned by the primary importer user.
            doc.user = customer_owner_user

        if organization_name:
            data["organization_name"] = organization_name
            data["organizationName"] = organization_name

        _apply_profile_fields(doc, data)

        if existing:
            doc.save(ignore_permissions=True)
        else:
            doc.insert(ignore_permissions=True)

        frappe.db.commit()
        return {"name": doc.name}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Organization Module Save Error")
        frappe.throw(str(e))



@frappe.whitelist(allow_guest=False)
def get_profile():
    """
    Fetch the Organization Module document linked to the current user.
    """
    user = frappe.session.user

    _preferred, supplier_ctx, customer_ctx = _get_role_aware_party_contexts(user)
    _supplier_name, supplier_doc, owner_user, _supplier_org_name = supplier_ctx
    _customer_name, customer_doc, customer_owner_user, _customer_org_name = customer_ctx
    existing = _get_canonical_org_profile_name(
        user,
        supplier_doc=supplier_doc,
        owner_user=owner_user,
        customer_doc=customer_doc,
        customer_owner_user=customer_owner_user,
    )
    if not existing:
        return {"exists": False, "data": None}

    doc = frappe.get_doc("Organization Module", existing)
    return {
        "exists": True,
        "data": {
            "organization_name": doc.organization_name,
            "website": doc.website,
            "phone": doc.phone,
            "street": doc.street,
            "house_no": doc.house_no,
            "postal_code": doc.postal_code,
            "city": doc.city,
            "country": doc.country,
            "type_of_market_operator": doc.type_of_market_operator,
            "logo": doc.logo,
            "user": doc.user,
        }
    }





@frappe.whitelist(methods=["POST"])
def add_certificate(data: dict):
    """
    Add a certificate as a child record under Organization Module.
    """
    if isinstance(data, str):
        data = json.loads(data)
    data = data or {}

    user = frappe.session.user
    profile_name_hint = data.get("profileName") or data.get("profile_name")
    supplier_hint = (
        data.get("supplierName")
        or data.get("supplier_name")
        or data.get("customerName")
        or data.get("customer_name")
        or data.get("organizationName")
        or data.get("organization_name")
        or profile_name_hint
    )
    _preferred, supplier_ctx, customer_ctx = _get_role_aware_party_contexts(user, supplier_hint, data)
    _supplier_name, supplier_doc, owner_user, _supplier_org_name = supplier_ctx
    _customer_name, customer_doc, customer_owner_user, _customer_org_name = customer_ctx

    if supplier_doc:
        _require_supplier_permission(
            user,
            SUPPLIER_PERMISSION_CERTIFICATE_MANAGER,
            supplier_hint=_supplier_name or supplier_hint,
            message=_("You are not allowed to manage supplier certificates"),
        )
    elif customer_doc:
        _require_customer_permission(
            user,
            SUPPLIER_PERMISSION_CERTIFICATE_MANAGER,
            customer_hint=_customer_name or supplier_hint,
            message=_("You are not allowed to manage importer certificates"),
        )

    profile_name = _get_canonical_org_profile_name(
        user,
        supplier_doc=supplier_doc,
        owner_user=owner_user,
        customer_doc=customer_doc,
        customer_owner_user=customer_owner_user,
    )

    # Non-supplier fallback (or legacy direct profile access for own record)
    if not profile_name and profile_name_hint and frappe.db.exists("Organization Module", profile_name_hint):
        hinted_doc = frappe.get_doc("Organization Module", profile_name_hint)
        if hinted_doc.user == user:
            profile_name = hinted_doc.name

    if not profile_name:
        frappe.throw(_("Organization profile not found for this user"))

    certificate_name = data.get("certificateName") or data.get("certificate_name")
    if not certificate_name:
        frappe.throw(_("Certificate Name is required"))

    valid_from = data.get("validFrom") or data.get("valid_from")
    valid_to = data.get("validTo") or data.get("valid_to")
    if not (valid_from and valid_to):
        frappe.throw(_("Valid From and Valid To are required"))

    doc = frappe.get_doc("Organization Module", profile_name)
    doc.append("certificates", {
        "certificate_name": certificate_name,
        "evidence_type": data.get("evidenceType") or data.get("evidence_type"),
        "valid_from": valid_from,
        "valid_to": valid_to,
        "attachment": data.get("fileUrl") or data.get("file_url"),
    })
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {"message": "Certificate added successfully", "parent": doc.name}
    

@frappe.whitelist()
def delete_certificate(profile_name=None, certificate_name=None, **kwargs):
    payload = kwargs.get("data")
    if isinstance(payload, str):
        payload = json.loads(payload)
    payload = payload or kwargs

    if payload:
        profile_name = payload.get("profile_name") or payload.get("profileName") or profile_name
        certificate_name = payload.get("certificate_name") or payload.get("certificateName") or certificate_name

    if not certificate_name:
        frappe.throw(_("Certificate Name is required"))

    user = frappe.session.user
    supplier_hint = (
        payload.get("supplierName")
        or payload.get("supplier_name")
        or payload.get("customerName")
        or payload.get("customer_name")
        or payload.get("organizationName")
        or payload.get("organization_name")
        or profile_name
    )
    _preferred, supplier_ctx, customer_ctx = _get_role_aware_party_contexts(user, supplier_hint, payload)
    _supplier_name, supplier_doc, owner_user, _supplier_org_name = supplier_ctx
    _customer_name, customer_doc, customer_owner_user, _customer_org_name = customer_ctx

    if supplier_doc:
        _require_supplier_permission(
            user,
            SUPPLIER_PERMISSION_CERTIFICATE_MANAGER,
            supplier_hint=_supplier_name or supplier_hint,
            message=_("You are not allowed to manage supplier certificates"),
        )
    elif customer_doc:
        _require_customer_permission(
            user,
            SUPPLIER_PERMISSION_CERTIFICATE_MANAGER,
            customer_hint=_customer_name or supplier_hint,
            message=_("You are not allowed to manage importer certificates"),
        )

    canonical_profile_name = _get_canonical_org_profile_name(
        user,
        supplier_doc=supplier_doc,
        owner_user=owner_user,
        customer_doc=customer_doc,
        customer_owner_user=customer_owner_user,
    )

    if not canonical_profile_name and profile_name and frappe.db.exists("Organization Module", profile_name):
        hinted_doc = frappe.get_doc("Organization Module", profile_name)
        if hinted_doc.user == user:
            canonical_profile_name = hinted_doc.name

    if not canonical_profile_name:
        frappe.throw(_("Organization profile not found for this user"))

    profile = frappe.get_doc("Organization Module", canonical_profile_name)
    for cert in profile.get("certificates"):
        if cert.certificate_name == certificate_name:
            profile.remove(cert)
            profile.save(ignore_permissions=True)
            frappe.db.commit()
            return {"success": True, "message": f"Certificate '{certificate_name}' deleted"}
    frappe.throw(f"Certificate '{certificate_name}' not found")




def manage_organization_users(doc, method):
    """
    Syncs the custom organization members child table with System Users.
    Run on Supplier/Customer validate.
    """
    doctype = str(getattr(doc, "doctype", "") or "")
    if doctype == "Supplier":
        member_table_fieldname = _get_member_table_fieldname(doc)
        role_name = "Supplier"
        link_doctype = "Supplier"
    elif doctype == "Customer":
        member_table_fieldname = _get_customer_member_table_fieldname(doc)
        role_name = "Customer"
        link_doctype = "Customer"
    else:
        return

    if not member_table_fieldname:
        return

    for member in (doc.get(member_table_fieldname) or []):
        if not member.email:
            continue

        # Check if User exists
        if not frappe.db.exists("User", member.email):
            # 1. Create New User
            user = frappe.get_doc({
                "doctype": "User",
                "email": member.email,
                "first_name": member.first_name,
                "last_name": member.last_name,
                "enabled": 1,
                "send_welcome_email": 1,
                "roles": [{"role": role_name}]
            })
            user.insert(ignore_permissions=True)
            
            # 2. Link User ID back to the child table row
            member.user_link = user.name
            
            # 3. Ensure Contact Exists (Vital for permissions)
            create_contact_link(user, member, doc.name, link_doctype)
        
        else:
            # User exists, ensure role + link + contact are correct
            user_name = _resolve_user_name(member.user_link or member.email) or member.email
            user_doc = frappe.get_doc("User", user_name)

            # Existing users may have been created under a different account type.
            if not any((r.role or "") == role_name for r in (user_doc.get("roles") or [])):
                user_doc.append("roles", {"role": role_name})
                user_doc.save(ignore_permissions=True)

            if not member.user_link:
                member.user_link = user_doc.name

            create_contact_link(user_doc, member, doc.name, link_doctype)


def create_contact_link(user, member, party_name, party_doctype="Supplier"):
    """
    Ensures a Contact exists linking this User to this party.
    """
    contact_name = frappe.db.get_value("Contact", {"email_id": user.email})
    
    if not contact_name:
        contact = frappe.get_doc({
            "doctype": "Contact",
            "first_name": member.first_name,
            "last_name": member.last_name,
            "email_id": user.email,
            "user": user.name,
            "links": [{"link_doctype": party_doctype, "link_name": party_name}]
        })
        contact.insert(ignore_permissions=True)
    else:
        # Check if already linked to this party
        contact = frappe.get_doc("Contact", contact_name)
        is_linked = any(l.link_name == party_name and l.link_doctype == party_doctype for l in contact.links)
        
        if not is_linked:
            contact.append("links", {
                "link_doctype": party_doctype,
                "link_name": party_name
            })
            contact.save(ignore_permissions=True)
            
            
def _resolve_member_owner_context(actor_user, data):
    requested_party_type = _get_preferred_party_type(actor_user, data)
    hint = (
        data.get("supplierName")
        or data.get("supplier_name")
        or data.get("customerName")
        or data.get("customer_name")
        or data.get("organizationName")
        or data.get("organization_name")
    )

    supplier_name = None
    customer_name = None
    if requested_party_type == "customer":
        customer_name = _get_customer_for_user(actor_user, hint)
        if not customer_name:
            supplier_name = _get_supplier_for_user(actor_user, hint)
    elif requested_party_type == "supplier":
        supplier_name = _get_supplier_for_user(actor_user, hint)
        if not supplier_name:
            customer_name = _get_customer_for_user(actor_user, hint)
    else:
        supplier_name = _get_supplier_for_user(actor_user, hint)
        customer_name = _get_customer_for_user(actor_user, hint)

    if supplier_name:
        doc = frappe.get_doc("Supplier", supplier_name)
        if not _can_manage_supplier_members(doc, actor_user):
            frappe.throw(
                _("Only the parent supplier account administrator can manage members for this supplier"),
                frappe.PermissionError,
            )
        member_table_fieldname = _get_member_table_fieldname(doc)
        if not member_table_fieldname:
            frappe.throw(
                _("Supplier member table is not configured. Please add a Supplier table field pointing to 'Supplier User'.")
            )
        return {
            "party_type": "supplier",
            "party_name": supplier_name,
            "doc": doc,
            "member_table_fieldname": member_table_fieldname,
            "limit": MAX_SUPPLIER_MEMBERS,
        }

    if customer_name:
        doc = frappe.get_doc("Customer", customer_name)
        if not _can_manage_customer_members(doc, actor_user):
            frappe.throw(_("You are not allowed to manage members for this importer"), frappe.PermissionError)
        member_table_fieldname = _get_customer_member_table_fieldname(doc)
        if not member_table_fieldname:
            frappe.throw(
                _("Importer member table is not configured. Please add a Customer table field pointing to 'Customer User'.")
            )
        return {
            "party_type": "customer",
            "party_name": customer_name,
            "doc": doc,
            "member_table_fieldname": member_table_fieldname,
            "limit": MAX_CUSTOMER_MEMBERS,
        }

    if requested_party_type == "customer":
        frappe.throw(_("No importer account found linked to this user."))
    if requested_party_type == "supplier":
        frappe.throw(_("No supplier account found linked to this user."))
    frappe.throw(_("No supplier or importer account found linked to this user."))


@frappe.whitelist(methods=["POST"])
def add_member(**kwargs):
    try:
        data = kwargs.get("data")
        if data is None:
            data = kwargs
        if isinstance(data, str):
            data = json.loads(data)
        data = data or {}

        email = (data.get("email") or "").strip()
        if not email:
            frappe.throw(_("Email is required"))
        email_norm = _normalize_email(email)

        actor_user = frappe.session.user
        owner_ctx = _resolve_member_owner_context(actor_user, data)
        doc = owner_ctx["doc"]
        member_table_fieldname = owner_ctx["member_table_fieldname"]
        existing_members = doc.get(member_table_fieldname) or []
        member_limit = owner_ctx["limit"]

        requested_permissions = _parse_requested_permission_keys(
            data.get("permissions") or data.get("permission_keys")
        )
        if not requested_permissions and (data.get("memberRole") or data.get("member_role")):
            role_key = _resolve_requested_member_role(data)
            requested_permissions.update(SUPPLIER_MEMBER_ROLE_CAPABILITIES.get(role_key, set()))
        if _parse_bool(data.get("ownQuestionnairesOnly", data.get("own_questionnaires_only")), default=False):
            requested_permissions.add(SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES)

        if len(existing_members) >= member_limit:
            frappe.throw(_("Maximum {0} members are allowed per organization").format(member_limit))

        for member in existing_members:
            if _normalize_email(member.email) == email_norm:
                frappe.throw(_("Member {0} already exists").format(email))

        # If this user existed previously and was disabled, re-enable on re-invite.
        existing_user_name = _resolve_user_name(email)
        if existing_user_name and frappe.db.exists("User", existing_user_name):
            enabled = frappe.db.get_value("User", existing_user_name, "enabled")
            if str(enabled).strip() in ("0", "False", "false", ""):
                frappe.db.set_value("User", existing_user_name, "enabled", 1, update_modified=False)
                frappe.cache.delete_key("enabled_users")

        row_data = {
            "first_name": data.get("firstName"),
            "last_name": data.get("lastName"),
            "email": email,
            "designation": data.get("designation") or data.get("deisgnation"),
        }

        row_doctype = "Supplier User" if owner_ctx["party_type"] == "supplier" else "Customer User"
        row_meta = frappe.get_meta(row_doctype)

        if row_meta.has_field("member_role"):
            row_data["member_role"] = SUPPLIER_MEMBER_ROLE_LABELS["viewer"]
        for permission_key, fieldname in SUPPLIER_ROW_PERMISSION_FIELDS.items():
            if row_meta.has_field(fieldname):
                row_data[fieldname] = 1 if permission_key in requested_permissions else 0
        if row_meta.has_field("own_questionnaires_only"):
            row_data["own_questionnaires_only"] = 1 if SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES in requested_permissions else 0

        doc.append(member_table_fieldname, row_data)

        # Triggers validate hooks to provision User + Contact link.
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        if owner_ctx["party_type"] == "customer":
            return {"message": "Member added to Importer"}
        return {"message": "Member added to Supplier"}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Add Member Error")
        frappe.throw(str(e))



@frappe.whitelist(methods=["POST"])
def update_member(**kwargs):
    try:
        data = kwargs.get("data")
        if data is None:
            data = kwargs
        if isinstance(data, str):
            data = json.loads(data)
        data = data or {}

        email = (data.get("email") or "").strip()
        member_id = data.get("memberId") or data.get("member_id") or data.get("memberName")
        if not email and not member_id:
            frappe.throw(_("Email or memberId is required"))
        email_norm = _normalize_email(email)

        actor_user = frappe.session.user
        owner_ctx = _resolve_member_owner_context(actor_user, data)
        doc = owner_ctx["doc"]
        member_table_fieldname = owner_ctx["member_table_fieldname"]
        members_list = doc.get(member_table_fieldname) or []

        target_row = None
        if member_id:
            target_row = next((row for row in members_list if row.name == member_id), None)
        if not target_row and email_norm:
            target_row = next(
                (
                    row
                    for row in members_list
                    if _normalize_email(row.email) == email_norm
                    or _normalize_email(getattr(row, "user_link", "")) == email_norm
                    or _normalize_email(getattr(row, "user", "")) == email_norm
                ),
                None,
            )
        if not target_row:
            frappe.throw(_("Member not found"))

        requested_permissions = _parse_requested_permission_keys(
            data.get("permissions") or data.get("permission_keys")
        )
        if _parse_bool(data.get("ownQuestionnairesOnly", data.get("own_questionnaires_only")), default=False):
            requested_permissions.add(SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES)

        row_doctype = "Supplier User" if owner_ctx["party_type"] == "supplier" else "Customer User"
        row_meta = frappe.get_meta(row_doctype)

        for permission_key, fieldname in SUPPLIER_ROW_PERMISSION_FIELDS.items():
            if row_meta.has_field(fieldname):
                setattr(target_row, fieldname, 1 if permission_key in requested_permissions else 0)
        if row_meta.has_field("own_questionnaires_only"):
            setattr(
                target_row,
                "own_questionnaires_only",
                1 if SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES in requested_permissions else 0,
            )
        if row_meta.has_field("member_role"):
            setattr(target_row, "member_role", SUPPLIER_MEMBER_ROLE_LABELS["viewer"])

        if "designation" in data or "deisgnation" in data:
            target_row.designation = data.get("designation") or data.get("deisgnation") or ""
        if "firstName" in data or "first_name" in data:
            target_row.first_name = data.get("firstName") or data.get("first_name") or target_row.first_name
        if "lastName" in data or "last_name" in data:
            target_row.last_name = data.get("lastName") or data.get("last_name") or target_row.last_name

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        final_permission_keys = _get_member_row_permission_keys(target_row, row_meta=row_meta)
        return {
            "message": "Member updated successfully",
            "member": {
                "name": target_row.name,
                "first_name": target_row.first_name,
                "last_name": target_row.last_name,
                "email": target_row.email,
                "designation": target_row.designation,
                "permissions": sorted(final_permission_keys),
                "permission_labels": _permission_labels(final_permission_keys),
                "own_questionnaires_only": SUPPLIER_PERMISSION_OWN_QUESTIONNAIRES in final_permission_keys,
            },
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Update Member Error")
        frappe.throw(str(e))


@frappe.whitelist(methods=["POST"])
def remove_member(**kwargs):
    try:
        data = kwargs.get("data")
        if data is None:
            data = kwargs
        if isinstance(data, str):
            data = json.loads(data)

        email = (data.get("email") or "").strip()
        member_id = data.get("memberId") or data.get("member_id") or data.get("memberName")

        if not email and not member_id:
            frappe.throw(_("Email or memberId is required"))
        email_norm = _normalize_email(email)

        actor_user = frappe.session.user
        owner_ctx = _resolve_member_owner_context(actor_user, data)
        doc = owner_ctx["doc"]
        member_table_fieldname = owner_ctx["member_table_fieldname"]

        members_list = doc.get(member_table_fieldname) or []
        rows_to_remove = []

        if member_id:
            rows_to_remove = [row for row in members_list if row.name == member_id]

        if not rows_to_remove and email_norm:
            rows_to_remove = [
                row for row in members_list
                if _normalize_email(row.email) == email_norm
                or _normalize_email(getattr(row, "user_link", "")) == email_norm
                or _normalize_email(getattr(row, "user", "")) == email_norm
            ]

        if not rows_to_remove:
            frappe.throw(_("Member not found"))

        user_ids_to_remove = set()
        for row in rows_to_remove:
            for candidate in (getattr(row, "user_link", None), getattr(row, "user", None), row.email):
                resolved = _resolve_user_name(candidate)
                if resolved:
                    user_ids_to_remove.add(resolved)
            doc.remove(row)
            
        doc.save(ignore_permissions=True)
        frappe.db.commit() # Commit the changes
        
        # Also include payload email as a candidate user.
        if email_norm:
            resolved_from_payload = _resolve_user_name(email_norm)
            if resolved_from_payload:
                user_ids_to_remove.add(resolved_from_payload)

        deleted_users = []
        fallback_disabled_users = []
        preserved_users = []

        if user_ids_to_remove:
            for user_id in user_ids_to_remove:
                try:
                    if user_id in ("Administrator", "Guest"):
                        continue
                    if user_id == frappe.session.user:
                        preserved_users.append(user_id)
                        continue
                    if frappe.db.exists("User", user_id):
                        try:
                            frappe.delete_doc("User", user_id, ignore_permissions=True, force=1)
                            deleted_users.append(user_id)
                        except Exception:
                            # Fallback to disable only when hard delete is blocked by linked records.
                            frappe.db.set_value("User", user_id, "enabled", 0, update_modified=False)
                            fallback_disabled_users.append(user_id)
                except Exception:
                    frappe.log_error(frappe.get_traceback(), "Delete/Disable User Error (remove_member)")

            frappe.cache.delete_key("enabled_users")
            frappe.db.commit()

        return {
            "message": "Member removed successfully",
            "deleted_users": deleted_users,
            "fallback_disabled_users": fallback_disabled_users,
            "preserved_users": preserved_users,
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Remove Member Error")
        frappe.throw(str(e))
