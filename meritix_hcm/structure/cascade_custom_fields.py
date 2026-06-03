# Copyright (c) 2026, Mohamed Kheir and contributors
# For license information, please see license.txt

"""Manage per-Structure Level Custom Fields on any target DocType.

Each Structure Level record (Company, BU, Sub BU, Sector, ...) may opt to
materialise as a read-only ``Data`` Custom Field on one or more target
DocTypes -- declared via the ``Structure Level.applies_to`` child table.
Each row in ``applies_to`` carries the target DocType, an explicit
``insert_after`` anchor, and per-row visibility flags (``hidden``,
``in_list_view``, ``in_standard_filter``, ``print_hide``).
The cascade walks up the Organization tree and populates each
per-Structure-Level field with the ancestor Organization record name.
Data fields are used (rather than Link) because Frappe's query builder
creates a single JOIN per linked DocType, so multiple Link→Organization
columns in the list view would all resolve to the same title.

Public surface:
    ensure(structure_doc, target_row)  -- create/update one CF.
    rename(old_label, new_label, target_doctype)  -- relabel.
    remove(label, target_doctype)  -- drop.
    fill(doc, target_doctype)  -- populate per-Structure-Level fields on one record.
    refill_all_for(target_doctype)  -- recompute for every record.
    refill_for_subtree(organization_name)  -- recompute for the org subtree
        across every registered target.
    sync_all()  -- idempotent rebuild for migrations / patches.
    sync_app()  -- after_install / after_migrate hook.
    fieldname_for(label)  -- canonical fieldname for a Structure Level label.
    target_doctypes()  -- list of DocTypes referenced by any Structure Level's
        applies_to.

Whitelisted endpoints (used by the Structure Level form):
    search_meritix_hcm_doctypes(...)  -- filter the target_doctype picker
        to DocTypes shipped by the meritix_hcm app.
    get_target_doctype_fields(target_doctype)  -- return the list of
        fieldnames available as ``insert_after`` anchors on a target.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

scrub = frappe.scrub


# Per-target-DocType defaults applied when a row in Structure Level.applies_to
# leaves a flag blank (e.g. legacy rows from before the flags existed) or
# when the target_doctype is referenced anywhere else without an explicit
# row (fallbacks for refill / orphan-cleanup paths).
DOCTYPE_CONFIG: dict[str, dict] = {
	"Position": {
		"insert_after": "tab1_sec1_col3",
		"hidden": 1,
		"in_standard_filter": 0,
		"in_list_view": 0,
		"print_hide": 1,
	},
	"Employee": {
		"insert_after": "column_break_scuj",
		"hidden": 1,
		"in_standard_filter": 0,
		"in_list_view": 0,
		"print_hide": 1,
	},
}

DEFAULT_CONFIG = {
	"insert_after": "organization",
	"hidden": 1,
	"in_standard_filter": 0,
	"in_list_view": 0,
	"print_hide": 1,
}


def fieldname_for(label: str) -> str:
	return scrub(label or "")


def custom_field_name(target_doctype: str, label: str) -> str:
	"""Desired record name in tabCustom Field for a (DocType, Structure Level) pair.

	Format ``'{TargetDocType} {Label}'`` (e.g. ``'Position Unit'``,
	``'Employee Sub BU'``). The fieldname stays snake_case (``unit``,
	``sub_bu``) -- only the record name reads naturally.
	"""
	return f"{target_doctype} {label}"


def _autonamed_cf_name(target_doctype: str, fieldname: str) -> str:
	"""The transient name Frappe assigns via Custom Field's built-in autoname.

	Custom Field's :meth:`autoname` sets ``name = '{dt}-{fieldname}'`` -- so
	right after :func:`create_custom_field` the record exists under this name
	and we immediately :func:`frappe.rename_doc` it to :func:`custom_field_name`.
	Also used to detect and migrate legacy records left over from earlier
	naming conventions.
	"""
	return f"{target_doctype}-{fieldname}"


def _config_for(target_doctype: str) -> dict:
	"""Default per-target config (used when the row leaves a flag blank)."""
	cfg = dict(DEFAULT_CONFIG)
	cfg.update(DOCTYPE_CONFIG.get(target_doctype, {}))
	return cfg


def _row_get(row, key, default=None):
	"""Read a value off a Document, _dict, or plain dict transparently."""
	if row is None:
		return default
	if hasattr(row, "get") and not isinstance(row, str):
		val = row.get(key)
	else:
		val = getattr(row, key, None)
	return default if val is None else val


def _flags_from_row(row, target_doctype: str) -> dict:
	"""Resolve the CF flags for a (Structure Level, target) row.

	Reads explicit values off the row when set; otherwise falls back to
	the per-target defaults in :data:`DOCTYPE_CONFIG`. ``insert_after``
	is empty-string-treated-as-blank so an unanswered Select on the row
	doesn't override the default anchor.
	"""
	defaults = _config_for(target_doctype)
	insert_after = _row_get(row, "insert_after", "")
	if not insert_after:
		insert_after = defaults["insert_after"]
	return {
		"insert_after": insert_after,
		"hidden": int(_row_get(row, "hidden", defaults["hidden"]) or 0),
		"in_list_view": int(_row_get(row, "in_list_view", defaults["in_list_view"]) or 0),
		"in_standard_filter": int(_row_get(row, "in_standard_filter", defaults["in_standard_filter"]) or 0),
		"print_hide": int(_row_get(row, "print_hide", defaults["print_hide"]) or 0),
	}


def _field_definition(
    target_doctype: str,
    structure_label: str,
    structure_name: str,
    flags: dict,
) -> dict:
    return {
        "fieldname": fieldname_for(structure_label),
        "label": structure_label,
        "fieldtype": "Link",
		"options": "Organization",
        "read_only": 1,
        "hidden": flags["hidden"],
        "in_list_view": flags["in_list_view"],
        "in_standard_filter": flags["in_standard_filter"],
        "print_hide": flags["print_hide"],
        "insert_after": flags["insert_after"],
        "is_system_generated": 1,
    }


def _apply_df(cf, df) -> None:
	"""Update mutable Custom Field attributes from ``df`` in place.

	Frappe blocks fieldtype changes on save, so we delete and recreate
	when the fieldtype differs.
	"""
	if cf.get("fieldtype") != df.get("fieldtype"):
		target_doctype = cf.dt
		desired_name = cf.name
		cf.delete(ignore_permissions=True)
		create_custom_field(target_doctype, df, is_system_generated=True)
		autoname = _autonamed_cf_name(target_doctype, df["fieldname"])
		if autoname != desired_name and frappe.db.exists("Custom Field", autoname):
			frappe.rename_doc("Custom Field", autoname, desired_name, force=True, show_alert=False)
		frappe.clear_cache(doctype=target_doctype)
		return

	dirty = False
	for key in (
		"label",
		"insert_after",
		"options",
		"hidden",
		"read_only",
		"in_list_view",
		"in_standard_filter",
		"print_hide",
	):
		if cf.get(key) != df.get(key):
			cf.set(key, df.get(key))
			dirty = True
	if dirty:
		cf.save(ignore_permissions=True)


def _normalise_row(row_or_dt) -> tuple[str, dict]:
	"""Accept either a row Document/dict or a bare DocType string.

	Returns ``(target_doctype, row_dict)`` where ``row_dict`` is suitable
	for :func:`_flags_from_row`. Bare strings are treated as legacy callers
	-- they get the per-target defaults.
	"""
	if isinstance(row_or_dt, str):
		return row_or_dt, {}
	target_doctype = _row_get(row_or_dt, "target_doctype")
	return target_doctype, row_or_dt


def ensure(structure_doc, target_row) -> None:
	"""Create the Custom Field for ``(structure_doc, target_row)`` or update it.

	``target_row`` may be a Frappe Document/dict from the
	``Structure Level.applies_to`` child table (preferred -- carries the per-row
	flags and ``insert_after``) or a bare DocType string (legacy callers
	get the per-target defaults).

	Handles three cases:

	1. Already named correctly (``'{DocType} {Label}'``) -> update in place.
	2. Legacy autonamed record exists (``'{DocType}-{fieldname}'``) -> rename
	   and update.
	3. No record yet -> create then rename.
	"""
	target_doctype, row = _normalise_row(target_row)
	if not target_doctype:
		return

	# label = the Structure Level name (which IS the label now)
	label = structure_doc.name if hasattr(structure_doc, "name") else structure_doc.get("name")
	if not label:
		return

	name = label  # name and label are the same field now

	flags = _flags_from_row(row, target_doctype)
	df = _field_definition(target_doctype, label, name, flags)
	desired = custom_field_name(target_doctype, label)
	legacy = _autonamed_cf_name(target_doctype, df["fieldname"])

	if frappe.db.exists("Custom Field", desired):
		_apply_df(frappe.get_doc("Custom Field", desired), df)
	elif frappe.db.exists("Custom Field", legacy):
		frappe.rename_doc("Custom Field", legacy, desired, force=True, show_alert=False)
		_apply_df(frappe.get_doc("Custom Field", desired), df)
	else:
		create_custom_field(target_doctype, df, is_system_generated=True)
		if legacy != desired and frappe.db.exists("Custom Field", legacy):
			frappe.rename_doc("Custom Field", legacy, desired, force=True, show_alert=False)

	frappe.clear_cache(doctype=target_doctype)


def rename(old_label: str, new_label: str, target_doctype: str) -> None:
	"""Rename the Custom Field on ``target_doctype`` when a Structure Level is relabelled."""
	if not old_label or not new_label or old_label == new_label or not target_doctype:
		return

	new_fieldname = fieldname_for(new_label)
	old_cf = custom_field_name(target_doctype, old_label)
	new_cf = custom_field_name(target_doctype, new_label)

	# Tolerate older records that may still be under the legacy autoname.
	if not frappe.db.exists("Custom Field", old_cf):
		legacy = _autonamed_cf_name(target_doctype, fieldname_for(old_label))
		if frappe.db.exists("Custom Field", legacy):
			old_cf = legacy
		else:
			return

	# Update fieldname/label first so Frappe renames the underlying column.
	cf = frappe.get_doc("Custom Field", old_cf)
	cf.fieldname = new_fieldname
	cf.label = new_label
	cf.save(ignore_permissions=True)

	if old_cf != new_cf:
		frappe.rename_doc("Custom Field", old_cf, new_cf, force=True, show_alert=False)

	frappe.clear_cache(doctype=target_doctype)


def remove(label: str, target_doctype: str) -> None:
	"""Drop the Custom Field on ``target_doctype`` for a Structure Level."""
	if not label or not target_doctype:
		return

	candidates = (
		custom_field_name(target_doctype, label),
		_autonamed_cf_name(target_doctype, fieldname_for(label)),
	)
	deleted = False
	for cf_name in candidates:
		if frappe.db.exists("Custom Field", cf_name):
			frappe.delete_doc("Custom Field", cf_name, force=True, ignore_permissions=True)
			deleted = True
	if deleted:
		frappe.clear_cache(doctype=target_doctype)


def target_doctypes() -> list[str]:
	"""Return every DocType referenced by at least one Structure Level's applies_to."""
	rows = frappe.get_all(
		"Structure DF Creation",
		filters={"parenttype": "Structure Level"},
		fields=["target_doctype"],
		distinct=True,
	)
	return [r.target_doctype for r in rows if r.target_doctype]


