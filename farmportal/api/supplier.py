import frappe
from frappe import _
from frappe.utils import now_datetime


def _coerce_page(value, default=1):
    try:
        page = int(value)
        return page if page > 0 else default
    except (TypeError, ValueError):
        return default


def _coerce_page_size(page_size=None, fallback_limit=100, default=25, max_size=100):
    candidate = page_size if page_size is not None else fallback_limit
    try:
        size = int(candidate)
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


def _normalize_email(value):
    return (value or "").strip().lower()


def _first_existing_supplier_field(candidates):
    try:
        meta = frappe.get_meta("Supplier")
    except Exception:
        return None

    for fieldname in candidates:
        if meta.has_field(fieldname):
            return fieldname
    return None


def _normalize_verification_status(value):
    raw = str(value or "").strip().lower()
    if raw in {"verified", "verify", "approved", "done", "complete", "completed"}:
        return "Verified"
    if raw in {"rejected", "reject", "declined"}:
        return "Rejected"
    return "Pending"


def _verification_default_key(supplier_name):
    return f"supplier_verification_status::{str(supplier_name or '').strip()}"


def _resolve_user_name(value):
    if not value:
        return None

    raw_value = str(value).strip()
    if not raw_value:
        return None

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


def _get_supplier_member_user_ids(supplier_name):
    """
    Resolve User IDs for supplier members from the Supplier User child table.
    """
    if not supplier_name:
        return []

    try:
        meta = frappe.get_meta("Supplier User")
    except Exception:
        return []

    fields = ["name"]
    candidate_fields = []
    for fieldname in ("user_link", "user", "email"):
        if meta.has_field(fieldname):
            fields.append(fieldname)
            candidate_fields.append(fieldname)

    if not candidate_fields:
        return []

    rows = frappe.get_all(
        "Supplier User",
        filters={
            "parenttype": "Supplier",
            "parent": supplier_name,
        },
        fields=fields,
        limit_page_length=500,
    )

    user_ids = []
    for row in rows:
        for fieldname in candidate_fields:
            resolved = _resolve_user_name(row.get(fieldname))
            if resolved and resolved not in user_ids:
                user_ids.append(resolved)

    return user_ids


@frappe.whitelist()
def create_supplier_with_user(name, email, country=None):
    """
    Creates a User, then a Supplier linked to that User, and sends a welcome email.
    """
    # 1. Validation
    if not name or not email:
        frappe.throw(_("Name and Email are required"))

    if frappe.db.exists("User", email):
        frappe.throw(_("A user with email {0} already exists").format(email))

    try:
        # 2. Create User
        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": name,
            "enabled": 1,
            "send_welcome_email": 1, # This triggers the standard welcome mail
            "roles": [{"role": "Supplier"}] # Assign Supplier Role
        })
        user.insert(ignore_permissions=True)

        # 3. Create Supplier
        supplier = frappe.get_doc({
            "doctype": "Supplier",
            "supplier_name": name,
            "country": country,
            "supplier_group": "All Supplier Groups", # Default required field
            "custom_user": user.name # Link the created user
        })
        supplier.insert(ignore_permissions=True)

        # 4. Commit
        frappe.db.commit()

        return {
            "message": "Supplier and User created successfully",
            "supplier": supplier.name,
            "user": user.name
        }

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Supplier Creation Error: {str(e)}")
        frappe.throw(_("Failed to create supplier: {0}").format(str(e)))
        

@frappe.whitelist()
def toggle_supplier_access(supplier_name, enable=0):
    """
    Disable/Enable login access for the Supplier owner and all supplier members.
    enable: 0 to disable, 1 to enable
    """
    if not supplier_name:
        frappe.throw(_("Supplier Name is required"))

    supplier = frappe.get_doc("Supplier", supplier_name)

    owner_user = _resolve_user_name(supplier.get("custom_user"))
    if not owner_user:
        frappe.throw(_("This supplier is not linked to a User account"))

    enable_flag = 1 if int(enable) else 0

    user_ids = [owner_user]
    for member_user in _get_supplier_member_user_ids(supplier.name):
        if member_user not in user_ids:
            user_ids.append(member_user)

    updated_users = []
    skipped_users = []
    for user_id in user_ids:
        if user_id in ("Administrator", "Guest"):
            skipped_users.append(user_id)
            continue
        if not frappe.db.exists("User", user_id):
            skipped_users.append(user_id)
            continue
        frappe.db.set_value("User", user_id, "enabled", enable_flag, update_modified=False)
        updated_users.append(user_id)

    frappe.cache.delete_key("enabled_users")
    frappe.db.commit()

    status = "Enabled" if enable_flag else "Disabled"
    return {
        "message": f"Supplier access {status}",
        "enabled": enable_flag,
        "updated_users_count": len(updated_users),
        "skipped_users_count": len(skipped_users),
    }


