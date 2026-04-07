from __future__ import annotations

from html import escape

import frappe

USER_LINK_FIELDS = ("custom_user", "user_id", "user")
PARTY_EMAIL_FIELDS = ("email_id", "email", "contact_email")


def _to_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _get_linked_user(doctype: str, docname: str) -> str | None:
    try:
        meta = frappe.get_meta(doctype)
    except Exception:
        return None

    for fieldname in USER_LINK_FIELDS:
        try:
            if meta.has_field(fieldname):
                user = _to_text(frappe.db.get_value(doctype, docname, fieldname))
                if user:
                    return user
        except Exception:
            continue
    return None


def _get_email_via_dynamic_link(doctype: str, docname: str) -> str | None:
    try:
        contact_names = frappe.get_all(
            "Dynamic Link",
            filters={
                "link_doctype": doctype,
                "link_name": docname,
                "parenttype": "Contact",
            },
            pluck="parent",
            limit_page_length=20,
        )
    except Exception:
        return None

    for contact_name in contact_names or []:
        contact_name = _to_text(contact_name)
        if not contact_name:
            continue

        try:
            contact_email = _to_text(frappe.db.get_value("Contact", contact_name, "email_id"))
            if contact_email:
                return contact_email
        except Exception:
            pass

        try:
            email_rows = frappe.get_all(
                "Contact Email",
                filters={"parent": contact_name},
                fields=["email_id"],
                limit_page_length=1,
            )
            if email_rows and _to_text(email_rows[0].get("email_id")):
                return _to_text(email_rows[0].get("email_id"))
        except Exception:
            pass

    return None


def _get_party_email(doctype: str, docname: str) -> str | None:
    docname = _to_text(docname)
    if not docname:
        return None

    user = _get_linked_user(doctype, docname)
    if user:
        try:
            user_email = _to_text(frappe.db.get_value("User", user, "email"))
            if user_email:
                return user_email
        except Exception:
            pass

    try:
        meta = frappe.get_meta(doctype)
        for fieldname in PARTY_EMAIL_FIELDS:
            if meta.has_field(fieldname):
                email_value = _to_text(frappe.db.get_value(doctype, docname, fieldname))
                if email_value:
                    return email_value
    except Exception:
        pass

    return _get_email_via_dynamic_link(doctype, docname)


def _get_party_display_name(doctype: str, docname: str) -> str:
    docname = _to_text(docname)
    if not docname:
        return ""

    preferred_fields = {
        "Supplier": ("supplier_name", "name"),
        "Customer": ("customer_name", "name"),
    }.get(doctype, ("name",))

    for fieldname in preferred_fields:
        try:
            value = _to_text(frappe.db.get_value(doctype, docname, fieldname))
            if value:
                return value
        except Exception:
            continue

    return docname


def _send_email(recipients: list[str], subject: str, message: str, context: str) -> None:
    clean_recipients = []
    seen = set()
    for addr in recipients:
        addr = _to_text(addr)
        if not addr:
            continue
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        clean_recipients.append(addr)

    if not clean_recipients:
        return

    try:
        frappe.sendmail(
            recipients=clean_recipients,
            subject=subject,
            message=message,
            delayed=False,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"{context} email send failed")


def _render_details_table(details: list[tuple[str, str]]) -> str:
    rows = []
    for label, value in details:
        text_value = _to_text(value)
        if not text_value:
            continue
        rows.append(
            "<tr>"
            "<td style='padding:10px 12px;border-bottom:1px solid #e8efea;color:#4b5563;font-size:13px;font-weight:600;vertical-align:top;width:38%;'>"
            f"{escape(_to_text(label))}"
            "</td>"
            "<td style='padding:10px 12px;border-bottom:1px solid #e8efea;color:#111827;font-size:13px;vertical-align:top;'>"
            f"{escape(text_value)}"
            "</td>"
            "</tr>"
        )

    if not rows:
        return ""

    return (
        "<table role='presentation' cellpadding='0' cellspacing='0' border='0' style='width:100%;border:1px solid #e8efea;border-radius:8px;border-collapse:separate;border-spacing:0;overflow:hidden;background:#ffffff;margin:16px 0 20px 0;'>"
        f"{''.join(rows)}"
        "</table>"
    )