def _structure_target_pairs() -> list[tuple[dict, dict]]:
	"""Every (Structure Level, applies_to row) the user has opted in.

	Returns ``(structure_dict, row_dict)`` tuples. The row_dict carries
	``target_doctype`` and per-row flags so callers can pass the row
	straight into :func:`ensure`.
	"""
	rows = frappe.db.sql(
		"""
		SELECT s.name AS structure_name,
			t.target_doctype, t.insert_after, t.hidden, t.in_list_view,
			t.in_standard_filter, t.print_hide
		FROM `tabStructure Level` s
		INNER JOIN `tabStructure DF Creation` t
			ON t.parent = s.name AND t.parenttype = 'Structure Level'
		WHERE t.target_doctype IS NOT NULL AND t.target_doctype != ''
		ORDER BY s.name
		""",
		as_dict=True,
	)
	pairs: list[tuple[dict, dict]] = []
	for r in rows:
		pairs.append(
			(
				frappe._dict(name=r.structure_name),
				frappe._dict(
					target_doctype=r.target_doctype,
					insert_after=r.insert_after,
					hidden=r.hidden,
					in_list_view=r.in_list_view,
					in_standard_filter=r.in_standard_filter,
					print_hide=r.print_hide,
				),
			)
		)
	return pairs


def sync_all() -> None:
	"""Idempotent: rebuild Custom Fields for every (Structure Level, target) pair.

	Forward pass materialises every pair; reverse pass drops orphan
	system-generated CFs on each registered target so removing a row
	from ``Structure Level.applies_to`` causes the matching CF to disappear
	on the next sync.
	"""
	pairs = _structure_target_pairs()

	for structure_doc, row in pairs:
		ensure(structure_doc, row)

	wanted_by_dt: dict[str, set[str]] = {}
	for structure_doc, row in pairs:
		wanted_by_dt.setdefault(row.target_doctype, set()).add(
			custom_field_name(row.target_doctype, structure_doc.name)
		)

	for target_doctype in set(target_doctypes()):
		existing = frappe.get_all(
			"Custom Field",
			filters={
				"dt": target_doctype,
				"is_system_generated": 1,
				"options": "Organization",
			},
			pluck="name",
		)
		wanted = wanted_by_dt.get(target_doctype, set())
		for cf_name in existing:
			if cf_name not in wanted:
				frappe.delete_doc("Custom Field", cf_name, force=True, ignore_permissions=True)
		if existing:
			frappe.clear_cache(doctype=target_doctype)


