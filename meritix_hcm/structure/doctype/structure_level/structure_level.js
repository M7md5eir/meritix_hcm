// Copyright (c) 2026, Mohamed Kheir and contributors
// For license information, please see license.txt

frappe.ui.form.on("Structure Level", {
	refresh(frm) {
		// Load insert_after options for all existing rows on form load
		(frm.doc.applies_to || []).forEach(function (row) {
			if (row.target_doctype) {
				_load_insert_after_options(frm, row);
			}
		});

		// Reload options when the user focuses the insert_after cell in the
		// grid (inline editing creates a fresh Autocomplete control that
		// doesn't carry the previously loaded options).
		frm.fields_dict.applies_to.grid.wrapper
			.off("focus.insert_after")
			.on("focus.insert_after", ".frappe-control[data-fieldname='insert_after'] input", function () {
				let $input = $(this);
				let $row = $input.closest(".rows .frappe-control").closest("[data-name]");
				let row_name = $row.data("name");
				if (!row_name) return;
				let row = locals["Structure DF Creation"][row_name];
				if (row && row.target_doctype) {
					// Only show dropdown when field is empty (Link field behavior)
					let show = !$input.val();
					_load_insert_after_options(frm, row, show);
				}
			});
	}
});

frappe.ui.form.on("Structure DF Creation", {
	target_doctype(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.target_doctype) {
			_load_insert_after_options(frm, row);
		} else {
			_set_insert_after_options(frm, row, []);
			frappe.model.set_value(cdt, cdn, "insert_after", "");
		}
	},

	form_render(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.target_doctype) {
			_load_insert_after_options(frm, row);
		}
	}
});

function _load_insert_after_options(frm, row, evaluate) {
	frappe.model.with_doctype(row.target_doctype, function () {
		let meta = frappe.get_meta(row.target_doctype);
		let options = meta.fields.map(f => f.fieldname);
		_set_insert_after_options(frm, row, options, evaluate);
	});
}

function _set_insert_after_options(frm, row, options, evaluate) {
	let grid_row = frm.fields_dict.applies_to.grid.grid_rows_by_docname[row.name];
	if (grid_row) {
		let field = grid_row.get_field("insert_after");
		if (field) {
			field.set_data(options);
			if (field.awesomplete) {
				if (evaluate) {
					field.awesomplete.evaluate();
				} else if (field.$input && field.$input.val()) {
					// awesomplete auto-evaluates when list is set on a
					// focused input; close the dropdown when the field
					// already has a value (Link field behavior).
					field.awesomplete.close();
				}
			}
		}
	}
}
