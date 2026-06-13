frappe.ui.form.on('Evaluation', {

    refresh(frm) {
        set_evaluation_form_query(frm);
        set_evaluation_subject_query(frm);
        set_evaluation_factor_query(frm);
    },

    // منقول: التحقق من إجمالي الوزن قبل الحفظ
    before_save(frm) {
        var total = 0;
        frm.doc.evaluation_record.forEach(function(row) {
            total += flt(row.weight);
        });
        frm.dashboard.clear_headline();
        if (total !== 100 && total !== 0) {
            frm.dashboard.set_headline_alert(
                __('total weight must equal 100%, the current total is {0}%', [total]),
                'red'
            );
            frappe.validated = false;
        }
    },

    evaluation_form(frm) {
        frm.set_value('evaluation_factor', null);
        frm.set_value('evaluation_subject', null);
        clear_subject_fields(frm);
        set_evaluation_factor_query(frm);
    },

    evaluation_factor(frm) {
        frm.set_value('evaluation_subject', null);
        clear_subject_fields(frm);
        set_evaluation_subject_query(frm);
    },

    evaluation_factor_doctype(frm) {
        frm.set_value('evaluation_subject', null);
        clear_subject_fields(frm);
    },

    evaluation_subject(frm) {
        set_fields_from_subject(frm);
    }

});

// الحقول اللي بتتسحب من الـ evaluation_subject
const SUBJECT_FIELDS = ['organization', 'job', 'emp_name', 'position', 'image'];

function clear_subject_fields(frm) {
    SUBJECT_FIELDS.forEach(function(f) {
        frm.set_value(f, null);
    });
}

function set_fields_from_subject(frm) {
    clear_subject_fields(frm);

    if (!frm.doc.evaluation_subject || !frm.doc.evaluation_factor_doctype) return;

    frappe.call({
        method: 'meritix_hcm.evaluation.doctype.evaluation.evaluation.get_subject_fields',
        args: {
            evaluation_factor_doctype: frm.doc.evaluation_factor_doctype,
            evaluation_subject: frm.doc.evaluation_subject
        },
        callback: function(r) {
            if (!r.message) return;
            SUBJECT_FIELDS.forEach(function(f) {
                frm.set_value(f, r.message[f] || null);
            });
        }
    });
}

// منقول: حساب النسبة المئوية عند تغيير achieved أو planned أو reverse_calc
frappe.ui.form.on('Evaluation Record', {

    // منقول: التحقق من تكرار الـ KPI في الجدول
    kpi(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (!row.kpi) return;

        var duplicates = frm.doc.evaluation_record.filter(function(d) {
            return d.kpi === row.kpi && d.name !== row.name;
        });

        frm.dashboard.clear_headline();

        if (duplicates.length > 0) {
            let kpi_name = frappe.utils.get_link_title('Evaluation KPI', row.kpi) || row.kpi;
            frm.dashboard.set_headline_alert(
                __('the KPI "{0}" already exists', [kpi_name]),
                'red'
            );
            frappe.model.set_value(cdt, cdn, 'kpi', '');
        }
    },

    achieved(frm, cdt, cdn) {
        calculate_percent(frm, cdt, cdn);
    },

    planned(frm, cdt, cdn) {
        calculate_percent(frm, cdt, cdn);
    },

    reverse_calc(frm, cdt, cdn) {
        calculate_percent(frm, cdt, cdn);
    }

});

// منقول: دالة حساب النسبة المئوية
function calculate_percent(frm, cdt, cdn) {
    let row = locals[cdt][cdn];

    if (!row.planned || row.planned === 0 || !row.achieved || row.achieved === 0) {
        frappe.model.set_value(cdt, cdn, 'percent', 0);
        return;
    }

    let percent = row.reverse_calc
        ? (row.planned / row.achieved) * 100
        : (row.achieved / row.planned) * 100;

    frappe.model.set_value(cdt, cdn, 'percent', percent);
}

function set_evaluation_form_query(frm) {
    frm.set_query('evaluation_form', function() {
        return {
            filters: {
                docstatus: 1
            }
        };
    });
}

function set_evaluation_factor_query(frm) {
    frm.set_query('evaluation_factor', function() {
        if (!frm.doc.evaluation_form) {
            return {
                filters: {
                    name: null
                }
            };
        }
        return {
            query: 'meritix_hcm.evaluation.doctype.evaluation.evaluation.get_evaluation_factors',
            filters: {
                evaluation_form: frm.doc.evaluation_form
            }
        };
    });
}

function set_evaluation_subject_query(frm) {
    if (!frm.doc.evaluation_factor) return;

    frappe.db.get_value('Evaluation Factor', frm.doc.evaluation_factor, 'structure_level', (r) => {
        frm.set_query('evaluation_subject', function() {
            if (!r || !r.structure_level) {
                return {};
            }
            return {
                filters: {
                    structure: r.structure_level
                }
            };
        });
    });
}