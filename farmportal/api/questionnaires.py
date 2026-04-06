from __future__ import annotations
import json
import frappe
from frappe import _ as _t
from frappe.utils.file_manager import save_file

DT = "Questionnaire"
CHILD_DT = "Questionnaire Question"
TEMPLATE_DT = "Questionnaire Template"
TEMPLATE_CHILD_DT = "Questionnaire Template Question"
CHOICE_INPUT_TYPES = {"Multiple Choice", "Checkbox", "Dropdown"}
SECTION_INPUT_TYPE = "Section"


def _coerce_page(value, default=1):
    try:
        page = int(value)
        return page if page > 0 else default
    except (TypeError, ValueError):
        return default


def _coerce_page_size(value, default=25, max_size=100):
    try:
        size = int(value)
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


# Reuse your helper from requests.py if available
try:
    from farmportal.api.requests import _get_party_from_user  # (customer, supplier)
except Exception:
    def _get_party_from_user(user: str):
        return None, None


def _as_list(v):
    """Convert input to list."""
    if not v:
        return []
    if isinstance(v, list):
        return v
    try:
        return json.loads(v)
    except Exception:
        return []


def _ensure_options(opts):
    """Accept ['A','B'] or "A\nB" and return newline string."""
    if isinstance(opts, str):
        return opts.strip()
    if isinstance(opts, list):
        return "\n".join([str(x).strip() for x in opts if str(x).strip()])
    return ""


def _normalize_input_type(input_type: str) -> str:
    """Normalize input type to standard values."""
    normalized = str(input_type or "").strip().lower()
    type_map = {
        'short answer': 'Short Answer',
        'short': 'Short Answer',
        'paragraph': 'Paragraph',
        'multiple choice': 'Multiple Choice',
        'radio': 'Multiple Choice',
        'checkbox': 'Checkbox',
        'check': 'Checkbox',
        'dropdown': 'Dropdown',
        'select': 'Dropdown',
        'date': 'Date',
        'section': 'Section',
        'text': 'Text',
        'file upload': 'File',
        'file': 'File',
        'attach': 'File'
    }
    return type_map.get(normalized, 'Short Answer')


def _is_effectively_empty_answer(row) -> bool:
    input_type = str(row.input_type or "").strip()
    if input_type == SECTION_INPUT_TYPE:
        return False

    answer = row.answer
    if answer is None:
        return True

    if input_type == "Checkbox":
        if isinstance(answer, list):
            return len([x for x in answer if str(x).strip()]) == 0
        answer_text = str(answer).strip()
        if not answer_text:
            return True
        try:
            parsed = json.loads(answer_text)
            if isinstance(parsed, list):
                return len([x for x in parsed if str(x).strip()]) == 0
        except Exception:
            pass
        return False

    return str(answer).strip() == ""


def _parse_payload(kwargs: dict) -> dict:
    payload = frappe._dict(kwargs or {})
    raw_data = payload.get("data")
    if raw_data:
        try:
            if isinstance(raw_data, str):
                parsed = json.loads(raw_data)
            elif isinstance(raw_data, dict):
                parsed = raw_data
            else:
                parsed = {}
            if isinstance(parsed, dict):
                payload.update(parsed)
        except Exception:
            pass
    return payload


def _resolve_customer_for_user(user: str) -> str | None:
    customer, _supplier = _get_party_from_user(user)
    if customer:
        return customer
    for fieldname in ("custom_user", "user_id", "user"):
        try:
            customer = frappe.db.get_value("Customer", {fieldname: user}, "name")
        except Exception:
            customer = None
        if customer:
            return customer
    return None


def _resolve_supplier_for_user(user: str) -> str | None:
    _customer, supplier = _get_party_from_user(user)
    if supplier:
        return supplier
    for fieldname in ("custom_user", "user_id", "user"):
        try:
            supplier = frappe.db.get_value("Supplier", {fieldname: user}, "name")
        except Exception:
            supplier = None
        if supplier:
            return supplier
    return None


def _is_system_manager(user: str) -> bool:
    try:
        return "System Manager" in frappe.get_roles(user)
    except Exception:
        return False


