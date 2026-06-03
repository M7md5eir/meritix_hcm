import frappe
from frappe.utils import getdate

LIFECYCLE_DOCTYPES = (
    "StructureLevel",
    "Organization",
    "Position",
    "Job",
    "Classification",
    "Location",
)

def _compute_active(enabled_date, disabled_date, today):
    if not enabled_date:
        return 0
    enabled = getdate(enabled_date)
    if disabled_date:
        return 1 if enabled <= today <= getdate(disabled_date) else 0
    return 1 if enabled <= today else 0

class LifecycleMixin:
    def before_save(self):
        self._validate_lifecycle_dates()
        self._sync_active_flag()

    def _validate_lifecycle_dates(self):
        if not self.enabled_date:
            self.enabled_date = getdate()

        if self.disabled_date and getdate(self.disabled_date) <= getdate(self.enabled_date):
            frappe.throw("disabled date must be after enabled date or left blank")

    def _sync_active_flag(self):
        new_status = _compute_active(self.enabled_date, self.disabled_date, getdate())
        if self.active != new_status:
            self.active = new_status

def update_status_daily():
    today = getdate()
    for doctype in LIFECYCLE_DOCTYPES:
        _sync_doctype(doctype, today)
    frappe.db.commit()

def _sync_doctype(doctype, today):
    rows = frappe.db.get_list(
        doctype,
        fields=["name", "enabled_date", "disabled_date", "active"],
    )
    for row in rows:
        new_status = _compute_active(row.get("enabled_date"), row.get("disabled_date"), today)
        if row.get("active", 0) != new_status:
            frappe.db.set_value(
                doctype,
                row["name"],
                "active",
                new_status,
                update_modified=False,
            )