import frappe
import json
from typing import List, Dict


def _coerce_start(value, default=0):
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(parsed, 0)


def _coerce_page_length(value, default=200, max_size=500):
    try:
        parsed = int(value)
    except Exception:
        parsed = default

    if parsed <= 0:
        parsed = default
    return min(parsed, max_size)


def _count_items(filters=None, or_filters=None):
    rows = frappe.get_all(
        "Item",
        filters=filters or {},
        or_filters=or_filters,
        fields=["count(name) as total"],
    )
    if rows and rows[0].get("total") is not None:
        return int(rows[0].get("total") or 0)
    return 0


def _build_meta(limit_start, limit_page_length, total, returned):
    next_start = limit_start + returned if (limit_start + returned) < total else None
    total_pages = (total + limit_page_length - 1) // limit_page_length if limit_page_length else 0
    return {
        "limit_start": limit_start,
        "limit_page_length": limit_page_length,
        "next_start": next_start,
        "total": total,
        "total_pages": total_pages,
    }


@frappe.whitelist()
def get_products(search: str = None, limit_start: int = 0, limit_page_length: int = 200):
    """
    Returns Items linked to Request.requested_products for the current user
    (customer or supplier), with a batches array for each item.
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Not logged in", frappe.PermissionError)

    limit_start = _coerce_start(limit_start, default=0)
    limit_page_length = _coerce_page_length(limit_page_length, default=200, max_size=500)

    # Resolve current party
    from farmportal.api.requests import _get_party_from_user
    customer, supplier = _get_party_from_user(user)

    # Importer side: show all EUDR Commodities items
    if customer and not supplier:
        filters = {"item_group": "EUDR Commodities", "disabled": 0}
        or_filters = None
        if search:
            like = f"%{search}%"
            or_filters = [
                ["Item", "item_code", "like", like],
                ["Item", "item_name", "like", like],
            ]

        total = _count_items(filters=filters, or_filters=or_filters)

        items = frappe.get_all(
            "Item",
            fields=["name", "item_code", "item_name", "item_group", "stock_uom"],
            filters=filters,
            or_filters=or_filters,
            start=limit_start,
            page_length=limit_page_length,
            order_by="modified desc",
        )

        item_names = [i["name"] for i in items if i.get("name")]
        item_codes = [i["item_code"] for i in items if i.get("item_code")]
        lookup_ids = list({*item_names, *item_codes})
        batches_by_item = {}
        if lookup_ids:
            batch_rows = frappe.get_all(
                "Batch",
                fields=["name", "batch_id", "item", "expiry_date", "manufacturing_date"],
                filters={"item": ["in", lookup_ids]},
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
            it["batches"] = batches_by_item.get(it.get("name")) or batches_by_item.get(it.get("item_code"), [])

        return {
            "message": f"Fetched {len(items)} EUDR Commodities products",
            "data": items,
            "meta": _build_meta(limit_start, limit_page_length, total, len(items)),
        }

    req_filters = {}
    if supplier:
        req_filters["supplier"] = supplier
    elif customer:
        req_filters["customer"] = customer
    else:
        return {
            "message": "No linked customer or supplier",
            "data": [],
            "meta": _build_meta(limit_start, limit_page_length, 0, 0),
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
            "meta": _build_meta(limit_start, limit_page_length, 0, 0),
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
            "meta": _build_meta(limit_start, limit_page_length, 0, 0),
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

    total = _count_items(filters=filters, or_filters=or_filters)

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
    item_names = [i["name"] for i in items if i.get("name")]
    item_codes = [i["item_code"] for i in items if i.get("item_code")]
    lookup_ids = list({*item_names, *item_codes})
    batches_by_item: Dict[str, List[Dict]] = {}

    if lookup_ids:
        batch_rows = frappe.get_all(
            "Batch",
            fields=["name", "batch_id", "item", "expiry_date", "manufacturing_date"],
            filters={"item": ["in", lookup_ids]},
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
        it["batches"] = batches_by_item.get(it.get("name")) or batches_by_item.get(it.get("item_code"), [])

    return {
        "message": f"Fetched {len(items)} requested products",
        "data": items,
        "meta": _build_meta(limit_start, limit_page_length, total, len(items)),
    }
