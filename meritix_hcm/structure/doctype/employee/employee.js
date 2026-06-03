// Copyright (c) 2026, Mohamed Kheir and contributors
// For license information, please see license.txt

frappe.ui.form.on("Employee", {
	refresh(frm) {
		_render_cascade_titles(frm);
	},
});

// Resolve cascade Data fields (ORG names) to Organization titles and
// render them as clickable links in the form view.
function _render_cascade_titles(frm) {
	const meta = frappe.get_meta("Employee");
	if (!meta) return;

	const cascade_fields = meta.fields.filter(
		(df) => df.fieldtype === "Data" && df.options === "Organization" && df.is_system_generated
	);
	if (!cascade_fields.length) return;

	const names = [];
	cascade_fields.forEach((df) => {
		const v = frm.doc[df.fieldname];
		if (v) names.push(v);
	});
	if (!names.length) return;

	frappe.xcall(
		"meritix_hcm.structure.cascade_custom_fields.get_organization_titles",
		{ names }
	).then((map) => {
		if (!map) return;
		cascade_fields.forEach((df) => {
			const v = frm.doc[df.fieldname];
			if (!v || !map[v]) return;
			const title = map[v];
			const $ctrl = frm.fields_dict[df.fieldname]?.$wrapper;
			if (!$ctrl) return;
			const $static = $ctrl.find(".control-value, .like-disabled-input");
			if ($static.length) {
				$static.html(
					`<a href="/app/organization/${encodeURIComponent(v)}"
					   data-doctype="Organization" data-name="${frappe.utils.escape_html(v)}"
					>${frappe.utils.escape_html(title)}</a>`
				);
			}
		});
	});
}