def _bulk_refill(target_doctype: str, organization_filter: list[str] | None = None) -> None:
	"""Recompute cascade fields for ``target_doctype`` using bulk SQL UPDATEs.

	For each Structure Level registered on the target, issues a single
	UPDATE ... JOIN that walks the Organization tree via Nested Set
	(lft/rgt) and sets the correct ancestor Organization in one pass.

	When ``organization_filter`` is given, only records whose
	``organization`` is in that list are updated (used by
	:func:`refill_for_subtree`). Otherwise all records are updated.
	"""
	pairs = frappe.db.sql(
		"""
		SELECT s.name AS structure_name, s.name AS label
		FROM `tabStructure Level` s
		INNER JOIN `tabStructure DF Creation` t
			ON t.parent = s.name AND t.parenttype = 'Structure Level'
		WHERE t.target_doctype = %s
			AND s.name IS NOT NULL AND s.name != ''
		""",
		(target_doctype,),
		as_dict=True,
	)
	if not pairs:
		return

	table = f"`tab{target_doctype}`"

	where_extra = ""
	filter_params: tuple = ()
	if organization_filter:
		placeholders = ", ".join(["%s"] * len(organization_filter))
		where_extra = f" AND rec.organization IN ({placeholders})"
		filter_params = tuple(organization_filter)

	# Verify which columns actually exist on the DB table before running
	# UPDATEs so a missing column doesn't abort the entire loop.
	existing_columns = {
		row.column_name
		for row in frappe.db.sql(
			"SELECT column_name FROM information_schema.columns WHERE table_name=%s",
			(f"tab{target_doctype}",),
			as_dict=True,
		)
	}

	for pair in pairs:
		fieldname = fieldname_for(pair.label)

		if fieldname not in existing_columns:
			continue

		# First NULL-out the field for all affected records so stale
		# values from a previous tree position are cleared.
		null_sql = f"UPDATE {table} rec SET rec.`{fieldname}` = NULL WHERE 1=1{where_extra}"
		frappe.db.sql(null_sql, filter_params)

		# Then set the correct ancestor via a Nested Set JOIN.
		update_sql = f"""
			UPDATE {table} rec
			INNER JOIN `tabOrganization` leaf ON leaf.name = rec.organization
			INNER JOIN `tabOrganization` ancestor
				ON ancestor.lft <= leaf.lft AND ancestor.rgt >= leaf.rgt
				AND ancestor.structure = %s
			SET rec.`{fieldname}` = ancestor.name
			WHERE 1=1{where_extra}
		"""
		frappe.db.sql(update_sql, (pair.structure_name, *filter_params))

	frappe.db.commit()


