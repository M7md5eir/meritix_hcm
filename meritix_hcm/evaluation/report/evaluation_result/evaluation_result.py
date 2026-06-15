import frappe
from frappe import _
from frappe import scrub
from structure_link.filters import apply_structure_filter


def execute(filters=None):
    filters = filters or {}
    factors = get_factors(filters)
    columns = get_columns(factors)
    data = get_data(filters, factors)
    return columns, data


def get_factors(filters):
    values = {}
    conditions = ""
    if filters.get('evaluation_form'):
        conditions = "WHERE pfc.parent = %(evaluation_form)s AND pfc.parentfield = 'evaluation_factor_setup'"
        values['evaluation_form'] = filters['evaluation_form']

    return frappe.db.sql(f"""
        SELECT DISTINCT paf.name, paf.name, paf.structure_level, paf.doctype_list
        FROM `tabEvaluation Factor` paf
        INNER JOIN `tabEvaluation Factor Setup` pfc ON pfc.factor = paf.name
        {conditions}
        ORDER BY paf.name
    """, values, as_dict=True)


def get_columns(factors):
    columns = [
        {"fieldname": "evaluation_subject", "label": _("Emp ID"),        "fieldtype": "Link", "options": "Employee", "width": 100, "align": "left"},
        {"fieldname": "emp_name",           "label": _("Employee Name"), "fieldtype": "Data",                        "width": 300, "align": "left"},
        {"fieldname": "job",                "label": _("Job"),           "fieldtype": "Data",                        "width": 300, "align": "left"},
    ]
    for f in factors:
        columns.append({"fieldname": f.name, "label": f.name, "fieldtype": "Float", "width": 150, "align": "left"})
    columns.append({"fieldname": "final_score", "label": _("Final Score"), "fieldtype": "Float", "width": 175, "align": "left"})
    return columns


def get_permitted_subjects(filters):
    conditions = {
        "evaluation_factor_doctype": "Employee"
    }
    if filters.get('evaluation_form'):
        conditions['evaluation_form'] = filters['evaluation_form']
    if filters.get('evaluation_period'):
        conditions['evaluation_period'] = filters['evaluation_period']

    records = frappe.get_list(
        "Evaluation",
        filters=conditions,
        fields=["evaluation_subject"],
        ignore_permissions=False,
        limit=0
    )

    return list(set([r.evaluation_subject for r in records]))


def get_data(filters, factors):
    if not factors:
        return []
    if not filters.get('evaluation_form'):
        return []
    if not filters.get('evaluation_period'):
        return []

    conditions = "WHERE e.evaluation_factor_doctype = 'Employee'"
    values = {}

    for key in ('evaluation_form', 'evaluation_period'):
        if filters.get(key):
            conditions += f" AND e.{key} = %({key})s"
            values[key] = filters[key]

    # تطبيق صلاحيات عن طريق Frappe permissions
    permitted_subjects = get_permitted_subjects(filters)
    if permitted_subjects:
        subject_placeholders = []
        for i, subj in enumerate(permitted_subjects):
            key = f"subj_{i}"
            values[key] = subj
            subject_placeholders.append(f"%(subj_{i})s")
        conditions += f" AND e.evaluation_subject IN ({', '.join(subject_placeholders)})"
    else:
        # مفيش subjects مسموح بيها خالص
        return []

    sc_cond, sc_values = apply_structure_filter(filters, fieldname="organization", alias="e", tree_doctype="Organization")
    conditions += sc_cond
    values.update(sc_values)

    factor_selects_parts = []
    for f in factors:
        factor_selects_parts.append(f"""
        , SUM(CASE WHEN e.evaluation_factor = '{f.name}' AND e.docstatus = 1 THEN e.final_score ELSE 0 END) AS `{f.name}_emp`
        , SUM(CASE WHEN e.evaluation_factor = '{f.name}' AND e.docstatus = 1 THEN 1 ELSE 0 END) AS `{f.name}_emp_count`
        """)

        if f.doctype_list == 'Organization' and f.structure_level:
            field_name = scrub(f.structure_level)
            factor_selects_parts.append(f"""
        , COALESCE((
            SELECT o.final_score FROM `tabEvaluation` o
            WHERE o.evaluation_form = e.evaluation_form
            AND o.evaluation_period = e.evaluation_period
            AND o.evaluation_factor_doctype = 'Organization'
            AND o.evaluation_factor = '{f.name}'
            AND o.evaluation_subject = e.`{field_name}`
            AND o.docstatus = 1
            LIMIT 1
        ), 0) AS `{f.name}_org`
        , COALESCE((
            SELECT COUNT(*) FROM `tabEvaluation` o
            WHERE o.evaluation_form = e.evaluation_form
            AND o.evaluation_period = e.evaluation_period
            AND o.evaluation_factor_doctype = 'Organization'
            AND o.evaluation_factor = '{f.name}'
            AND o.evaluation_subject = e.`{field_name}`
            AND o.docstatus = 1
        ), 0) AS `{f.name}_org_count`
            """)
        else:
            factor_selects_parts.append(f"""
        , 0 AS `{f.name}_org`
        , 0 AS `{f.name}_org_count`
            """)

    factor_selects = "".join(factor_selects_parts)

    rows = frappe.db.sql(f"""
        SELECT e.evaluation_subject
        , MAX(e.emp_name) AS emp_name
        , MAX(e.job) AS job
        {factor_selects}
        FROM `tabEvaluation` e
        LEFT JOIN `tabEvaluation Form` ef ON ef.name = e.evaluation_form
        {conditions}
        GROUP BY e.evaluation_subject
    """, values, as_dict=True)

    result = []
    for row in rows:
        final_score = 0
        new_row = {
            "evaluation_subject": row.evaluation_subject,
            "emp_name": row.get('emp_name'),
            "job": row.get('job'),
        }
        for f in factors:
            emp_count = row.get(f'{f.name}_emp_count') or 0
            org_count = row.get(f'{f.name}_org_count') or 0
            score = (row.get(f'{f.name}_emp') or 0) + (row.get(f'{f.name}_org') or 0)
            new_row[f.name] = score
            new_row[f'{f.name}_submitted'] = (emp_count + org_count) > 0
            final_score += score
        new_row['final_score'] = final_score
        result.append(new_row)

    return result


def _org_filter(filters):
    node = filters.get("organization")
    if not node:
        return "", {}

    if (filters.get("organization_match_mode") or "=") == "descendants of (inclusive)":
        row = frappe.db.get_value("Organization", node, ["lft", "rgt"], as_dict=True)
        if row and row.lft is not None:
            return (
                " AND o.organization IN (SELECT name FROM `tabOrganization` WHERE lft >= %(org_lft)s AND rgt <= %(org_rgt)s)",
                {"org_lft": row.lft, "org_rgt": row.rgt},
            )

    return " AND o.organization = %(org_val)s", {"org_val": node}