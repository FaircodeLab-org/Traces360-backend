import json

import frappe
from frappe import _

USER_LINK_FIELDS = {
    "Customer": ["custom_user", "user_id", "user"],
    "Supplier": ["custom_user", "user_id", "user"],
}

MAPPING_KEY_PREFIX = "importer_email_account"
SERVICE_OPTIONS = {"", "GMail", "Sendgrid", "SparkPost", "Yahoo Mail", "Outlook.com", "Yandex.Mail"}


def _payload_from_request(data=None):
    if data is not None:
        if isinstance(data, str):
            try:
                return json.loads(data)
            except Exception:
                return {}
        return data if isinstance(data, dict) else {}

    if frappe.form_dict:
        if frappe.form_dict.get("data"):
            raw = frappe.form_dict.get("data")
            if isinstance(raw, str):
                try:
                    return json.loads(raw)
                except Exception:
                    return {}
            if isinstance(raw, dict):
                return raw

        # fallback for direct form payload
        form_payload = {
            key: val for key, val in frappe.form_dict.items() if key not in {"cmd", "data"}
        }
        if form_payload:
            return form_payload

    try:
        body = frappe.request.get_json(silent=True)
        if isinstance(body, dict):
            return body
    except Exception:
        pass

    return {}


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _to_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _get_user_email(user: str) -> str | None:
    try:
        return frappe.db.get_value("User", user, "email")
    except Exception:
        return None


def _link_by_contact_email(user: str, target_doctype: str) -> str | None:
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
            "link_doctype": target_doctype,
        },
        fields=["link_name"],
        limit=1,
    )
    return links[0]["link_name"] if links else None


def _link_by_user_field(doctype: str, user: str) -> str | None:
    try:
        meta = frappe.get_meta(doctype)
    except Exception:
        return None

    for fieldname in USER_LINK_FIELDS.get(doctype, []):
        if meta.has_field(fieldname):
            docname = frappe.db.get_value(doctype, {fieldname: user}, "name")
            if docname:
                return docname

    return None


def _resolve_parties(user: str) -> tuple[str | None, str | None]:
    customer = _link_by_user_field("Customer", user) or _link_by_contact_email(user, "Customer")
    supplier = _link_by_user_field("Supplier", user) or _link_by_contact_email(user, "Supplier")
    return customer, supplier


def _require_importer_context():
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, _supplier = _resolve_parties(user)
    roles = set(frappe.get_roles(user))
    is_manager = "System Manager" in roles

    if not customer and not is_manager:
        frappe.throw(_("Only importer/customer users can configure email settings"), frappe.PermissionError)

    return user, customer, is_manager


def _mapping_key(customer: str | None, user: str, is_manager: bool) -> str:
    scope = customer or (user if is_manager else None)
    if not scope:
        frappe.throw(_("Unable to resolve importer context"), frappe.PermissionError)
    return f"{MAPPING_KEY_PREFIX}::{scope}"


def _get_mapped_account_name(map_key: str) -> str | None:
    return frappe.db.get_value("DefaultValue", {"parent": "__default", "defkey": map_key}, "defvalue")


def _set_mapped_account_name(map_key: str, account_name: str | None):
    frappe.defaults.set_global_default(map_key, account_name or None)


def _password_set(doc) -> bool:
    try:
        return bool(doc.get_password("password"))
    except Exception:
        return False


def _normalize_imap_folders(doc):
    if not (_to_bool(doc.get("enable_incoming"), False) and _to_bool(doc.get("use_imap"), False)):
        return

    normalized = []
    for row in (doc.get("imap_folder") or []):
        folder_name = ""
        append_to = ""

        if isinstance(row, dict):
            folder_name = _to_text(row.get("folder_name"))
            append_to = _to_text(row.get("append_to"))
        else:
            folder_name = _to_text(getattr(row, "folder_name", ""))
            append_to = _to_text(getattr(row, "append_to", ""))

        if not folder_name:
            continue

        clean_row = {"folder_name": folder_name}
        if append_to:
            clean_row["append_to"] = append_to
        normalized.append(clean_row)

    if not normalized:
        normalized = [{"folder_name": "INBOX"}]

    doc.set("imap_folder", normalized)


def _sanitize_account(doc, customer: str | None):
    return {
        "account_name": doc.name,
        "customer": customer,
        "service": doc.service or "",
        "email_account_name": doc.email_account_name or "",
        "email_id": doc.email_id or "",
        "login_id_is_different": int(doc.login_id_is_different or 0),
        "login_id": doc.login_id or "",
        "password_set": _password_set(doc),
        "enable_incoming": int(doc.enable_incoming or 0),
        "default_incoming": int(doc.default_incoming or 0),
        "use_imap": int(doc.use_imap or 0),
        "use_ssl": int(doc.use_ssl or 0),
        "use_starttls": int(doc.use_starttls or 0),
        "email_server": doc.email_server or "",
        "incoming_port": doc.incoming_port or "",
        "enable_outgoing": int(doc.enable_outgoing or 0),
        "default_outgoing": int(doc.default_outgoing or 0),
        "use_tls": int(doc.use_tls or 0),
        "use_ssl_for_outgoing": int(doc.use_ssl_for_outgoing or 0),
        "smtp_server": doc.smtp_server or "",
        "smtp_port": doc.smtp_port or "",
    }


