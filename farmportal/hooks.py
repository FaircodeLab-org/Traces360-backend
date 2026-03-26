app_name = "farmportal"
app_title = "Farmportal"
app_publisher = "Mirshad"
app_description = "Farm portal"
app_email = "abdullamirshadcl@gmail.com"
app_license = "mit"

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            ["dt", "in", ["Supplier", "Customer"]],
            ["fieldname", "=", "custom_user"],
        ],
    },
    {
        "dt": "Item Group",
        "filters": [["name", "=", "EUDR Commodities"]],
    },
    {
        "dt": "Item",
        "filters": [["item_group", "=", "EUDR Commodities"]],
    },
]

# your_app/hooks.py
doc_events = {
    "Supplier": {
        "validate": "farmportal.api.organization_profile.manage_organization_users"
    }
}


# CORS Configuration - Add this section
override_whitelisted_methods = {
    "farmportal.auth_helper.login_and_get_api_keys": "farmportal.auth_helper.login_and_get_api_keys",
    "farmportal.auth_helper.regenerate_api_keys": "farmportal.auth_helper.regenerate_api_keys",
    "farmportal.custom_api.get_current_user": "farmportal.custom_api.get_current_user"
}


# # Allow CORS for specific origins
# allow_cors_origins = ["https://farm-portal-2cpb.vercel.app"]

# # Add response headers to all requests
# response_headers = {
#     "Access-Control-Allow-Origin": "https://farm-portal-2cpb.vercel.app",
#     "Access-Control-Allow-Credentials": "true",
#     "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
#     "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Frappe-CSRF-Token, Accept",
# }

# # Handle OPTIONS requests
# def on_request():
#     import frappe
#     if frappe.request.method == "OPTIONS":
#         frappe.local.response = frappe._dict({
#             "http_status_code": 200,
#             "message": "ok"
#         })
#         add_response_headers()
        
# def add_response_headers():
#     import frappe
#     if frappe.local.response:
#         for key, value in response_headers.items():
#             frappe.local.response.setdefault("headers", {})[key] = value

# # Register hooks
# before_request = ["farmportal.hooks.on_request"]
# after_request = ["farmportal.hooks.add_response_headers"]

# def boot_session(bootinfo):
#     """Set cookie settings for cross-origin"""
#     frappe.local.cookie_manager.set_cookie(
#         "sid", frappe.session.sid,
#         httponly=True,
#         samesite="None",
#         secure=True
#     )

# # Add to hooks
# boot_session = "farmportal.hooks.boot_session"



# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "farmportal",
# 		"logo": "/assets/farmportal/logo.png",
# 		"title": "Farmportal",
# 		"route": "/farmportal",
# 		"has_permission": "farmportal.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/farmportal/css/farmportal.css"
# app_include_js = "/assets/farmportal/js/farmportal.js"

# include js, css files in header of web template
# web_include_css = "/assets/farmportal/css/farmportal.css"
# web_include_js = "/assets/farmportal/js/farmportal.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "farmportal/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "farmportal/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "farmportal.utils.jinja_methods",
# 	"filters": "farmportal.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "farmportal.install.before_install"
# after_install = "farmportal.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "farmportal.uninstall.before_uninstall"
# after_uninstall = "farmportal.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "farmportal.utils.before_app_install"
# after_app_install = "farmportal.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "farmportal.utils.before_app_uninstall"
# after_app_uninstall = "farmportal.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "farmportal.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"farmportal.tasks.all"
# 	],
# 	"daily": [
# 		"farmportal.tasks.daily"
# 	],
# 	"hourly": [
# 		"farmportal.tasks.hourly"
# 	],
# 	"weekly": [
# 		"farmportal.tasks.weekly"
# 	],
# 	"monthly": [
# 		"farmportal.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "farmportal.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "farmportal.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "farmportal.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["farmportal.utils.before_request"]
# after_request = ["farmportal.utils.after_request"]

# Job Events
# ----------
# before_job = ["farmportal.utils.before_job"]
# after_job = ["farmportal.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"farmportal.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
