# Copyright (c) 2026, Mohamed Kheir and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from meritix_hcm.structure import cascade_custom_fields


class Evaluation(Document):
    def before_save(self):
        self.set_fields_from_evaluation_subject()
        cascade_custom_fields.fill(self, self.doctype)

        self.evaluation_record = [row for row in self.evaluation_record if row.kpi]

        if not self.evaluation_record:
            self.score = 0
            return

        factor_data = frappe.db.get_value(
            'Evaluation Factor Setup',
            {
                'parent': self.evaluation_form,
                'parentfield': 'evaluation_factor_setup',
                'factor': self.evaluation_factor
            },
            ['formula', 'weight'],
            as_dict=True
        )

        if not factor_data or not factor_data.formula:
            self.score = 0
            return

        total_score = 0

        for row in self.evaluation_record:
            if not row.planned or not row.achieved or not row.weight:
                row.percent = 0
                row.score = 0
                continue

            if row.reverse_calc:
                row.percent = (row.planned / row.achieved) * 100
            else:
                row.percent = (row.achieved / row.planned) * 100

            formula = factor_data.formula.replace('percent', str(row.percent))
            score = frappe.safe_eval(formula)
            row.score = (row.weight * score) / 100

            total_score += row.score or 0

        self.score = total_score

    def on_submit(self):
        cascade_custom_fields.fill(self, self.doctype)
        self.db_update()

    def on_update_after_submit(self):
        cascade_custom_fields.fill(self, self.doctype)
        self.db_update()

    def set_fields_from_evaluation_subject(self):
        data = get_subject_fields(self.evaluation_factor_doctype, self.evaluation_subject)
        for f, v in data.items():
            self.set(f, v)


@frappe.whitelist()
def get_subject_fields(evaluation_factor_doctype, evaluation_subject):
    target_fields = ['organization', 'job', 'emp_name', 'position', 'image']

    field_to_doctype = {
        'organization': 'Organization',
        'job': 'Job',
        'position': 'Position',
    }

    data = {f: None for f in target_fields}

    if not evaluation_subject or not evaluation_factor_doctype:
        return data

    meta = frappe.get_meta(evaluation_factor_doctype)

    fetch_fields = ['name'] + [f for f in target_fields if meta.has_field(f)]

    result = frappe.db.get_value(
        evaluation_factor_doctype, evaluation_subject, fetch_fields, as_dict=True
    )
    if not result:
        return data

    for f in target_fields:
        if evaluation_factor_doctype == field_to_doctype.get(f):
            data[f] = result.get('name')
        else:
            data[f] = result.get(f)

    return data


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_evaluation_factors(doctype, txt, searchfield, start, page_len, filters):
    evaluation_form = filters.get('evaluation_form')
    return frappe.db.sql("""
        SELECT ef.name AS factor_label
        FROM `tabEvaluation Factor` ef
        INNER JOIN `tabEvaluation Factor Setup` efc ON efc.factor = ef.name
        WHERE efc.parent = %(evaluation_form)s
        AND efc.parentfield = 'evaluation_factor_setup'
        AND (ef.name LIKE %(txt)s OR ef.name LIKE %(txt)s)
        LIMIT %(page_len)s OFFSET %(start)s
    """, {
        'evaluation_form': evaluation_form,
        'txt': f'%{txt}%',
        'page_len': page_len,
        'start': start
    })