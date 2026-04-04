import frappe, json
from frappe import _

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


def _normalize_email(value):
    return (value or "").strip().lower()


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


def _can_manage_supplier_members(supplier_doc, user: str) -> bool:
    """Only the primary supplier account can add/remove members."""
    owner_user = _get_supplier_owner_user(supplier_doc)
    return bool(owner_user and owner_user == user)


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


def _get_supplier_context_for_user(user: str, supplier_hint=None):
    supplier_name = _get_supplier_for_user(user, supplier_hint)
    if not supplier_name:
        return None, None, None, None

    supplier_doc = frappe.get_doc("Supplier", supplier_name)
    owner_user = _get_supplier_owner_user(supplier_doc)
    supplier_org_name = str(supplier_doc.get("supplier_name") or "").strip()
    return supplier_name, supplier_doc, owner_user, supplier_org_name


def _get_canonical_org_profile_name(user: str, supplier_doc=None, owner_user: str | None = None):
    """
    Return the one Organization Module record that should be shared by all users
    under the same supplier.
    """
    if supplier_doc:
        if owner_user:
            owner_doc = frappe.db.exists("Organization Module", {"user": owner_user})
            if owner_doc:
                return owner_doc

        supplier_org_name = str(supplier_doc.get("supplier_name") or "").strip()
        if supplier_org_name:
            org_docs = frappe.get_all(
                "Organization Module",
                filters={"organization_name": supplier_org_name},
                fields=["name", "user", "modified"],
                order_by="modified desc",
                limit_page_length=200,
            )
            chosen = _pick_best_org_profile_name(org_docs, preferred_user=owner_user)
            if chosen:
                return chosen

        # Legacy recovery: choose best profile among known supplier users.
        candidate_users = []
        for candidate in [owner_user, _resolve_user_name(user) or user]:
            if candidate and candidate not in candidate_users:
                candidate_users.append(candidate)
        for member_user in _get_supplier_member_user_ids(supplier_doc):
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
            chosen = _pick_best_org_profile_name(profile_rows, preferred_user=owner_user)
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