def _parse_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _validate_question_payload(qlist: list[dict]) -> None:
    if not qlist:
        frappe.throw(_t("Questions are required"))

    has_real_question = False
    for q in qlist:
        if not isinstance(q, dict):
            continue

        question = (q.get("question") or q.get("question_text") or "").strip()
        input_type = _normalize_input_type(q.get("input_type") or q.get("type") or "Short Answer")

        if not question:
            frappe.throw(_t("Question text is required"))

        if input_type != SECTION_INPUT_TYPE:
            has_real_question = True

        if input_type in CHOICE_INPUT_TYPES:
            options = [x.strip() for x in _ensure_options(q.get("options")).splitlines() if x.strip()]
            if not options:
                frappe.throw(_t("Options are required for question: {0}").format(question))

    if not has_real_question:
        frappe.throw(_t("At least one non-section question is required"))


def _append_question_rows(doc, qlist: list[dict], table_field: str = "questions") -> None:
    for q in qlist:
        if not isinstance(q, dict):
            continue

        item = doc.append(table_field, {})
        item.question = (q.get("question") or q.get("question_text") or "").strip()
        raw_type = q.get("input_type") or q.get("type") or "Short Answer"
        item.input_type = _normalize_input_type(raw_type)

        if item.input_type == SECTION_INPUT_TYPE:
            item.required = 0
            item.options_raw = (q.get("description") or q.get("section_description") or "").strip()
            continue

        item.required = 1 if q.get("required") else 0
        if item.input_type in CHOICE_INPUT_TYPES:
            item.options_raw = _ensure_options(q.get("options"))
        else:
            item.options_raw = ""


def _serialize_question_row(row) -> dict:
    options = []
    if row.input_type in CHOICE_INPUT_TYPES:
        options = (row.options_raw or "").splitlines()
    description = (row.options_raw or "") if row.input_type == SECTION_INPUT_TYPE else ""
    return {
        "rowname": row.name,
        "question": row.question,
        "input_type": row.input_type,
        "options": options,
        "description": description,
        "required": int(row.required or 0),
        "answer": row.answer or "",
    }


def _ensure_template_access(doc, customer: str | None, is_manager: bool):
    if is_manager:
        return
    if int(doc.get("is_public") or 0):
        return
    if customer and doc.get("customer") == customer:
        return
    frappe.throw(_t("Not permitted to access this template"), frappe.PermissionError)



def _find_template_with_same_title(title: str, customer: str | None, exclude_id: str | None = None) -> str | None:
    wanted = str(title or "").strip().lower()
    if not wanted:
        return None

    rows = frappe.get_all(
        TEMPLATE_DT,
        filters={"is_active": 1},
        fields=["name", "title", "customer"],
        limit_page_length=2000,
    )

    scope_customer = (customer or "").strip()
    for row in rows:
        if exclude_id and row.get("name") == exclude_id:
            continue

        row_customer = str(row.get("customer") or "").strip()
        if row_customer != scope_customer:
            continue

        row_title = str(row.get("title") or "").strip().lower()
        if row_title == wanted:
            return row.get("name")

    return None

