import frappe


def _get_index_columns(index_rows):
    indexes = {}
    for row in index_rows:
        key_name = str(row.get("Key_name") or "")
        if not key_name:
            continue
        indexes.setdefault(key_name, {"non_unique": int(row.get("Non_unique") or 1), "cols": []})
        indexes[key_name]["cols"].append((int(row.get("Seq_in_index") or 0), str(row.get("Column_name") or "")))
    for key_name, data in indexes.items():
        data["cols"] = [col for _seq, col in sorted(data["cols"], key=lambda x: x[0])]
    return indexes


def execute():
    if not frappe.db.table_exists("Land Plot"):
        return

    # 1) Drop single-column unique indexes on plot_id (legacy global uniqueness).
    index_rows = frappe.db.sql("SHOW INDEX FROM `tabLand Plot`", as_dict=True)
    indexes = _get_index_columns(index_rows)
    for key_name, data in indexes.items():
        if data["non_unique"] == 0 and data["cols"] == ["plot_id"]:
            frappe.db.sql(f"ALTER TABLE `tabLand Plot` DROP INDEX `{key_name}`")

    # 2) Add supplier+plot_id unique index (supplier-scoped uniqueness).
    index_rows = frappe.db.sql("SHOW INDEX FROM `tabLand Plot`", as_dict=True)
    indexes = _get_index_columns(index_rows)
    has_supplier_plot_unique = any(
        data["non_unique"] == 0 and data["cols"] == ["supplier", "plot_id"]
        for data in indexes.values()
    )
    if has_supplier_plot_unique:
        return

    duplicates = frappe.db.sql(
        """
        SELECT supplier, plot_id, COUNT(*) AS cnt
        FROM `tabLand Plot`
        GROUP BY supplier, plot_id
        HAVING COUNT(*) > 1
        LIMIT 1
        """,
        as_dict=True,
    )
    if duplicates:
        frappe.log_error(
            message=(
                "Skipped adding unique index on tabLand Plot(supplier, plot_id) "
                f"because duplicates exist: {duplicates[0]}"
            ),
            title="Land Plot Index Migration Skipped",
        )
        return

    frappe.db.sql(
        "ALTER TABLE `tabLand Plot` ADD UNIQUE INDEX `supplier_plot_id_unique` (`supplier`, `plot_id`)"
    )

