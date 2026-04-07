# Copyright (c) 2025, Mirshad and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from farmportal.notifications import send_questionnaire_created_email


class Questionnaire(Document):
    def after_insert(self):
        send_questionnaire_created_email(self)
