import frappe
from frappe import _

USER_LINK_FIELDS = ["custom_user", "user_id", "user"]


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


def _get_buyer_user_field():
    meta = frappe.get_meta("Buyer")
    for fieldname in USER_LINK_FIELDS:
        if meta.has_field(fieldname):
            return fieldname
    return None


@frappe.whitelist()
def create_buyer_with_user(buyer_name=None, email=None, buyer_code=None, company_name=None, phone=None, country=None, name=None):
    """
    Creates a User, then a Buyer linked to that User, and sends a welcome email.
    """
    # Allow legacy 'name' param
    buyer_name = buyer_name or name

    if not buyer_name or not email:
        frappe.throw(_("Buyer Name and Email are required"))

    if frappe.db.exists("User", email):
        frappe.throw(_("A user with email {0} already exists").format(email))

    try:
        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": name,
            "enabled": 1,
            "send_welcome_email": 1,
            "roles": [{"role": "Customer"}]
        })
        user.insert(ignore_permissions=True)

        buyer_data = {
            "doctype": "Buyer",
            "buyer_name": buyer_name,
            "buyer_code": buyer_code,
            "company_name": company_name,
            "email": email,
            "phone": phone,
            "country": country,
        }
        if country:
            customer_data["country"] = country

        user_field = _get_buyer_user_field()
        if user_field:
            buyer_data[user_field] = user.name
        buyer = frappe.get_doc(buyer_data)
        buyer.insert(ignore_permissions=True)

        frappe.db.commit()

        return {
            "message": "Buyer and User created successfully",
            "buyer": buyer.name,
            "user": user.name
        }
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Buyer Creation Error: {str(e)}")
        frappe.throw(_("Failed to create buyer: {0}").format(str(e)))


@frappe.whitelist()
def toggle_buyer_access(buyer_name, enable=0):
    if not buyer_name:
        frappe.throw(_("Buyer Name is required"))

    buyer = frappe.get_doc("Buyer", buyer_name)

    user_field = _get_buyer_user_field()
    user_name = getattr(buyer, user_field, None) if user_field else None
    if not user_name:
        frappe.throw(_("This buyer is not linked to a User account"))

    user = frappe.get_doc("User", user_name)
    user.enabled = int(enable)
    user.save(ignore_permissions=True)
    frappe.db.commit()

    status = "Enabled" if user.enabled else "Disabled"
    return {"message": f"Buyer access {status}", "enabled": user.enabled}


@frappe.whitelist()
def get_buyers(search=None, limit=100, page=1, page_size=None):
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    page_no = _coerce_page(page, default=1)
    page_limit = _coerce_page_size(page_size=page_size, fallback_limit=limit, default=25, max_size=100)
    offset = (page_no - 1) * page_limit

    user_field = _get_buyer_user_field()
    if not user_field:
        frappe.throw(_("Buyer doctype has no user link field (custom_user/user_id/user)"))

    search_condition = ""
    params = {}
    if search:
        search_condition = """
            AND (
                b.buyer_name LIKE %(search)s
                OR b.name LIKE %(search)s
                OR b.buyer_code LIKE %(search)s
                OR b.company_name LIKE %(search)s
                OR b.email LIKE %(search)s
                OR u.email LIKE %(search)s
            )
        """
        params["search"] = f"%{search}%"

    base_from_where = f"""
        SELECT 
            b.name, 
            b.buyer_name, 
            b.buyer_code,
            b.company_name,
            b.email,
            b.phone,
            b.country, 
            b.{user_field} as user_link,
            u.enabled as user_enabled
        FROM `tabBuyer` b
        JOIN `tabUser` u ON b.{user_field} = u.name
        WHERE 
            b.{user_field} IS NOT NULL 
            AND b.{user_field} != ''
            {search_condition}
    """

    count_query = f"""
        SELECT COUNT(*) AS total
        FROM `tabBuyer` b
        JOIN `tabUser` u ON b.{user_field} = u.name
        WHERE 
            b.{user_field} IS NOT NULL 
            AND b.{user_field} != ''
            {search_condition}
    """
    total_row = frappe.db.sql(count_query, params, as_dict=True) or []
    total = int((total_row[0] or {}).get("total") or 0)

    query = f"""
        {base_from_where}
        ORDER BY b.buyer_name ASC
        LIMIT {page_limit}
        OFFSET {offset}
    """

    data = frappe.db.sql(query, params, as_dict=True)

    buyers = [
        {
            "_id": row.name,
            "name": row.name,
            "buyer_name": row.buyer_name or row.name,
            "buyer_code": row.buyer_code,
            "company_name": row.company_name,
            "email": row.email,
            "phone": row.phone,
            "country": row.country,
            "user": row.user_link,
            "user_enabled": row.user_enabled
        }
        for row in data
    ]

    return {
        "buyers": buyers,
        "pagination": _build_pagination(page_no, page_limit, total),
    }
