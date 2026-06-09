import frappe
from frappe import _
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
        SELECT DISTINCT paf.name, paf.name
        FROM `tabEvaluation Factor` paf
        INNER JOIN `tabEvaluation Factor Setup` pfc ON pfc.factor = paf.name
        {conditions}
        ORDER BY paf.name
    """, values, as_dict=True)


def get_columns(factors):
    columns = [
        {"fieldname": "evaluation_subject", "label": _("Emp ID"),        "fieldtype": "Link", "options": "Employee", "width": 100},
        {"fieldname": "emp_name",           "label": _("Employee Name"), "fieldtype": "Data",                        "width": 300},
        {"fieldname": "job",                "label": _("Job"),           "fieldtype": "Data",                        "width": 150},
    ]
    for f in factors:
        columns.append({"fieldname": f.name, "label": f.name, "fieldtype": "Float", "width": 150})
    columns.append({"fieldname": "final_score", "label": _("Final Score"), "fieldtype": "Float", "width": 150})
    return columns


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

    sc_cond, sc_values = apply_structure_filter(filters, fieldname="organization", alias="e", tree_doctype="Organization")
    conditions += sc_cond
    values.update(sc_values)

    org_cond, org_values = _org_filter(filters)
    values.update(org_values)

    factor_selects = "".join(f"""
        , SUM(CASE WHEN e.evaluation_factor = '{f.name}' AND e.docstatus = 1 THEN e.final_score ELSE 0 END) AS `{f.name}_emp`
        , SUM(CASE WHEN e.evaluation_factor = '{f.name}' AND e.docstatus = 1 THEN 1 ELSE 0 END) AS `{f.name}_emp_count`
        , COALESCE((
            SELECT SUM(o.final_score) FROM `tabEvaluation` o
            WHERE o.evaluation_form = e.evaluation_form
            AND o.evaluation_period = e.evaluation_period
            AND o.evaluation_factor_doctype = 'Organization'
            AND o.evaluation_factor = '{f.name}'
            AND o.docstatus = 1 {org_cond}
        ), 0) AS `{f.name}_org`
        , COALESCE((
            SELECT COUNT(*) FROM `tabEvaluation` o
            WHERE o.evaluation_form = e.evaluation_form
            AND o.evaluation_period = e.evaluation_period
            AND o.evaluation_factor_doctype = 'Organization'
            AND o.evaluation_factor = '{f.name}'
            AND o.docstatus = 1 {org_cond}
        ), 0) AS `{f.name}_org_count`
    """ for f in factors)

    rows = frappe.db.sql(f"""
        SELECT e.evaluation_subject
        {factor_selects}
        FROM `tabEvaluation` e
        LEFT JOIN `tabEvaluation Form` ef ON ef.name = e.evaluation_form
        {conditions}
        GROUP BY e.evaluation_subject
    """, values, as_dict=True)

    result = []
    for row in rows:
        final_score = 0
        emp = frappe.db.get_value('Employee', row.evaluation_subject, ['emp_name', 'job'], as_dict=True) or {}
        new_row = {
            "evaluation_subject": row.evaluation_subject,
            "emp_name": emp.get('emp_name'),
            "job": emp.get('job'),
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