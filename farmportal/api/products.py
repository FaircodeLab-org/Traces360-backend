# my_app/my_app/api/products.py
import frappe
import json
from typing import List, Dict

@frappe.whitelist()
def get_products(search: str = None, limit_start: int = 0, limit_page_length: int = 200):
    """
    Returns Items linked to Request.requested_products for the current user
    (customer or supplier), with a batches array for each item.
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Not logged in", frappe.PermissionError)

    # Resolve current party
    from farmportal.api.requests import _get_party_from_user
    customer, supplier = _get_party_from_user(user)

    req_filters = {}
    if supplier:
        req_filters["supplier"] = supplier
    elif customer:
        req_filters["customer"] = customer
    else:
        return {
            "message": "No linked customer or supplier",
            "data": [],
            "meta": {
                "limit_start": limit_start,
                "limit_page_length": limit_page_length,
                "next_start": None,
            },
        }

    request_docs = frappe.get_all(
        "Request",
        filters=req_filters,
        fields=["name", "purchase_order_data"],
    )
    if not request_docs:
        return {
            "message": "No requests found",
            "data": [],
            "meta": {
                "limit_start": limit_start,
                "limit_page_length": limit_page_length,
                "next_start": None,
            },
        }

    request_names = [r.get("name") for r in request_docs]

    rows = frappe.get_all(
        "Request Product Item",
        filters={"parent": ["in", request_names]},
        fields=["item_code"],
    )
    requested_ids = set()
    for r in rows:
        code = r.get("item_code")
        if code:
            requested_ids.add(code)

    # Also include products selected in PO responses (purchase_order_data)
    for req in request_docs:
        po_data = req.get("purchase_order_data")
        if not po_data:
            continue
        try:
            parsed = json.loads(po_data) if isinstance(po_data, str) else po_data
        except Exception:
            continue
        if isinstance(parsed, dict):
            for pid in parsed.get("products") or []:
                if pid:
                    requested_ids.add(pid)

    if not requested_ids:
        return {
            "message": "No requested products found",
            "data": [],
            "meta": {
                "limit_start": limit_start,
                "limit_page_length": limit_page_length,
                "next_start": None,
            },
        }

    requested_ids = list(requested_ids)

    filters = {"name": ["in", requested_ids], "disabled": 0}
    or_filters = None
    if search:
        like = f"%{search}%"
        or_filters = [
            ["Item", "item_code", "like", like],
            ["Item", "item_name", "like", like],
        ]

    items: List[Dict] = frappe.get_all(
        "Item",
        fields=["name", "item_code", "item_name", "item_group", "stock_uom"],
        filters=filters,
        or_filters=or_filters,
        start=limit_start,
        page_length=limit_page_length,
        order_by="modified desc",
    )

    # collect item codes to fetch batches in one shot
    item_codes = [i["item_code"] for i in items if i.get("item_code")]
    batches_by_item: Dict[str, List[Dict]] = {}

    if item_codes:
        batch_rows = frappe.get_all(
            "Batch",
            fields=["name", "batch_id", "item", "expiry_date", "manufacturing_date"],
            filters={"item": ["in", item_codes]},
            order_by="creation desc",
            limit_page_length=5000,
        )
        for b in batch_rows:
            batches_by_item.setdefault(b["item"], []).append({
                "name": b["name"],
                "batch_id": b.get("batch_id"),
                "expiry_date": b.get("expiry_date"),
                "manufacturing_date": b.get("manufacturing_date"),
            })

    for it in items:
        it["batches"] = batches_by_item.get(it.get("item_code"), [])

    return {
        "message": f"Fetched {len(items)} requested products",
        "data": items,
        "meta": {
            "limit_start": limit_start,
            "limit_page_length": limit_page_length,
            "next_start": limit_start + len(items) if len(items) == limit_page_length else None,
        },
    }