@frappe.whitelist()
def create_questionnaire(supplier_id: str = None, title: str = None, questions: list | str = None, due_date: str | None = None, **kwargs):
    """
    Customer creates a questionnaire with actual questions.
    
    Args:
        supplier_id: ID of the supplier to send questionnaire to
        title: Title of the questionnaire
        questions: List of question objects with structure:
            {
                question: str,
                input_type: 'Short Answer' | 'Paragraph' | 'Multiple Choice' | 'Checkbox'
                            | 'Dropdown' | 'File' | 'Date' | 'Section',
                options: list (required for Multiple Choice / Checkbox / Dropdown),
                description: str (optional, for Section),
                required: 0 | 1
            }
        due_date: Optional due date in YYYY-MM-DD format
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_t("Not logged in"), frappe.PermissionError)

    payload = _parse_payload(kwargs)
    supplier_id = supplier_id or payload.get("supplier_id") or payload.get("supplier") or payload.get("supplier_name")
    title = title or payload.get("title")
    questions = questions if questions is not None else payload.get("questions")
    due_date = due_date or payload.get("due_date")

    customer = _resolve_customer_for_user(user)
    supplier_flag = _resolve_supplier_for_user(user)
    if not customer:
        frappe.throw(_t("No Customer linked to your user ({0})").format(user), frappe.PermissionError)
    if supplier_flag and not customer:
        frappe.throw(_t("Suppliers cannot create questionnaires"), frappe.PermissionError)

    if not supplier_id:
        frappe.throw(_t("Supplier is required"))
    if not title:
        frappe.throw(_t("Title is required"))

    if not frappe.db.exists("Supplier", supplier_id):
        by_supplier_name = frappe.db.get_value("Supplier", {"supplier_name": supplier_id}, "name")
        if by_supplier_name:
            supplier_id = by_supplier_name
        else:
            frappe.throw(_t("Supplier '{0}' not found").format(supplier_id))

    qlist = _as_list(questions)
    _validate_question_payload(qlist)

    doc = frappe.new_doc(DT)
    doc.title = title
    doc.customer = customer
    doc.supplier = supplier_id
    doc.status = "Pending"
    doc.created_by = user
    if due_date:
        doc.due_date = due_date

    _append_question_rows(doc, qlist, table_field="questions")

    # Some sites may have custom mandatory parent fields on Questionnaire
    # (e.g. static form fields) that are unrelated to this API-driven flow.
    # We intentionally bypass those and validate dynamic question rows ourselves.
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True, ignore_mandatory=True)
    frappe.db.commit()
    return {"id": doc.name, "status": doc.status, "message": _t("Questionnaire created successfully")}


@frappe.whitelist()
def list_for_me(status: str | None = None, page=1, page_size=25):
    """
    List questionnaires for the logged-in user.
    
    Returns questionnaires where the user is either:
    - The customer (created by them)
    - The supplier (sent to them)
    
    Args:
        status: Optional status filter ('Pending', 'Completed', 'Denied')
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_t("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    filters = {}
    role = None
    
    if supplier and not customer:
        role = "supplier"
        filters["supplier"] = supplier
    elif customer:
        role = "customer"
        filters["customer"] = customer
    else:
        return {"items": [], "role": None}

    if status:
        filters["status"] = status

    page_no = _coerce_page(page, default=1)
    page_len = _coerce_page_size(page_size, default=25, max_size=100)
    offset = (page_no - 1) * page_len

    total = int(frappe.db.count(DT, filters=filters) or 0)

    rows = frappe.get_all(
        DT,
        filters=filters,
        fields=[
            "name as id", "title", "customer", "supplier", "status",
            "due_date", "creation", "modified", "responded_by", "submitted_on"
        ],
        order_by="creation desc",
        limit_start=offset,
        limit_page_length=page_len,
    )
    return {
        "items": rows,
        "role": role,
        "pagination": _build_pagination(page_no, page_len, total),
    }


@frappe.whitelist()
def list_templates(page=1, page_size=25):
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_t("Not logged in"), frappe.PermissionError)

    customer = _resolve_customer_for_user(user)
    is_manager = _is_system_manager(user)

    page_no = _coerce_page(page, default=1)
    page_len = _coerce_page_size(page_size, default=25, max_size=100)
    offset = (page_no - 1) * page_len

    filters = {"is_active": 1}
    or_filters = None

    if not is_manager:
        if customer:
            or_filters = [
                [TEMPLATE_DT, "is_public", "=", 1],
                [TEMPLATE_DT, "customer", "=", customer],
            ]
        else:
            filters["is_public"] = 1

    total_rows = frappe.get_all(
        TEMPLATE_DT,
        fields=["count(name) as total"],
        filters=filters,
        or_filters=or_filters,
    )
    total = int((total_rows[0] or {}).get("total") or 0) if total_rows else 0
    rows = frappe.get_all(
        TEMPLATE_DT,
        fields=[
            "name as id", "title", "description", "customer",
            "created_by", "is_public", "is_active", "modified"
        ],
        filters=filters,
        or_filters=or_filters,
        order_by="modified desc",
        limit_start=offset,
        limit_page_length=page_len,
    )

    items = [{
        "id": row.get("id"),
        "title": row.get("title"),
        "description": row.get("description") or "",
        "customer": row.get("customer"),
        "created_by": row.get("created_by"),
        "is_public": int(row.get("is_public") or 0),
        "modified": row.get("modified"),
    } for row in rows]

    return {
        "items": items,
        "pagination": _build_pagination(page_no, page_len, total),
    }