def _merge_legacy_member_profile_certificates(supplier_doc, canonical_profile_name, owner_user=None):
    """
    Backfill certificates from old per-member Organization Module records into the
    canonical supplier-shared profile.
    """
    if not supplier_doc or not canonical_profile_name:
        return

    try:
        member_user_ids = _get_supplier_member_user_ids(supplier_doc)
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
    supplier_members = []
    can_manage_members = False
    supplier_name, supplier_doc, owner_user, _supplier_org_name = _get_supplier_context_for_user(user)
    if supplier_doc:
        can_manage_members = _can_manage_supplier_members(supplier_doc, user)

    existing = _get_canonical_org_profile_name(user, supplier_doc, owner_user)
    if not existing:
        return None

    if supplier_doc:
        _merge_legacy_member_profile_certificates(supplier_doc, existing, owner_user)

    doc = frappe.get_doc("Organization Module", existing)

    if supplier_name:
        member_table_fieldname = _get_member_table_fieldname(supplier_doc)
        supplier_members = [
            {
                "name": m.name,
                "first_name": m.first_name,
                "last_name": m.last_name,
                "email": m.email,
                "designation": m.designation,
                "user_link": m.user_link,
            }
            for m in (supplier_doc.get(member_table_fieldname, []) if member_table_fieldname else [])
        ]

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
        "custom_organization_members": supplier_members,
        "can_manage_members": can_manage_members,
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
            or data.get("organizationName")
            or data.get("organization_name")
            or data.get("docname")
        )
        _supplier_name, supplier_doc, owner_user, supplier_org_name = _get_supplier_context_for_user(user, supplier_hint)
        existing = _get_canonical_org_profile_name(user, supplier_doc, owner_user)

        organization_name = str(data.get("organizationName") or data.get("organization_name") or "").strip()
        if not organization_name:
            organization_name = supplier_org_name or ""

        if not organization_name and not existing:
            frappe.throw("Organization Name is required")

        if existing:
            doc = frappe.get_doc("Organization Module", existing)
            if not organization_name:
                organization_name = str(doc.get("organization_name") or "").strip()
        else:
            doc = frappe.new_doc("Organization Module")
            doc.user = owner_user or user

        if supplier_doc and owner_user:
            # Keep one supplier-shared profile owned by the primary supplier user.
            doc.user = owner_user

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

    _supplier_name, supplier_doc, owner_user, _supplier_org_name = _get_supplier_context_for_user(user)
    existing = _get_canonical_org_profile_name(user, supplier_doc, owner_user)
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
        or data.get("organizationName")
        or data.get("organization_name")
        or profile_name_hint
    )
    _supplier_name, supplier_doc, owner_user, _supplier_org_name = _get_supplier_context_for_user(user, supplier_hint)
    profile_name = _get_canonical_org_profile_name(user, supplier_doc, owner_user)

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
        or payload.get("organizationName")
        or payload.get("organization_name")
        or profile_name
    )
    _supplier_name, supplier_doc, owner_user, _supplier_org_name = _get_supplier_context_for_user(user, supplier_hint)
    canonical_profile_name = _get_canonical_org_profile_name(user, supplier_doc, owner_user)

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
    Run on Supplier.validate
    """
    member_table_fieldname = _get_member_table_fieldname(doc)
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
                "roles": [{"role": "Supplier"}] 
            })
            user.insert(ignore_permissions=True)
            
            # 2. Link User ID back to the child table row
            member.user_link = user.name
            
            # 3. Ensure Contact Exists (Vital for permissions)
            create_contact_link(user, member, doc.name)
        
        else:
            # User exists, ensure link is set
            if not member.user_link:
                member.user_link = member.email 
                # Still ensure contact exists even if user existed before
                user_doc = frappe.get_doc("User", member.email)
                create_contact_link(user_doc, member, doc.name)

def create_contact_link(user, member, supplier_name):
    """
    Ensures a Contact exists linking this User to this Supplier.
    """
    contact_name = frappe.db.get_value("Contact", {"email_id": user.email})
    
    if not contact_name:
        contact = frappe.get_doc({
            "doctype": "Contact",
            "first_name": member.first_name,
            "last_name": member.last_name,
            "email_id": user.email,
            "user": user.name,
            "links": [{"link_doctype": "Supplier", "link_name": supplier_name}]
        })
        contact.insert(ignore_permissions=True)
    else:
        # Check if already linked to THIS supplier
        contact = frappe.get_doc("Contact", contact_name)
        is_linked = any(l.link_name == supplier_name and l.link_doctype == 'Supplier' for l in contact.links)
        
        if not is_linked:
            contact.append("links", {
                "link_doctype": "Supplier",
                "link_name": supplier_name
            })
            contact.save(ignore_permissions=True)
            
            
@frappe.whitelist(methods=["POST"])
def add_member(**kwargs):
    try:
        # 1. Parse Payload
        data = kwargs.get('data')
        if data is None: data = kwargs
        if isinstance(data, str): import json; data = json.loads(data)

        # 2. Validate Inputs
        email = (data.get("email") or "").strip()
        if not email: frappe.throw("Email is required")
        email_norm = _normalize_email(email)
        
        # 3. FIND THE SUPPLIER
        # We ignore 'supplierName' from frontend because it might be the Org Module ID.
        # Instead, we reliably find the Supplier linked to the *current logged-in user*.
        
        user = frappe.session.user
        supplier_hint = data.get("supplierName") or data.get("organizationName") or data.get("organization_name")
        supplier_name = _get_supplier_for_user(user, supplier_hint)
        
        if not supplier_name:
             frappe.throw("No Supplier account found linked to this user.")

        # 4. Get the Supplier Document
        supplier_doc = frappe.get_doc("Supplier", supplier_name)
        if not _can_manage_supplier_members(supplier_doc, user):
            frappe.throw(_("Only the primary supplier account can manage members"), frappe.PermissionError)
        member_table_fieldname = _get_member_table_fieldname(supplier_doc)
        if not member_table_fieldname:
            frappe.throw(
                "Supplier member table is not configured. "
                "Please add a Supplier table field pointing to 'Supplier User'."
            )
        
        # 5. Add to custom child table
        existing_members = supplier_doc.get(member_table_fieldname) or []
        
        for member in existing_members:
            if _normalize_email(member.email) == email_norm:
                frappe.throw(f"Member {email} already exists")

        # If this user existed previously and was disabled, re-enable on re-invite.
        existing_user_name = _resolve_user_name(email)
        if existing_user_name and frappe.db.exists("User", existing_user_name):
            enabled = frappe.db.get_value("User", existing_user_name, "enabled")
            if str(enabled).strip() in ("0", "False", "false", ""):
                frappe.db.set_value("User", existing_user_name, "enabled", 1, update_modified=False)
                frappe.cache.delete_key("enabled_users")

        supplier_doc.append(member_table_fieldname, {
            "first_name": data.get("firstName"),
            "last_name": data.get("lastName"),
            "email": email,
            "designation": data.get("designation") or data.get("deisgnation")
        })
        
        supplier_doc.save(ignore_permissions=True) # This triggers the hooks we wrote earlier!
        frappe.db.commit()
        
        return {"message": "Member added to Supplier"}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Add Member Error")
        frappe.throw(str(e))



@frappe.whitelist(methods=["POST"])
def remove_member(**kwargs):
    try:
        # Flexible payload parsing
        data = kwargs.get('data')
        if data is None: data = kwargs
        if isinstance(data, str): import json; data = json.loads(data)

        email = (data.get("email") or "").strip()
        member_id = data.get("memberId") or data.get("member_id") or data.get("memberName")
        
        if not email and not member_id:
            frappe.throw(_("Email or memberId is required"))
        email_norm = _normalize_email(email)

        actor_user = frappe.session.user
        supplier_hint = data.get("supplierName") or data.get("organizationName") or data.get("organization_name")
        supplier_name = _get_supplier_for_user(actor_user, supplier_hint)
        if not supplier_name:
            frappe.throw("No Supplier account found linked to this user.")

        doc = frappe.get_doc("Supplier", supplier_name)
        if not _can_manage_supplier_members(doc, actor_user):
            frappe.throw(_("Only the primary supplier account can manage members"), frappe.PermissionError)
        member_table_fieldname = _get_member_table_fieldname(doc)
        if not member_table_fieldname:
            frappe.throw(_("Supplier member table is not configured"))
        
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
