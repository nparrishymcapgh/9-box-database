# Succession Planning

This Streamlit app supports manager-only 9 box evaluations backed by Google Sheets.

## What the app does

- Manager login only (email + password from the Managers tab)
- Shows employees assigned to that manager
- Loads role-based questions from the Questions tab
- Scores each employee using:
  - Start at 8 points
  - Add question points for each Yes answer
- Shows the matching level name, performance, and potential for the calculated score
- Stores submissions in the Responses tab

## Required Google Sheet tabs

- Employees
- Managers
- Questions
- Responses (auto-created if missing)
- Levels

## Required columns

### Employees

- ID
- name
- email
- job_name
- manager_name
- manager_email
- location
- department
- role

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
- role should match Employees.role, falling back to Employees.job_name when needed (case-insensitive)
- comma-separated role values are supported
- blank role applies to all roles

### Levels

The Levels tab should include these columns:

- score
- performance
- potential
- name
- steps
- focus
- description

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

## UI behavior

- The 9 Box Evaluation tab shows the next pending employee automatically and displays a completion message once all assigned employees are reviewed.
- Individual question point values are not shown on the main evaluation screen.
- The main evaluation screen shows only the level name, performance, and potential while answers are selected.
- Total points are shown at the bottom of the evaluation screen.
- Submitted 9 Box Evaluations shows each employee's name, role, location, department, and full level details, including focus, steps, and description.
- Saved evaluations can be deleted from the Submitted 9 Box Evaluations tab to start over.

## Migration note for existing data

- Older rows in the `Responses` tab may include legacy approval-related columns (`employee_*`, `executive_*`, token fields, and prior status values).
- The current manager-only app ignores those legacy workflow fields and only uses manager submission data.
- You can keep historical rows as-is; no data migration is required for the app to run.
