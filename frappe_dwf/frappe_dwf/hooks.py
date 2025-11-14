app_name = "frappe_dwf"
app_title = "Frappe DWF"
app_publisher = "fleetwoodfc"
app_description = "Minimal Frappe app for IHE Departmental Workflow (DWF) mapping"
app_version = "0.0.1"

# Expose API methods for DICOM/HL7 webhook integration
# Whitelisted methods are defined in frappe_dwf.api

doc_events = {
    # optionally, hooks on DocType events could be added here
}

webhooks = []

override_whitelisted_methods = {
}