def _target_structure_fields(target_doctype: str) -> set[str]:
	"""Return the set of cascade fieldnames registered for ``target_doctype``."""
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT s.name
		FROM `tabStructure Level` s
		INNER JOIN `tabStructure DF Creation` t
			ON t.parent = s.name AND t.parenttype = 'Structure Level'
		WHERE t.target_doctype = %s AND s.name IS NOT NULL AND s.name != ''
		""",
		(target_doctype,),
		as_dict=True,
	)
	return {fieldname_for(r.name) for r in rows}


def _get_organization_ancestry(organization: str) -> list[dict]:
	"""Walk up the Organization tree using Nested Set and return ancestor nodes.

	Returns a list of dicts with ``name`` and ``structure`` (the
	Structure Level name) for every ancestor (inclusive) of the given
	Organization, ordered from root to leaf.
	"""
	lft_rgt = frappe.db.get_value("Organization", organization, ["lft", "rgt"])
	if not lft_rgt:
		return []

	lft, rgt = lft_rgt
	if not lft or not rgt:
		return []

	return frappe.db.sql(
		"""
		SELECT o.name, o.structure,
		       s.name AS structure_label
		FROM `tabOrganization` o
		LEFT JOIN `tabStructure Level` s ON s.name = o.structure
		WHERE o.lft <= %s AND o.rgt >= %s
		ORDER BY o.lft
		""",
		(lft, rgt),
		as_dict=True,
	)


def fill(doc, target_doctype: str) -> None:
	target_fields = _target_structure_fields(target_doctype)

	for fieldname in target_fields:
		if hasattr(doc, fieldname):
			doc.set(fieldname, None)

	organization = doc.get("organization") if hasattr(doc, "get") else getattr(doc, "organization", None)
	if not organization:
		return

	for node in _get_organization_ancestry(organization):
		structure_label = node.get("structure_label")
		if not structure_label:
			continue
		fieldname = fieldname_for(structure_label)
		if fieldname in target_fields and hasattr(doc, fieldname):
			doc.set(fieldname, node["name"])


def fill_on_save(doc, method=None):
	"""Hook for doc_events: populate cascade fields when a target DocType is saved."""
	target_doctype = doc.doctype
	meta = frappe.get_meta(target_doctype)
	if not meta.has_field("organization"):
		return
	if not _target_structure_fields(target_doctype):
		return
	fill(doc, target_doctype)


def propagate_position_change(doc, method=None):
	"""Hook for Position.on_update: propagate organization changes to linked Employees.

	When a Position's ``organization`` changes, every Employee whose
	``position`` points to this Position must have its ``organization``
	(and all cascade fields) updated to match. Employee.organization
	is declared as ``fetch_from: position.organization`` but Frappe's
	fetch_from only fires on the client -- this hook handles the backend
	propagation for existing records.
	"""
	if not doc.has_value_changed("organization"):
		return

	new_org = doc.organization

	employees = frappe.get_all(
		"Employee",
		filters={"position": doc.name},
		pluck="name",
	)
	if not employees:
		return

	placeholders = ", ".join(["%s"] * len(employees))
	frappe.db.sql(
		f"UPDATE `tabEmployee` SET organization = %s WHERE name IN ({placeholders})",
		(new_org, *employees),
	)

	if _target_structure_fields("Employee"):
		for emp_name in employees:
			emp = frappe.get_doc("Employee", emp_name)
			fill(emp, "Employee")
			emp.db_update()

	frappe.db.commit()


def refill_all_for(target_doctype: str) -> None:
	"""Recompute the cascade fields for every record of ``target_doctype``.

	Uses bulk SQL UPDATEs per Structure Level instead of loading each
	record one-by-one, drastically reducing query count for large tables.
	"""
	if not target_doctype:
		return
	_bulk_refill(target_doctype)


def _descendants_inclusive(organization_name: str) -> list[str]:
	"""All Organization names in the subtree rooted at ``organization_name``.

	Uses a single Nested Set query instead of recursive parent lookups.
	"""
	lft_rgt = frappe.db.get_value("Organization", organization_name, ["lft", "rgt"])
	if not lft_rgt:
		return [organization_name]

	lft, rgt = lft_rgt
	return frappe.db.sql_list(
		"""
		SELECT name FROM `tabOrganization`
		WHERE lft >= %s AND rgt <= %s
		""",
		(lft, rgt),
	)


def refill_for_subtree(organization_name: str) -> None:
	"""Recompute the cascade fields under ``organization_name`` for every target.

	Uses bulk SQL UPDATEs instead of loading each record individually.
	"""
	if not organization_name:
		return

	descendants = _descendants_inclusive(organization_name)
	if not descendants:
		return

	for target_doctype in target_doctypes():
		try:
			meta = frappe.get_meta(target_doctype)
		except Exception:
			continue
		if not meta.has_field("organization"):
			continue

		_bulk_refill(target_doctype, organization_filter=descendants)


def _backfill_legacy_position_targets() -> None:
	"""One-time backfill: pre-existing sites had Position CFs implicitly --
	now that the user must opt in via ``Structure Level.applies_to``, seed the
	child table for any Structure Level that already has a ``'Position {Label}'``
	CF in the database. Idempotent: re-runs are no-ops.
	"""
	for s in frappe.get_all("Structure Level", fields=["name"]):
		cf_name = custom_field_name("Position", s.name)
		if not frappe.db.exists("Custom Field", cf_name):
			continue
		existing = frappe.get_all(
			"Structure DF Creation",
			filters={"parent": s.name, "parenttype": "Structure Level", "target_doctype": "Position"},
			pluck="name",
			limit=1,
		)
		if existing:
			continue
		row = frappe.get_doc(
			{
				"doctype": "Structure DF Creation",
				"parent": s.name,
				"parenttype": "Structure Level",
				"parentfield": "applies_to",
				"target_doctype": "Position",
				"insert_after": DOCTYPE_CONFIG["Position"]["insert_after"],
				"hidden": DOCTYPE_CONFIG["Position"]["hidden"],
				"in_list_view": DOCTYPE_CONFIG["Position"]["in_list_view"],
				"in_standard_filter": DOCTYPE_CONFIG["Position"]["in_standard_filter"],
				"print_hide": DOCTYPE_CONFIG["Position"]["print_hide"],
			}
		)
		row.insert(ignore_permissions=True)


def sync_app() -> None:
	"""Idempotent reconciliation: keep Custom Fields and per-record cascade
	values in sync with the live ``Structure Level.applies_to`` registration.

	Wired to ``after_install`` and ``after_migrate`` in hooks.py.
	"""
	_backfill_legacy_position_targets()

	# Rebuild the Organization Nested Set so lft/rgt values are correct
	# before the cascade queries rely on them.
	try:
		frappe.utils.nestedset.rebuild_tree("Organization", "parent_organization")
	except Exception:
		pass

	sync_all()
	for target_doctype in target_doctypes():
		refill_all_for(target_doctype)


# ---------------------------------------------------------------------------
# Custom Field protection
# ---------------------------------------------------------------------------


def protect_system_generated_cf(doc, method=None):
	"""Prevent manual edits/deletion of system-generated cascade CFs.

	Wired via ``doc_events`` in hooks.py. Allows programmatic changes
	(called with ``ignore_permissions=True`` from within this module)
	but blocks interactive Customize Form / direct API edits.

	The protection is intentionally scoped to *modifying / deleting*
	an existing CF -- it must not block the cascade's own
	:func:`create_custom_field` call (which goes through Frappe's
	standard ``insert``/``before_save`` flow without setting
	``ignore_permissions``). New docs are therefore allowed through;
	the only way a CF acquires ``is_system_generated=1`` in the first
	place is via the cascade itself.
	"""
	if not doc.get("is_system_generated"):
		return
	if doc.get("options") != "Organization":
		return
	if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch:
		return
	if doc.flags.ignore_permissions:
		return
	if doc.is_new():
		return

	frappe.throw(
		f"Custom Field <b>{doc.name}</b> is auto-managed by the Structure Level cascade. "
		"Edit the Structure Level DocType instead of modifying this field directly."
	)


# ---------------------------------------------------------------------------
# Whitelisted endpoints used by the Structure Level form.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def search_meritix_hcm_doctypes(
	doctype: str | None = None,
	txt: str = "",
	searchfield: str = "name",
	start: int = 0,
	page_len: int = 20,
	filters: dict | None = None,
) -> list[list]:
	"""Search query for the ``target_doctype`` picker in ``Structure Level.applies_to``.

	Returns only DocTypes shipped by the meritix_hcm app and excludes child
	tables / single DocTypes (those without an ``organization`` field
	wouldn't carry a meaningful cascade). Output shape matches Frappe's
	standard search query: ``[name, description, ...]``.
	"""
	txt = txt or ""
	page_len = int(page_len or 20)
	start = int(start or 0)

	rows = frappe.db.sql(
		"""
		SELECT dt.name, dt.module
		FROM `tabDocType` dt
		INNER JOIN `tabModule Def` md ON md.name = dt.module
		WHERE md.app_name = 'meritix_hcm'
			AND dt.istable = 0
			AND dt.issingle = 0
			AND (dt.name LIKE %(txt)s OR dt.module LIKE %(txt)s)
		ORDER BY dt.name
		LIMIT %(start)s, %(page_len)s
		""",
		{"txt": f"%{txt}%", "start": start, "page_len": page_len},
		as_list=True,
	)
	return rows


@frappe.whitelist()
def get_organization_titles(names) -> dict[str, str]:
	"""Return a mapping of Organization names to their display titles.

	Used by the client-side list/form formatters to resolve ORG-xxx
	record names stored in cascade Data fields into human-readable
	Organization titles.
	"""
	import json

	if isinstance(names, str):
		names = json.loads(names)
	if not names:
		return {}
	return dict(
		frappe.get_all(
			"Organization",
			filters={"name": ("in", names)},
			fields=["name", "organization"],
			as_list=True,
		)
	)


@frappe.whitelist()
def get_target_doctype_fields(target_doctype: str) -> list[dict]:
	"""Return the fieldnames available as ``insert_after`` anchors on a target.

	Used by ``structure.js`` to populate the ``insert_after`` Select
	on each ``applies_to`` row when the user changes ``target_doctype``.
	Includes both the standard DocType fields and any existing Custom
	Fields on that target, so users can anchor a Structure Level CF below
	another Structure Level CF.
	"""
	if not target_doctype:
		return []
	try:
		meta = frappe.get_meta(target_doctype)
	except Exception:
		return []

	out: list[dict] = []
	seen: set[str] = set()
	for f in meta.fields:
		if not f.fieldname or f.fieldname in seen:
			continue
		seen.add(f.fieldname)
		out.append(
			{
				"value": f.fieldname,
				"label": f.label or f.fieldname,
				"fieldtype": f.fieldtype,
			}
		)
	return out