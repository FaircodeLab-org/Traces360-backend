# Copyright (c) 2025, Mirshad and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from farmportal.notifications import send_request_created_email


class Request(Document):
    def after_insert(self):
        send_request_created_email(self)