@frappe.whitelist()
def get_suppliers(search=None, limit=100, page=1, page_size=None):
    """
    Get suppliers linked to a User, including their email and enabled status.
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    page_no = _coerce_page(page, default=1)
    page_limit = _coerce_page_size(page_size=page_size, fallback_limit=limit, default=25, max_size=100)
    offset = (page_no - 1) * page_limit
    verification_field = _first_existing_supplier_field(("custom_verification_status", "verification_status"))
    verification_select = (
        f", s.`{verification_field}` as verification_status"
        if verification_field
        else ", 'Pending' as verification_status"
    )

    # Prepare search condition
    search_condition = ""
    params = {}
    if search:
        search_condition = """
            AND (
                s.supplier_name LIKE %(search)s 
                OR s.name LIKE %(search)s
                OR u.email LIKE %(search)s
            )
        """
        params["search"] = f"%{search}%"

    # SQL Query with Join to get User details (email, enabled status)
    # We filter by s.disabled = 0 (Supplier doctype status)
    # We DO NOT filter by u.enabled so we can see disabled users in the list
    base_from_where = f"""
        SELECT 
            s.name, 
            s.supplier_name, 
            s.country, 
            s.custom_user,
            u.email, 
            u.enabled as user_enabled
            {verification_select}
        FROM `tabSupplier` s
        JOIN `tabUser` u ON s.custom_user = u.name
        WHERE 
            s.disabled = 0
            AND s.custom_user IS NOT NULL 
            AND s.custom_user != ''
            {search_condition}
    """

    count_query = f"""
        SELECT COUNT(*) AS total
        FROM `tabSupplier` s
        JOIN `tabUser` u ON s.custom_user = u.name
        WHERE 
            s.disabled = 0
            AND s.custom_user IS NOT NULL 
            AND s.custom_user != ''
            {search_condition}
    """
    total_row = frappe.db.sql(count_query, params, as_dict=True) or []
    total = int((total_row[0] or {}).get("total") or 0)

    query = f"""
        {base_from_where}
        ORDER BY s.supplier_name ASC
        LIMIT {page_limit}
        OFFSET {offset}
    """

    data = frappe.db.sql(query, params, as_dict=True)

    supplier_names = [str(row.get("name") or "").strip() for row in data if row.get("name")]
    supplier_labels = [str(row.get("supplier_name") or row.get("name") or "").strip() for row in data if row.get("name")]
    owner_users = [str(row.get("custom_user") or "").strip() for row in data if row.get("custom_user")]

    profile_by_supplier = {}
    members_by_supplier = {}
    certificates_by_profile = {}

    try:
        # 1) Supplier members (shared organization users) keyed by Supplier.name
        if supplier_names:
            member_rows = frappe.get_all(
                "Supplier User",
                filters={
                    "parenttype": "Supplier",
                    "parent": ["in", supplier_names],
                },
                fields=["parent", "name", "first_name", "last_name", "email", "designation", "user_link"],
                order_by="idx asc",
                limit_page_length=max(1000, len(supplier_names) * 50),
            )
            for member in member_rows:
                parent = str(member.get("parent") or "").strip()
                if not parent:
                    continue
                members_by_supplier.setdefault(parent, []).append(
                    {
                        "name": member.get("name"),
                        "first_name": member.get("first_name"),
                        "last_name": member.get("last_name"),
                        "email": member.get("email"),
                        "designation": member.get("designation"),
                        "user_link": member.get("user_link"),
                    }
                )

        # 2) Organization profile lookup (primary by supplier label, fallback by owner user)
        profile_fields = [
            "name",
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
            "user",
            "modified",
        ]

        profile_by_org_name = {}
        if supplier_labels:
            org_profiles = frappe.get_all(
                "Organization Module",
                filters={"organization_name": ["in", supplier_labels]},
                fields=profile_fields,
                order_by="modified desc",
                limit_page_length=max(500, len(supplier_labels) * 5),
            )
            for profile in org_profiles:
                org_key = str(profile.get("organization_name") or "").strip()
                if org_key and org_key not in profile_by_org_name:
                    profile_by_org_name[org_key] = profile

        profile_by_owner_user = {}
        if owner_users:
            owner_profiles = frappe.get_all(
                "Organization Module",
                filters={"user": ["in", owner_users]},
                fields=profile_fields,
                order_by="modified desc",
                limit_page_length=max(500, len(owner_users) * 5),
            )
            for profile in owner_profiles:
                owner_key = str(profile.get("user") or "").strip()
                if owner_key and owner_key not in profile_by_owner_user:
                    profile_by_owner_user[owner_key] = profile

        selected_profile_names = []
        for row in data:
            supplier_key = str(row.get("name") or "").strip()
            supplier_label = str(row.get("supplier_name") or row.get("name") or "").strip()
            owner_key = str(row.get("custom_user") or "").strip()
            profile = profile_by_org_name.get(supplier_label) or profile_by_owner_user.get(owner_key)
            if not profile or not supplier_key:
                continue

            profile_by_supplier[supplier_key] = profile
            profile_name = str(profile.get("name") or "").strip()
            if profile_name and profile_name not in selected_profile_names:
                selected_profile_names.append(profile_name)

        # 3) Certificates keyed by Organization Module profile
        if selected_profile_names:
            cert_rows = frappe.get_all(
                "Organization Certificate",
                filters={
                    "parenttype": "Organization Module",
                    "parent": ["in", selected_profile_names],
                },
                fields=["parent", "certificate_name", "evidence_type", "valid_from", "valid_to", "attachment"],
                order_by="idx asc",
                limit_page_length=max(1000, len(selected_profile_names) * 20),
            )
            for cert in cert_rows:
                profile_name = str(cert.get("parent") or "").strip()
                if not profile_name:
                    continue
                certificates_by_profile.setdefault(profile_name, []).append(
                    {
                        "certificate_name": cert.get("certificate_name"),
                        "evidence_type": cert.get("evidence_type"),
                        "valid_from": cert.get("valid_from"),
                        "valid_to": cert.get("valid_to"),
                        "attachment": cert.get("attachment"),
                    }
                )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Supplier Profile Enrichment Error")

    # Format response for frontend
    suppliers = []
    for row in data:
        supplier_key = str(row.get("name") or "").strip()
        member_rows = members_by_supplier.get(supplier_key, [])
        profile_row = profile_by_supplier.get(supplier_key)

        organization_profile = None
        certificates = []
        if profile_row:
            profile_name = str(profile_row.get("name") or "").strip()
            certificates = certificates_by_profile.get(profile_name, [])
            organization_profile = {
                "name": profile_name,
                "organization_name": profile_row.get("organization_name"),
                "website": profile_row.get("website"),
                "phone": profile_row.get("phone"),
                "street": profile_row.get("street"),
                "house_no": profile_row.get("house_no"),
                "postal_code": profile_row.get("postal_code"),
                "city": profile_row.get("city"),
                "country": profile_row.get("country"),
                "type_of_market_operator": profile_row.get("type_of_market_operator"),
                "logo": profile_row.get("logo"),
                "certificates": certificates,
                "members": member_rows,
            }

        suppliers.append(
            {
                "_id": row.name,
                "name": row.name,
                "supplier_name": row.supplier_name or row.name,  # Display name
                "country": row.country,
                "user": row.custom_user,
                "email_id": row.email,  # For displaying contact email
                "user_enabled": row.user_enabled,  # 1 or 0
                "has_profile": bool(organization_profile),
                "members_count": len(member_rows),
                "certificates_count": len(certificates),
                "verification_status": _normalize_verification_status(
                    row.get("verification_status")
                    if verification_field
                    else frappe.defaults.get_global_default(_verification_default_key(row.name))
                ),
                "organization_members": member_rows,
                "organization_profile": organization_profile,
            }
        )
    
    return {
        "suppliers": suppliers,
        "pagination": _build_pagination(page_no, page_limit, total),
    }


@frappe.whitelist()
def update_supplier_verification_status(supplier_name, verification_status="Pending"):
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    supplier_name = str(supplier_name or "").strip()
    if not supplier_name:
        frappe.throw(_("Supplier Name is required"))

    if not frappe.db.exists("Supplier", supplier_name):
        frappe.throw(_("Supplier not found"))

    from farmportal.api.requests import _get_party_from_user

    customer_name, _supplier_name = _get_party_from_user(user)
    is_system_manager = "System Manager" in frappe.get_roles(user)
    if not customer_name and not is_system_manager:
        frappe.throw(_("Only importer users can update supplier verification status"), frappe.PermissionError)

    verification_field = _first_existing_supplier_field(("custom_verification_status", "verification_status"))
    normalized_status = _normalize_verification_status(verification_status)
    if verification_field:
        updates = {verification_field: normalized_status}

        verified_by_field = _first_existing_supplier_field(("custom_verified_by", "verified_by"))
        verified_on_field = _first_existing_supplier_field(("custom_verified_on", "verified_on"))

        if normalized_status == "Verified":
            if verified_by_field:
                updates[verified_by_field] = user
            if verified_on_field:
                updates[verified_on_field] = now_datetime()
        else:
            if verified_by_field:
                updates[verified_by_field] = None
            if verified_on_field:
                updates[verified_on_field] = None

        frappe.db.set_value("Supplier", supplier_name, updates, update_modified=True)
    else:
        frappe.defaults.set_global_default(_verification_default_key(supplier_name), normalized_status)

    frappe.db.commit()

    return {
        "message": _("Supplier verification status updated"),
        "supplier_name": supplier_name,
        "verification_status": normalized_status,
    }


def _normalize_file_url(value):
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized.startswith(("http://", "https://")):
        try:
            from urllib.parse import urlparse
            parsed = urlparse(normalized)
            normalized = parsed.path or normalized
        except Exception:
            pass
    return normalized


@frappe.whitelist()
def download_supplier_profile_attachment(supplier_name, file_url=None, file_name=None):
    """Download supplier profile certificate attachment with permission checks."""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    supplier_name = str(supplier_name or "").strip()
    if not supplier_name:
        frappe.throw(_("supplier_name is required"))

    supplier_doc = frappe.get_doc("Supplier", supplier_name)

    # Permission model:
    # - Importer (Customer-linked user): can view supplier profile attachments in Browse Suppliers.
    # - Supplier-linked user: only for their own supplier profile.
    from farmportal.api.requests import _get_party_from_user

    customer_name, supplier_link = _get_party_from_user(user)
    supplier_link = str(supplier_link or "").strip()

    has_customer_access = bool(customer_name)
    has_same_supplier_access = bool(supplier_link and supplier_link == supplier_name)

    if not (has_customer_access or has_same_supplier_access):
        frappe.throw(_("Not permitted to download this attachment"), frappe.PermissionError)

    supplier_label = str(supplier_doc.get("supplier_name") or supplier_doc.name or "").strip()
    supplier_owner = str(supplier_doc.get("custom_user") or "").strip()

    profile_name = None
    if supplier_label:
        profile_rows = frappe.get_all(
            "Organization Module",
            filters={"organization_name": supplier_label},
            fields=["name"],
            order_by="modified desc",
            limit=1,
        )
        if profile_rows:
            profile_name = str(profile_rows[0].get("name") or "").strip()

    if not profile_name and supplier_owner:
        profile_rows = frappe.get_all(
            "Organization Module",
            filters={"user": supplier_owner},
            fields=["name"],
            order_by="modified desc",
            limit=1,
        )
        if profile_rows:
            profile_name = str(profile_rows[0].get("name") or "").strip()

    if not profile_name:
        frappe.throw(_("Supplier profile not found"), frappe.DoesNotExistError)

    cert_rows = frappe.get_all(
        "Organization Certificate",
        filters={
            "parenttype": "Organization Module",
            "parent": profile_name,
        },
        fields=["attachment"],
        limit_page_length=500,
    )

    allowed_urls = {
        _normalize_file_url(row.get("attachment"))
        for row in cert_rows
        if row.get("attachment")
    }
    allowed_urls = {u for u in allowed_urls if u}

    if not allowed_urls:
        frappe.throw(_("Attachment not found"), frappe.DoesNotExistError)

    normalized_url = _normalize_file_url(file_url)
    if normalized_url and normalized_url not in allowed_urls:
        frappe.throw(_("Not permitted to download this attachment"), frappe.PermissionError)

    filters = {}
    if file_name:
        filters["name"] = str(file_name).strip()
    elif normalized_url:
        filters["file_url"] = normalized_url
    else:
        frappe.throw(_("file_url or file_name is required"))

    file_rows = frappe.get_all(
        "File",
        filters=filters,
        fields=["name", "file_name", "file_url"],
        order_by="creation desc",
        limit=1,
    )

    if not file_rows:
        frappe.throw(_("Attachment not found"), frappe.DoesNotExistError)

    selected_file = file_rows[0]
    selected_url = _normalize_file_url(selected_file.get("file_url"))
    if selected_url and selected_url not in allowed_urls:
        frappe.throw(_("Not permitted to download this attachment"), frappe.PermissionError)

    file_doc = frappe.get_doc("File", selected_file["name"])
    frappe.local.response.filename = selected_file.get("file_name") or file_doc.file_name or file_doc.name
    frappe.local.response.filecontent = file_doc.get_content()
    frappe.local.response.type = "download"
