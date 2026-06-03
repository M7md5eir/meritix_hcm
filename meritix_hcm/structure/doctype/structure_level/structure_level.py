import frappe
from frappe.model.document import Document

from meritix_hcm.meritix_hcm.lifecycle import LifecycleMixin
from meritix_hcm.structure import cascade_custom_fields as cascade


class StructureLevel(LifecycleMixin, Document):

	def on_update(self):
		self._handle_label_rename()
		self._sync_custom_fields()

	def on_trash(self):
		self._remove_custom_fields()

	def _handle_label_rename(self):
		"""Rename Custom Fields when the structure label changes."""
		old_doc = self.get_doc_before_save()
		if not old_doc:
			return
		old_label = old_doc.level
		if not old_label or old_label == self.level:
			return
		for row in self.applies_to or []:
			if row.target_doctype:
				cascade.rename(old_label, self.level, row.target_doctype)

	def _sync_custom_fields(self):
		"""Create/update Custom Fields for every applies_to row and remove orphans."""
		if not self.level:
			return

		# Suppress toast notifications from Custom Field create/update/delete
		prev = frappe.flags.mute_messages
		frappe.flags.mute_messages = True
		try:
			current_targets = set()
			for row in self.applies_to or []:
				if not row.target_doctype:
					continue
				cascade.ensure(self, row)
				current_targets.add(row.target_doctype)

			previous_targets = {
				r.target_doctype
				for r in frappe.get_all(
					"Custom Field",
					filters={
						"is_system_generated": 1,
						"options": "Organization",
						"fieldname": cascade.fieldname_for(self.level),
					},
					fields=["dt as target_doctype"],
				)
			}
			for removed_dt in previous_targets - current_targets:
				cascade.remove(self.level, removed_dt)
		finally:
			frappe.flags.mute_messages = prev

	def _remove_custom_fields(self):
		"""Remove all Custom Fields owned by this Structure Level."""
		if not self.level:
			return
		for row in self.applies_to or []:
			if row.target_doctype:
				cascade.remove(self.level, row.target_doctype)