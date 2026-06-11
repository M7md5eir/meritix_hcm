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

    emp_factors = [f for f in factors if f.doctype_list == 'Employee']
    org_factors = [f for f in factors if f.doctype_list == 'Organization']

    factor_structure = {}
    for f in org_factors:
        factor_structure[f.name] = scrub(f.structure_level) if f.structure_level else None

    conditions = "WHERE e.evaluation_factor_doctype = 'Employee'"
    values = {}

    for key in ('evaluation_form', 'evaluation_period'):
        if filters.get(key):
            conditions += f" AND e.{key} = %({key})s"
            values[key] = filters[key]

    sc_cond, sc_values = apply_structure_filter(filters, fieldname="organization", alias="e", tree_doctype="Organization")
    conditions += sc_cond
    values.update(sc_values)

    emp_factor_selects = "".join(f"""
        , SUM(CASE WHEN e.evaluation_factor = '{f.name}' AND e.docstatus = 1 THEN e.final_score ELSE 0 END) AS `{f.name}_emp`
    """ for f in emp_factors)

    rows = frappe.db.sql(f"""
        SELECT e.evaluation_subject
        {emp_factor_selects}
        FROM `tabEvaluation` e
        LEFT JOIN `tabEvaluation Form` ef ON ef.name = e.evaluation_form
        {conditions}
        GROUP BY e.evaluation_subject
    """, values, as_dict=True)

    if not rows:
        return []

    emp_names = [r.evaluation_subject for r in rows]
    emp_data = {}
    if emp_names:
        placeholders = ", ".join(["%s"] * len(emp_names))
        emp_records = frappe.db.sql(f"""
            SELECT name, emp_name, job, bu, sub_bu, sector, department, company, organization
            FROM `tabEmployee`
            WHERE name IN ({placeholders})
        """, emp_names, as_dict=True)
        emp_data = {e.name: e for e in emp_records}

    org_evaluations = {}
    if org_factors:
        org_factor_names = [f.name for f in org_factors]
        org_placeholders = ", ".join(["%s"] * len(org_factor_names))
        org_period = filters.get('evaluation_period')
        org_form = filters.get('evaluation_form')

        org_records = frappe.db.sql(f"""
            SELECT evaluation_factor, evaluation_subject, final_score
            FROM `tabEvaluation`
            WHERE evaluation_form = %s
            AND evaluation_period = %s
            AND evaluation_factor_doctype = 'Organization'
            AND evaluation_factor IN ({org_placeholders})
            AND docstatus = 1
        """, [org_form, org_period] + org_factor_names, as_dict=True)

        for rec in org_records:
            org_evaluations.setdefault(rec.evaluation_factor, {})[rec.evaluation_subject] = rec.final_score

    result = []
    for row in rows:
        emp = emp_data.get(row.evaluation_subject, {})
        new_row = {
            "evaluation_subject": row.evaluation_subject,
            "emp_name": emp.get('emp_name'),
            "job": emp.get('job'),
        }

        final_score = 0

        for f in emp_factors:
            score = row.get(f'{f.name}_emp') or 0
            new_row[f.name] = score
            final_score += score

        for f in org_factors:
            field_name = factor_structure.get(f.name)
            if field_name:
                emp_org_value = emp.get(field_name)
                if emp_org_value:
                    score = org_evaluations.get(f.name, {}).get(emp_org_value, 0)
                else:
                    score = 0
            else:
                score = 0
            new_row[f.name] = score
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