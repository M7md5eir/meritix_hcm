def get_data(filters, factors):
    if not factors:
        return []
    if not filters.get('evaluation_form'):
        return []
    if not filters.get('evaluation_period'):
        return []

    conditions = "WHERE e.evaluation_factor_doctype = 'Employee' AND e.docstatus IN (0, 1)"
    values = {}

    for key in ('evaluation_form', 'evaluation_period'):
        if filters.get(key):
            conditions += f" AND e.{key} = %({key})s"
            values[key] = filters[key]

    permitted_subjects = get_permitted_subjects(filters)
    if permitted_subjects:
        subject_placeholders = []
        for i, subj in enumerate(permitted_subjects):
            key = f"subj_{i}"
            values[key] = subj
            subject_placeholders.append(f"%(subj_{i})s")
        conditions += f" AND e.evaluation_subject IN ({', '.join(subject_placeholders)})"
    else:
        return []

    sc_cond, sc_values = apply_structure_filter(filters, fieldname="organization", alias="e", tree_doctype="Organization")
    conditions += sc_cond
    values.update(sc_values)

    factor_weights = {f.name: f.factor_weight or 0 for f in factors}

    factor_selects_parts = []
    for f in factors:
        factor_selects_parts.append(f"""
        , SUM(CASE WHEN e.evaluation_factor = '{f.name}' AND e.docstatus IN (0, 1) THEN e.score ELSE 0 END) AS `{f.name}_emp`
        , SUM(CASE WHEN e.evaluation_factor = '{f.name}' AND e.docstatus IN (0, 1) THEN 1 ELSE 0 END) AS `{f.name}_emp_count`
        , SUM(CASE WHEN e.evaluation_factor = '{f.name}' AND e.docstatus = 1 THEN 1 ELSE 0 END) AS `{f.name}_emp_submitted_count`
        """)

        if f.doctype_list == 'Organization' and f.structure_level:
            field_name = scrub(f.structure_level)
            factor_selects_parts.append(f"""
        , COALESCE((
            SELECT o.score FROM `tabEvaluation` o
            WHERE o.evaluation_form = e.evaluation_form
            AND o.evaluation_period = e.evaluation_period
            AND o.evaluation_factor_doctype = 'Organization'
            AND o.evaluation_factor = '{f.name}'
            AND o.evaluation_subject = e.`{field_name}`
            AND o.docstatus IN (0, 1)
            LIMIT 1
        ), 0) AS `{f.name}_org`
        , COALESCE((
            SELECT COUNT(*) FROM `tabEvaluation` o
            WHERE o.evaluation_form = e.evaluation_form
            AND o.evaluation_period = e.evaluation_period
            AND o.evaluation_factor_doctype = 'Organization'
            AND o.evaluation_factor = '{f.name}'
            AND o.evaluation_subject = e.`{field_name}`
            AND o.docstatus IN (0, 1)
        ), 0) AS `{f.name}_org_count`
        , COALESCE((
            SELECT COUNT(*) FROM `tabEvaluation` o
            WHERE o.evaluation_form = e.evaluation_form
            AND o.evaluation_period = e.evaluation_period
            AND o.evaluation_factor_doctype = 'Organization'
            AND o.evaluation_factor = '{f.name}'
            AND o.evaluation_subject = e.`{field_name}`
            AND o.docstatus = 1
        ), 0) AS `{f.name}_org_submitted_count`
            """)
        else:
            factor_selects_parts.append(f"""
        , 0 AS `{f.name}_org`
        , 0 AS `{f.name}_org_count`
        , 0 AS `{f.name}_org_submitted_count`
            """)

    factor_selects = "".join(factor_selects_parts)

    rows = frappe.db.sql(f"""
        SELECT e.evaluation_subject
        , MAX(e.name) AS evaluation_name
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
            "evaluation_name": row.get('evaluation_name'),
            "evaluation_name_submitted": True,
            "emp_name": row.get('emp_name'),
            "job": row.get('job'),
        }
        for f in factors:
            emp_count = row.get(f'{f.name}_emp_count') or 0
            org_count = row.get(f'{f.name}_org_count') or 0
            emp_submitted_count = row.get(f'{f.name}_emp_submitted_count') or 0
            org_submitted_count = row.get(f'{f.name}_org_submitted_count') or 0

            score = (row.get(f'{f.name}_emp') or 0) + (row.get(f'{f.name}_org') or 0)
            weight = factor_weights.get(f.name, 0)
            factor_final = (score * weight) / 100
            new_row[f.name] = factor_final

            exists = (emp_count + org_count) > 0
            submitted = (emp_submitted_count + org_submitted_count) > 0

            # نلوّن فقط لو فيه تقييم موجود بس لسه مش submitted (Draft).
            # لو مفيش تقييم أصلاً (أو ملغي) → اعتبره submitted عشان مايتلوّنش.
            new_row[f'{f.name}_submitted'] = (not exists) or submitted

            final_score += factor_final
        new_row['final_score'] = final_score
        result.append(new_row)

    return result