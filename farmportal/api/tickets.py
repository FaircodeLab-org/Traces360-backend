import frappe
from frappe.utils import now


def _coerce_page(value, default=1):
    try:
        page = int(value)
    except Exception:
        page = default
    return max(page, 1)


def _coerce_page_size(value, default=25, max_size=100):
    try:
        size = int(value)
    except Exception:
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


@frappe.whitelist(allow_guest=True)
def create_ticket(company_code, tenant_site, subject, description, priority="Medium", module=None, user_email=None):
    ticket = frappe.get_doc({
        "doctype": "Support Ticket",
        "company_code": company_code,
        "tenant_site": tenant_site,
        "user_email": user_email or frappe.session.user,
        "subject": subject,
        "description": description,
        "priority": priority,
        "module": module,
        "status": "Open",
        "created_by": user_email or frappe.session.user or "Guest"
    })

    ticket.insert(ignore_permissions=True)

    return {
        "ticket_id": ticket.name,
        "message": "Ticket created successfully"
    }


@frappe.whitelist(allow_guest=True)
def get_tickets(company_code=None, page=1, page_size=25, status=None, priority=None, query=None, user_email=None):
    page_no = _coerce_page(page, default=1)
    page_len = _coerce_page_size(page_size, default=25, max_size=100)
    offset = (page_no - 1) * page_len

    clean_status = (status or "").strip()
    if clean_status.lower() == "all":
        clean_status = ""

    clean_priority = (priority or "").strip()
    if clean_priority.lower() == "all":
        clean_priority = ""

    clean_query = (query or "").strip()
    clean_user_email = (user_email or "").strip().lower()

    where = ["1=1"]
    params = {}

    if company_code:
        where.append("company_code = %(company_code)s")
        params["company_code"] = company_code

    if clean_status:
        where.append("status = %(status)s")
        params["status"] = clean_status

    if clean_priority:
        where.append("priority = %(priority)s")
        params["priority"] = clean_priority

    if clean_user_email:
        where.append("(LOWER(COALESCE(user_email, '')) = %(user_email)s OR LOWER(COALESCE(created_by, '')) = %(user_email)s)")
        params["user_email"] = clean_user_email

    if clean_query:
        where.append("(" + " OR ".join([
            "name LIKE %(q)s",
            "subject LIKE %(q)s",
            "description LIKE %(q)s",
            "created_by LIKE %(q)s",
            "user_email LIKE %(q)s",
            "module LIKE %(q)s",
        ]) + ")")
        params["q"] = f"%{clean_query}%"

    where_sql = " AND ".join(where)

    total_row = frappe.db.sql(
        f"SELECT COUNT(name) AS total FROM `tabSupport Ticket` WHERE {where_sql}",
        params,
        as_dict=True,
    ) or []
    total = int(total_row[0].get("total") or 0) if total_row else 0

    query_params = dict(params)
    query_params.update({"offset": offset, "page_len": page_len})

    tickets = frappe.db.sql(
        f"""
        SELECT
            name,
            company_code,
            subject,
            description,
            status,
            priority,
            module,
            user_email,
            created_by,
            tenant_site,
            creation
        FROM `tabSupport Ticket`
        WHERE {where_sql}
        ORDER BY creation DESC
        LIMIT %(offset)s, %(page_len)s
        """,
        query_params,
        as_dict=True,
    )

    return {
        "tickets": tickets,
        "pagination": _build_pagination(page_no, page_len, total),
    }


@frappe.whitelist(allow_guest=True)
def add_reply(ticket_id, message, attachment=None, reply_by=None):
    if not ticket_id:
        frappe.throw("ticket_id is required")
    if not message:
        frappe.throw("message is required")

    doc = frappe.get_doc("Support Ticket", ticket_id)
    doc.append("reply", {
        "user": reply_by or frappe.session.user or "Guest",
        "message": message,
        "attachment": attachment,
        "date": now()
    })
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"message": "Reply added"}


@frappe.whitelist(allow_guest=True)
def update_status(ticket_id, status, updated_by=None):
    if not ticket_id:
        frappe.throw("ticket_id is required")
    if not status:
        frappe.throw("status is required")

    allowed = {"Open", "In Progress", "Resolved", "Closed"}
    if status not in allowed:
        frappe.throw(f"Invalid status: {status}")

    doc = frappe.get_doc("Support Ticket", ticket_id)
    doc.status = status
    if hasattr(doc, "modified_by"):
        doc.modified_by = updated_by or frappe.session.user or "Guest"
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"message": "Status updated"}


@frappe.whitelist(allow_guest=True)
def get_ticket_detail(ticket_id):
    if not ticket_id:
        frappe.throw("ticket_id is required")

    doc = frappe.get_doc("Support Ticket", ticket_id)
    return {
        "name": doc.name,
        "company_code": doc.company_code,
        "subject": doc.subject,
        "description": doc.description,
        "status": doc.status,
        "priority": doc.priority,
        "created_by": doc.created_by,
        "user_email": doc.user_email,
        "tenant_site": doc.tenant_site,
        "creation": doc.creation,
        "reply": [
            {
                "user": r.user,
                "message": r.message,
                "attachment": r.attachment,
                "date": r.date
            }
            for r in (doc.get("reply") or [])
        ],
    }
