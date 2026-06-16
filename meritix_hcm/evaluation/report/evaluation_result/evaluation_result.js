frappe.query_reports["Evaluation Result"] = {
    filters: [
        {
            fieldname: "evaluation_form",
            label: __("Evaluation Form"),
            fieldtype: "Link",
            options: "Evaluation Form"
        },
        {
            fieldname: "evaluation_period",
            label: __("Evaluation Period"),
            fieldtype: "Link",
            options: "Period"
        },
        {
            fieldname: "organization",
            label: __("Organization"),
            fieldtype: "Structure Link",
            options: "Organization"
        }
    ],

    formatter: function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);

        const skip = ["evaluation_subject", "emp_name", "job", "final_score", "evaluation_name"];
        if (data && !skip.includes(column.fieldname)) {
            if (!data[column.fieldname + "_submitted"]) {
                value = `<div style="background-color: #fff0f0; color: #941f1f; margin: -4px -8px; padding: 4px 8px;">${value}</div>`;
            }
        }

        return value;
    }
};