def _default_payload(customer: str | None):
    base_name = _to_text(customer) or "Importer"
    return {
        "account_name": None,
        "customer": customer,
        "service": "",
        "email_account_name": f"{base_name} Email",
        "email_id": "",
        "login_id_is_different": 0,
        "login_id": "",
        "password_set": False,
        "enable_incoming": 1,
        "default_incoming": 1,
        "use_imap": 1,
        "use_ssl": 1,
        "use_starttls": 0,
        "email_server": "",
        "incoming_port": "993",
        "enable_outgoing": 1,
        "default_outgoing": 1,
        "use_tls": 1,
        "use_ssl_for_outgoing": 0,
        "smtp_server": "",
        "smtp_port": "587",
    }


@frappe.whitelist()
def get_importer_email_settings():
    user, customer, is_manager = _require_importer_context()
    map_key = _mapping_key(customer, user, is_manager)
    account_name = _get_mapped_account_name(map_key)

    if account_name and frappe.db.exists("Email Account", account_name):
        doc = frappe.get_doc("Email Account", account_name)
        return _sanitize_account(doc, customer)

    return _default_payload(customer)


@frappe.whitelist(methods=["POST"])
def save_importer_email_settings(data=None, **kwargs):
    user, customer, is_manager = _require_importer_context()
    payload = _payload_from_request(data) or {}

    # Also allow kwargs for direct whitelisted invocation patterns
    for key, value in (kwargs or {}).items():
        if key not in payload:
            payload[key] = value

    map_key = _mapping_key(customer, user, is_manager)
    mapped_name = _get_mapped_account_name(map_key)

    if mapped_name and frappe.db.exists("Email Account", mapped_name):
        doc = frappe.get_doc("Email Account", mapped_name)
    else:
        doc = frappe.new_doc("Email Account")

    is_new = doc.is_new()

    email_account_name = _to_text(payload.get("email_account_name")) or _to_text(doc.email_account_name)
    email_id = _to_text(payload.get("email_id")) or _to_text(doc.email_id)
    service = _to_text(payload.get("service")) or _to_text(doc.service)

    if not email_account_name:
        frappe.throw(_("Email account name is required"))
    if not email_id:
        frappe.throw(_("Email address is required"))
    if service not in SERVICE_OPTIONS:
        frappe.throw(_("Unsupported email service: {0}").format(service))

    login_id_is_different = _to_bool(
        payload.get("login_id_is_different"), default=_to_bool(doc.login_id_is_different, False)
    )
    login_id = _to_text(payload.get("login_id")) if login_id_is_different else ""

    password = payload.get("password")
    password = _to_text(password)
    if is_new and not password:
        frappe.throw(_("Password is required for first-time setup"))

    enable_incoming = _to_bool(payload.get("enable_incoming"), True)
    enable_outgoing = _to_bool(payload.get("enable_outgoing"), True)

    email_server = _to_text(payload.get("email_server"))
    incoming_port = _to_text(payload.get("incoming_port")) or "993"
    smtp_server = _to_text(payload.get("smtp_server"))
    smtp_port = _to_text(payload.get("smtp_port")) or "587"

    if enable_incoming and not email_server:
        frappe.throw(_("Incoming server is required"))
    if enable_outgoing and not smtp_server:
        frappe.throw(_("Outgoing server is required"))

    doc.email_account_name = email_account_name
    doc.email_id = email_id
    doc.service = service or None
    doc.auth_method = "Basic"
    doc.login_id_is_different = 1 if login_id_is_different else 0
    doc.login_id = login_id

    doc.enable_incoming = 1 if enable_incoming else 0
    doc.default_incoming = 1
    doc.use_imap = 1 if _to_bool(payload.get("use_imap"), True) else 0
    doc.use_ssl = 1 if _to_bool(payload.get("use_ssl"), True) else 0
    doc.use_starttls = 1 if _to_bool(payload.get("use_starttls"), False) else 0
    doc.email_server = email_server
    doc.incoming_port = incoming_port

    _normalize_imap_folders(doc)

    doc.enable_outgoing = 1 if enable_outgoing else 0
    doc.default_outgoing = 1
    doc.use_tls = 1 if _to_bool(payload.get("use_tls"), True) else 0
    doc.use_ssl_for_outgoing = 1 if _to_bool(payload.get("use_ssl_for_outgoing"), False) else 0
    doc.smtp_server = smtp_server
    doc.smtp_port = smtp_port

    if password:
        doc.password = password
        doc.awaiting_password = 0

    if is_new:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    frappe.db.sql(
        """
        UPDATE `tabEmail Account`
        SET default_incoming = 0
        WHERE name != %s AND IFNULL(default_incoming, 0) = 1
        """,
        (doc.name,),
    )
    frappe.db.sql(
        """
        UPDATE `tabEmail Account`
        SET default_outgoing = 0
        WHERE name != %s AND IFNULL(default_outgoing, 0) = 1
        """,
        (doc.name,),
    )
    frappe.db.set_value("Email Account", doc.name, "default_incoming", 1)
    frappe.db.set_value("Email Account", doc.name, "default_outgoing", 1)

    _set_mapped_account_name(map_key, doc.name)

    frappe.db.commit()
    doc.reload()

    result = _sanitize_account(doc, customer)
    result["message"] = _("Email settings saved")
    return result