@frappe.whitelist()
def get_template(template_id: str):
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_t("Not logged in"), frappe.PermissionError)
    if not template_id:
        frappe.throw(_t("Template ID is required"))

    customer = _resolve_customer_for_user(user)
    is_manager = _is_system_manager(user)

    doc = frappe.get_doc(TEMPLATE_DT, template_id)
    _ensure_template_access(doc, customer, is_manager)

    questions = []
    for row in doc.get("questions") or []:
        options = []
        if row.input_type in CHOICE_INPUT_TYPES:
            options = (row.options_raw or "").splitlines()
        description = (row.options_raw or "") if row.input_type == SECTION_INPUT_TYPE else ""
        questions.append({
            "rowname": row.name,
            "question": row.question,
            "input_type": row.input_type,
            "options": options,
            "description": description,
            "required": int(row.required or 0),
        })

    return {
        "id": doc.name,
        "title": doc.title,
        "description": doc.description or "",
        "is_public": int(doc.is_public or 0),
        "customer": doc.customer,
        "questions": questions,
    }


@frappe.whitelist()
def save_template(
    template_id: str | None = None,
    title: str | None = None,
    questions: list | str = None,
    description: str | None = None,
    is_public: int | str | None = 0,
    **kwargs
):
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_t("Not logged in"), frappe.PermissionError)

    payload = _parse_payload(kwargs)
    template_id = template_id or payload.get("template_id") or payload.get("id")
    title = title or payload.get("title")
    description = description if description is not None else payload.get("description")
    questions = questions if questions is not None else payload.get("questions")
    is_public = payload.get("is_public", is_public)

    if not title:
        frappe.throw(_t("Template title is required"))
    normalized_title = str(title).strip()
    if not normalized_title:
        frappe.throw(_t("Template title is required"))

    customer = _resolve_customer_for_user(user)
    is_manager = _is_system_manager(user)
    if not customer and not is_manager:
        frappe.throw(_t("Only importer/customer users can manage templates"), frappe.PermissionError)

    qlist = _as_list(questions)
    _validate_question_payload(qlist)

    if template_id:
        doc = frappe.get_doc(TEMPLATE_DT, template_id)
        if not is_manager and doc.customer != customer:
            frappe.throw(_t("Not permitted to update this template"), frappe.PermissionError)
    else:
        doc = frappe.new_doc(TEMPLATE_DT)
        doc.customer = customer if customer else None
        doc.created_by = user

    scope_customer = (doc.get("customer") or customer or "").strip() or None
    duplicate_id = _find_template_with_same_title(
        normalized_title,
        scope_customer,
        exclude_id=(doc.name if template_id else None),
    )
    if duplicate_id:
        frappe.throw(_t("Template name '{0}' already exists").format(normalized_title))

    doc.title = normalized_title
    doc.description = (description or "").strip()
    doc.is_public = 1 if _parse_bool(is_public, default=False) else 0
    doc.is_active = 1
    doc.set("questions", [])
    _append_question_rows(doc, qlist, table_field="questions")

    doc.flags.ignore_mandatory = True
    if template_id:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True, ignore_mandatory=True)
    frappe.db.commit()

    return {"id": doc.name, "message": _t("Template saved successfully")}


