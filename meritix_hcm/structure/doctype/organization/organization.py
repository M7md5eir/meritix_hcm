import frappe
from frappe.utils.nestedset import NestedSet

from meritix_hcm.meritix_hcm.lifecycle import LifecycleMixin


class Organization(LifecycleMixin, NestedSet):
	# Frappe's import_controller only auto-resolves to NestedSet for
	# `custom` doctypes; for app-shipped tree doctypes the Python class
	# must extend NestedSet explicitly so update_nsm() runs and the
	# lft/rgt columns stay consistent. Without this every Organization
	# row had lft = rgt = 0 and the cascade's ancestry queries (which
	# rely on Nested Set joins) returned no rows.
	nsm_parent_field = "parent_organization"

	def on_update(self):
		super().on_update()
		if self.has_value_changed("parent_organization") or self.has_value_changed("structure"):
			frappe.enqueue(
				"meritix_hcm.structure.cascade_custom_fields.refill_for_subtree",
				organization_name=self.name,
				queue="long",
				enqueue_after_commit=True,
			)
