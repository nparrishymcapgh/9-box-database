# Succession Planning

This Streamlit app supports manager-only succession planning using a 9-box scoring flow backed by Google Sheets.

## What the app does

- Manager login only (email + password from the Managers tab)
- Shows employees assigned to that manager
- Loads role-based questions from the Questions tab
- Scores each employee using:
  - Start at 6 points
  - Add question points for each Yes answer
- Stores submissions in the Responses tab

## Required Google Sheet tabs

- Employees
- Managers
- Questions
- Responses (auto-created if missing)

## Required columns

### Employees

- ID
- name
- email
- manager_email
- branch (optional)
- dept (optional)
- job_title (recommended)

### Managers

- manager_email (or email)
- password
- manager_name (optional)

### Questions

The Questions tab should have exactly:

- ID
- points
- question
- role

Notes:
- role should match Employees.job_title (case-insensitive)
- comma-separated role values are supported
- blank role applies to all roles

## Streamlit secrets

Use .streamlit/secrets.toml locally, or Streamlit Cloud Secrets in deployment.

Template file: .streamlit/secrets.toml.example

Expected sections:

```toml
[gcp_service_account]
# service account JSON fields

[app]
url = "https://your-streamlit-app-url.streamlit.app"
data_sync_minutes = 5
```

SMTP is optional now because there is no approval email workflow.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Migration note for existing data

- Older rows in the `Responses` tab may include legacy approval-related columns (`employee_*`, `executive_*`, token fields, and prior status values).
- The current manager-only app ignores those legacy workflow fields and only uses manager submission data.
- You can keep historical rows as-is; no data migration is required for the app to run.