def _render_notification_email(
    *,
    title: str,
    greeting: str,
    intro: str,
    details: list[tuple[str, str]],
    sender_name: str,
) -> str:
    safe_title = escape(_to_text(title) or "Notification")
    safe_greeting = escape(_to_text(greeting) or "Hello,")
    safe_intro = escape(_to_text(intro))
    safe_sender = escape(_to_text(sender_name) or "Importer")
    details_html = _render_details_table(details)

    return (
        "<div style='margin:0;padding:24px 0;background:#f4f7f5;font-family:Arial,Helvetica,sans-serif;'>"
        "<table role='presentation' cellpadding='0' cellspacing='0' border='0' style='width:100%;max-width:680px;margin:0 auto;background:#ffffff;border:1px solid #dfe8e1;border-radius:12px;overflow:hidden;'>"
        "<tr>"
        "<td style='padding:16px 24px;background:linear-gradient(90deg,#1f6d36,#2e7d32);color:#ffffff;'>"
        "<div style='font-size:20px;font-weight:700;letter-spacing:0.2px;'>Traces360</div>"
        "</td>"
        "</tr>"
        "<tr>"
        "<td style='padding:24px 24px 8px 24px;'>"
        f"<h2 style='margin:0 0 14px 0;color:#1f2937;font-size:22px;line-height:1.3;'>{safe_title}</h2>"
        f"<p style='margin:0 0 10px 0;color:#111827;font-size:14px;line-height:1.6;'>{safe_greeting}</p>"
        f"<p style='margin:0;color:#374151;font-size:14px;line-height:1.6;'>{safe_intro}</p>"
        f"{details_html}"
        "<p style='margin:0 0 18px 0;color:#374151;font-size:14px;line-height:1.6;'>Please log in to Traces360 to take action.</p>"
        "<p style='margin:0 0 24px 0;color:#111827;font-size:14px;line-height:1.7;'>"
        "Regards,<br>"
        f"<strong>{safe_sender}</strong>"
        "</p>"
        "</td>"
        "</tr>"
        "<tr>"
        "<td style='padding:12px 24px;background:#f8faf9;color:#6b7280;font-size:12px;border-top:1px solid #e5ece7;'>This is an automated notification from Traces360.</td>"
        "</tr>"
        "</table>"
        "</div>"
    )


def send_request_created_email(doc) -> None:
    if not doc or _to_text(getattr(doc, "doctype", "")) != "Request":
        return

    supplier_name = _to_text(getattr(doc, "supplier", ""))
    customer_name = _to_text(getattr(doc, "customer", ""))
    if not supplier_name or not customer_name:
        return

    supplier_email = _get_party_email("Supplier", supplier_name)
    if not supplier_email:
        return

    supplier_label = _get_party_display_name("Supplier", supplier_name) or supplier_name
    customer_label = _get_party_display_name("Customer", customer_name) or customer_name

    request_type = _to_text(getattr(doc, "request_type", ""))
    request_label_map = {
        "land_plot": "Land Plot Data",
        "product_data": "Product Data",
        "purchase_order": "Purchase Order",
    }
    request_label = request_label_map.get(request_type, request_type.replace("_", " ").title() or "Request")

    po_number = _to_text(getattr(doc, "purchase_order_number", ""))
    note = _to_text(getattr(doc, "message", ""))

    subject = f"New {request_label} Request - {doc.name}"

    details = [
        ("Request ID", doc.name),
        ("Request Type", request_label),
    ]
    if po_number:
        details.append(("PO / Contract No", po_number))
    if note:
        details.append(("Message", note))

    message = _render_notification_email(
        title=f"New {request_label} Request",
        greeting=f"Hello {supplier_label},",
        intro="A new request has been created and shared with you.",
        details=details,
        sender_name=customer_label,
    )

    _send_email([supplier_email], subject, message, context="Request created notification")


def send_questionnaire_created_email(doc) -> None:
    if not doc or _to_text(getattr(doc, "doctype", "")) != "Questionnaire":
        return

    supplier_name = _to_text(getattr(doc, "supplier", ""))
    customer_name = _to_text(getattr(doc, "customer", ""))
    if not supplier_name or not customer_name:
        return

    supplier_email = _get_party_email("Supplier", supplier_name)
    if not supplier_email:
        return

    supplier_label = _get_party_display_name("Supplier", supplier_name) or supplier_name
    customer_label = _get_party_display_name("Customer", customer_name) or customer_name

    title = _to_text(getattr(doc, "title", "")) or "Questionnaire"
    due_date = _to_text(getattr(doc, "due_date", ""))

    subject = f"New Questionnaire - {title}"

    details = [
        ("Questionnaire ID", doc.name),
        ("Title", title),
        ("From Importer", customer_label),
    ]
    if due_date:
        details.append(("Due Date", due_date))

    message = _render_notification_email(
        title=f"New Questionnaire: {title}",
        greeting=f"Hello {supplier_label},",
        intro="A new questionnaire has been assigned to you. Please review and submit your responses.",
        details=details,
        sender_name=customer_label,
    )

    _send_email([supplier_email], subject, message, context="Questionnaire created notification")