@frappe.whitelist()
def create_questionnaire_from_template(
    template_id: str = None,
    supplier_id: str = None,
    due_date: str | None = None,
    title: str | None = None,
    **kwargs
):
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_t("Not logged in"), frappe.PermissionError)

    payload = _parse_payload(kwargs)
    template_id = template_id or payload.get("template_id") or payload.get("id")
    supplier_id = supplier_id or payload.get("supplier_id") or payload.get("supplier") or payload.get("supplier_name")
    due_date = due_date or payload.get("due_date")
    title = title or payload.get("title")

    if not template_id:
        frappe.throw(_t("Template ID is required"))
    if not supplier_id:
        frappe.throw(_t("Supplier is required"))

    customer = _resolve_customer_for_user(user)
    if not customer:
        frappe.throw(_t("No Customer linked to your user ({0})").format(user), frappe.PermissionError)

    is_manager = _is_system_manager(user)
    template_doc = frappe.get_doc(TEMPLATE_DT, template_id)
    _ensure_template_access(template_doc, customer, is_manager)

    if not frappe.db.exists("Supplier", supplier_id):
        by_supplier_name = frappe.db.get_value("Supplier", {"supplier_name": supplier_id}, "name")
        if by_supplier_name:
            supplier_id = by_supplier_name
        else:
            frappe.throw(_t("Supplier '{0}' not found").format(supplier_id))

    qlist = []
    for row in template_doc.get("questions") or []:
        qlist.append({
            "question": row.question,
            "input_type": row.input_type,
            "required": int(row.required or 0),
            "options": (row.options_raw or "").splitlines() if row.input_type in CHOICE_INPUT_TYPES else [],
            "description": (row.options_raw or "") if row.input_type == SECTION_INPUT_TYPE else "",
        })

    _validate_question_payload(qlist)

    doc = frappe.new_doc(DT)
    doc.title = (title or template_doc.title or "Questionnaire").strip()
    doc.customer = customer
    doc.supplier = supplier_id
    doc.status = "Pending"
    doc.created_by = user
    if due_date:
        doc.due_date = due_date

    _append_question_rows(doc, qlist, table_field="questions")

    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True, ignore_mandatory=True)
    frappe.db.commit()
    return {"id": doc.name, "status": doc.status, "message": _t("Questionnaire created successfully from template")}


@frappe.whitelist()
def get_one(q_id: str):
    """
    Return questionnaire with its questions and answers.
    
    Args:
        q_id: Questionnaire ID
        
    Returns:
        Dictionary with questionnaire details and questions array
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_t("Not logged in"), frappe.PermissionError)

    doc = frappe.get_doc(DT, q_id)
    customer, supplier = _get_party_from_user(user)
    is_manager = _is_system_manager(user)
    if not is_manager and doc.customer != customer and doc.supplier != supplier:
        frappe.throw(_t("Not permitted to view this questionnaire"), frappe.PermissionError)
    
    # Serialize questions (include child row name so we can map answers)
    questions = []
    for row in doc.get("questions") or []:
        opts = []
        if row.input_type in CHOICE_INPUT_TYPES:
            opts = (row.options_raw or "").splitlines()
        section_description = (row.options_raw or "") if row.input_type == SECTION_INPUT_TYPE else ""
        
        questions.append({
            "rowname": row.name,          # child row id for mapping answers
            "question": row.question,
            "input_type": row.input_type,
            "options": opts,
            "description": section_description,
            "required": int(row.required or 0),
            "answer": row.answer or ""
        })
    
    return {
        "id": doc.name,
        "title": doc.title,
        "customer": doc.customer,
        "supplier": doc.supplier,
        "status": doc.status,
        "due_date": doc.due_date,
        "creation": doc.creation,
        "response_message": doc.get("response_message") or "",
        "questions": questions
    }


@frappe.whitelist()
def upload_questionnaire_file(q_id: str, rowname: str):
    """
    Upload a file for a specific questionnaire question.
    Call this before submitting answers to get the file_url.
    
    Args:
        q_id: Questionnaire ID
        rowname: Child table row name (question identifier)
        
    Returns:
        Dictionary with file_url, file_name, and rowname
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_t("Not logged in"), frappe.PermissionError)

    # Verify access
    doc = frappe.get_doc(DT, q_id)
    _, supplier = _get_party_from_user(user)
    
    if not supplier or supplier != doc.supplier:
        frappe.throw(_t("Not permitted to upload files"), frappe.PermissionError)

    # Verify questionnaire is in editable state
    if doc.status not in ["Pending", "Draft"]:
        frappe.throw(_t("Cannot upload files to completed questionnaire"))

    # Get the uploaded file from request
    if 'file' not in frappe.request.files:
        frappe.throw(_t("No file uploaded"))

    uploaded_file = frappe.request.files['file']
    
    if not uploaded_file.filename:
        frappe.throw(_t("Invalid file"))
    
    file_name = uploaded_file.filename
    file_data = uploaded_file.read()

    # Verify this is a file-type question
    child_map = {row.name: row for row in (doc.get("questions") or [])}
    question_row = child_map.get(rowname)
    
    if not question_row:
        frappe.throw(_t("Question not found"))
    
    if question_row.input_type != "File":
        frappe.throw(_t("This question does not accept file uploads"))

    # Save file attached to the questionnaire document
    saved_file = save_file(
        fname=file_name,
        content=file_data,
        dt=DT,
        dn=q_id,
        is_private=1
    )

    frappe.db.commit()

    # Return the file URL to store in the answer
    return {
        "file_url": saved_file.file_url,
        "file_name": saved_file.file_name,
        "rowname": rowname,
        "message": _t("File uploaded successfully")
    }


@frappe.whitelist()
def submit_answers(q_id: str = None, answers: dict | str = None, message: str | None = None, action: str | None = None, **kwargs):
    """
    Submit or update answers for a questionnaire.
    
    Args:
        q_id: Questionnaire ID
        answers: Dictionary mapping rowname to answer value (for File type, should be file_url)
        message: Optional response message
        action: Optional action ('complete', 'deny', etc.)
        
    Returns:
        Dictionary with updated status
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_t("Not logged in"), frappe.PermissionError)

    payload = _parse_payload(kwargs)
    q_id = q_id or payload.get("q_id") or payload.get("id") or payload.get("questionnaire_id")
    answers = answers if answers is not None else payload.get("answers")
    if message is None:
        message = payload.get("message")
    if action is None:
        action = payload.get("action")

    if not q_id:
        frappe.throw(_t("Questionnaire ID is required"))

    supplier = _resolve_supplier_for_user(user)
    doc = frappe.get_doc(DT, q_id)
    
    if not supplier or supplier != doc.supplier:
        frappe.throw(_t("Not permitted to respond"), frappe.PermissionError)

    # Parse answers - may arrive as JSON string, dict, "", or null
    amap = {}
    if isinstance(answers, dict):
        amap = answers
    elif isinstance(answers, str) and answers.strip():
        try:
            amap = json.loads(answers)
        except Exception:
            amap = {}

    # Update child table answers
    child_map = {row.name: row for row in (doc.get("questions") or [])}
    for rowname, val in amap.items():
        row = child_map.get(rowname)
        if row:
            if val is None:
                row.answer = ""
            elif isinstance(val, (list, dict)):
                row.answer = json.dumps(val, ensure_ascii=False)
            else:
                row.answer = str(val)

    if message is not None:
        doc.response_message = message

    # Handle status changes based on action
    token = (action or "").strip().lower()
    if token in {"complete", "accept", "submit", "done"}:
        # Validate required fields before completing
        missing_required = []
        for row in (doc.get("questions") or []):
            if not row.required:
                continue
            if str(row.input_type or "").strip() == SECTION_INPUT_TYPE:
                continue
            if _is_effectively_empty_answer(row):
                missing_required.append(row.question)
        
        if missing_required:
            frappe.throw(
                _t("Please answer all required questions: {0}").format(", ".join(missing_required))
            )
        
        doc.status = "Completed"
        doc.submitted_on = frappe.utils.now_datetime()
        doc.responded_by = user
    elif token in {"deny", "reject", "rejected", "decline"}:
        doc.status = "Denied"
        doc.responded_by = user
        if not message:
            doc.response_message = "Denied by supplier"

    # Keep API flow resilient to unrelated custom mandatory parent fields.
    doc.flags.ignore_mandatory = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    return {
        "id": doc.name,
        "status": doc.status,
        "message": _t("Saved successfully")
    }


@frappe.whitelist()
def delete_questionnaire(q_id: str):
    """
    Delete a questionnaire (customer only).
    
    Args:
        q_id: Questionnaire ID
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_t("Not logged in"), frappe.PermissionError)

    customer, _ = _get_party_from_user(user)
    doc = frappe.get_doc(DT, q_id)
    
    if not customer or customer != doc.customer:
        frappe.throw(_t("Not permitted to delete"), frappe.PermissionError)
    
    doc.delete(ignore_permissions=True)
    frappe.db.commit()
    
    return {"message": _t("Questionnaire deleted successfully")}
