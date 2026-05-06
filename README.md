# Leader Level Balanced Score Card

This Streamlit app loads data from Google Sheets, lets managers complete role-based 9-box ratings for employees, and sends approval emails to employees, managers, and executives. It also includes a separate employee login so each employee can complete a one-time self-response form from the Employee_Questions sheet.

## 9-Box Scoring Rules

- Each manager review starts at 6 base points.
- Questions come from the Questions tab and are filtered by the employee role (role or job title mapping).
- Each question is answered Yes or No.
- For each Yes answer, the app adds that question's points value.
- The stored questions_score value is the total points.
- The displayed 9-box rating is the total points clamped to 1-9.

## Setup Instructions

### 1. Install Python dependencies

1. Make sure your Python interpreter is the one used by VS Code.
2. Install the required packages (requires Streamlit 1.28.0 or later):

   ```bash
   pip install -r requirements.txt
   ```

3. If you see errors like `Import "gspread" could not be resolved` or `Import "google.oauth2.service_account" could not be resolved`:
   - Ensure the correct Python environment is selected in VS Code.
   - Install the packages again in that environment:

   ```bash
   pip install gspread google-auth
   ```

   - Restart VS Code or reload the window after installation.

### 2. Configure the Google Sheets service account

1. Open the Google Cloud Console: https://console.cloud.google.com/
2. Create a new project or use an existing one.
3. Enable the Google Sheets API for the project.
4. Create a service account for the project:
   - Go to `APIs & Services` → `Credentials` → `Create credentials` → `Service account`.
   - Give it a name like `streamlit-service-account`.
5. Create a JSON key for the service account:
   - In the service account details, go to `Keys` → `Add key` → `Create new key` → `JSON`.
   - Download the JSON file.
6. Open your Google Sheet and share it with the service account email address from the JSON file.
   - The email looks like `xxxxx@xxxxx.iam.gserviceaccount.com`.

### 3. Add service account credentials to Streamlit secrets

Create a local file at `.streamlit/secrets.toml` in the repository root, or use Streamlit Cloud's secrets UI.

A tracked template file is provided at `.streamlit/secrets.toml.example` with placeholders. Copy it to `.streamlit/secrets.toml` and fill in your actual values:

```toml
[gcp_service_account]
type = "service_account"
project_id = "your-google-cloud-project-id"
private_key_id = "your-private-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\nYOUR_PRIVATE_KEY_HERE\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-service-account%40your-project.iam.gserviceaccount.com"

[smtp]
server = "smtp.gmail.com"
port = 587
username = "your-email@gmail.com"
password = "your-app-password"
from_email = "no-reply@yourdomain.com"

[app]
url = "https://your-streamlit-app-url.streamlit.app"
```

> **Gmail users**: Use an App Password instead of your regular password. Generate one at https://myaccount.google.com/apppasswords

> Important: keep the private key exactly as it appears in the JSON, with `\n` escaped when storing in the TOML file.

### 4. Configure SMTP and app URL secrets

Also add these settings to `.streamlit/secrets.toml`:

```toml
[smtp]
server = "smtp.example.com"
port = 587
username = "your-smtp-username"
password = "your-smtp-password"
from_email = "no-reply@example.com"

[app]
url = "https://your-app-url"
```

- `server`: your SMTP host, for example `smtp.gmail.com`.
- `port`: usually `587` for TLS.
- `username` / `password`: your SMTP login credentials.
- `from_email`: the sender email address used in outgoing messages.
- `app.url`: the public URL for this Streamlit app, required to build approval links.

### 5. Set the Google Sheet ID in `streamlit_app.py`

Open `streamlit_app.py` and confirm the `GOOGLE_SHEET_ID` value matches your Google Sheet ID.

The sheet ID is the long string in the URL: `https://docs.google.com/spreadsheets/d/[SHEET_ID]/edit`

```python
GOOGLE_SHEET_ID = "your-sheet-id-here"
```

### 5. Set up Google Sheets structure

Your Google Sheet should contain these input tabs:

- `Employees`
- `Questions`
- `Employee_Questions`

The app will create `Responses` and `Employee_Responses` automatically if they do not already exist.

#### **Employees Tab**
This tab contains all employees and their managers. Required columns (case-sensitive):

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `ID` | Number/Text | Yes | Unique employee identifier |
| `name` | Text | Yes | Employee's full name |
| `email` | Text | Yes | Employee's email address |
| `manager_email` | Text | Yes | Manager's email address |
| `manager_name` | Text | No | Manager's full name (optional) |
| `branch` | Text | No | Branch/location (optional) |
| `dept` | Text | No | Department (optional) |
| `job_title` | Text | No | Job title (optional) |
| `executive_email` | Text | No | Executive's email for final approval (optional) |

**Example:**
```
ID | name | email | manager_email | manager_name | branch | dept | job_title | executive_email
1  | John Doe | john@company.com | manager@company.com | Jane Manager | HQ | Sales | Sales Rep | exec@company.com
2  | Jane Smith | jane@company.com | manager@company.com | Jane Manager | HQ | Sales | Sales Rep | exec@company.com
```

#### **Questions Tab**
This tab contains all manager 9-box questions. Required columns (case-sensitive):

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `ID` | Number/Text | Yes | Unique question identifier |
| `points` | Number | Yes | Points to add when the manager answers Yes |
| `question` | Text | Yes | The question text shown to managers |
| `role` | Text | Yes | Employee role/job title this question applies to |

Role matching notes:
- The app matches each employee using Employees.role or Employees.job_title.
- A role cell can contain multiple role names separated by commas.
- If role is blank, the question applies to every employee (supported, but optional by your process).

**Example:**
```
ID | points | question | role
1  | 1      | Consistently meets branch goals       | Membership Director
2  | 2      | Mentors team members proactively      | Membership Director
3  | 1      | Builds cross-team partnerships        | Membership Director, Program Director
4  | 1      | Demonstrates YMCA values daily        | 
```

#### **Employee_Questions Tab**
This tab contains the questions employees answer after logging in with their own email address. Required columns (case-sensitive):

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `ID` | Number/Text | Yes | Unique question identifier |
| `question` | Text | Yes | The prompt shown to the employee |
| `type` | Text | Yes | Either `Multi-Line` or `Three Line` |
| `question_section` | Text | No | Groups questions into sections |

Notes:
- `Multi-Line` renders a multi-line text area.
- `Three Line` renders three single-line inputs for the same question.
- Employee questions do not affect any score or approval status.

**Example:**
```
ID | question | type | question_section
1  | What accomplishments are you most proud of this period? | Multi-Line | Accomplishments
2  | List up to three goals for next period. | Three Line | Future Focus
```

#### **Responses Tab**
This tab is created automatically by the app. Do not create it manually - it will be initialized with these columns:

| Column | Type | Description |
|--------|------|-------------|
| `response_id` | Text | Unique response identifier |
| `created_at` | DateTime | When response was created |
| `updated_at` | DateTime | When response was last updated |
| `manager_email` | Text | Manager who created the evaluation |
| `manager_name` | Text | Manager's name |
| `employee_id` | Text | Employee's ID |
| `employee_name` | Text | Employee's name |
| `employee_email` | Text | Employee's email |
| `branch` | Text | Employee's branch |
| `dept` | Text | Employee's department |
| `job_title` | Text | Employee's job title |
| `executive_email` | Text | Executive's email |
| `questions_score` | Number | 9-box total points (base 6 plus points for Yes answers) |
| `number_of_nos` | Number | Count of "No" answers |
| `responses` | Text | JSON string of all answers |
| `employee_agree` | Text | Employee approval status |
| `manager_agree` | Text | Manager approval status |
| `executive_agree` | Text | Executive approval status |
| `employee_agree_ts` | DateTime | Employee approval timestamp |
| `manager_agree_ts` | DateTime | Manager approval timestamp |
| `executive_agree_ts` | DateTime | Executive approval timestamp |
| `status` | Text | Current approval status |
| `employee_token` | Text | Employee approval token |
| `manager_token` | Text | Manager approval token |
| `executive_token` | Text | Executive approval token |

#### **Employee_Responses Tab**
This tab stores employee self-responses. The app creates it automatically if it is missing. If you create it manually, use these columns in this order:

| Column | Type | Description |
|--------|------|-------------|
| `response_id` | Text | Unique employee response identifier |
| `created_at` | DateTime | When the employee response was created |
| `updated_at` | DateTime | When the employee response was last updated |
| `employee_id` | Text | Employee's ID from the Employees tab |
| `employee_name` | Text | Employee's name |
| `employee_email` | Text | Employee's email |
| `branch` | Text | Employee's branch |
| `dept` | Text | Employee's department |
| `job_title` | Text | Employee's job title |
| `responses` | Text | JSON string containing all employee answers |
| `status` | Text | Submission status, currently `Submitted` |

Employee response behavior:
- Employees log in using the `email` column from the `Employees` tab.
- Each employee can have only one active record in `Employee_Responses`.
- If a response already exists, the employee sees it instead of a blank form.
- Employees can edit and update their existing response while no manager scorecard exists or the manager scorecard is still in `Draft`.
- Once the manager scorecard enters approval (any non-`Draft` manager status), the employee self-evaluation becomes read-only.
- If a manager scorecard is rejected and reset/removed, the employee self-evaluation becomes editable again.
- Managers cannot submit a scorecard for an employee until that employee has a self-evaluation on file.
- If a self-evaluation is missing, the manager dashboard can send a reminder email to the employee with the app link.
- Managers can view submitted self-evaluations at any time in the `Employee Self-Evaluations` tab.
- Managers can toggle self-evaluation visibility on and off in both the scorecard submission view and the `Employee Self-Evaluations` tab.
- When shown to managers, self-evaluations are displayed in a compact table format.

### 6. Test your setup (optional but recommended)

Before running the main app, test your Google Sheets connection:

```bash
python test_setup.py
```

This script will check:
- All required packages are installed
- Secrets file exists and is configured
- Google Sheets connection works
- Required worksheets exist

### 7. Run the app

```bash
streamlit run streamlit_app.py
```

### 8. Deploy the Application (Required for Approval Links)

**Important**: The approval workflow requires the app to be deployed with a public URL. Local development won't work for email approval links.

#### **Option 1: Streamlit Cloud (Recommended)**

1. Push your code to GitHub:
   ```bash
   git add .
   git commit -m "Ready for deployment"
   git push origin main
   ```

2. Go to [share.streamlit.io](https://share.streamlit.io) and connect your GitHub repo.

3. In the app settings, add the secrets under the "Secrets" section using the same TOML format as above:
   ```toml
   [gcp_service_account]
   type = "service_account"
   project_id = "your-project-id"
   private_key_id = "your-private-key-id"
   private_key = "-----BEGIN PRIVATE KEY-----\nYOUR_PRIVATE_KEY\n-----END PRIVATE KEY-----\n"
   client_email = "your-service-account@your-project.iam.gserviceaccount.com"
   client_id = "your-client-id"
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-service-account%40your-project.iam.gserviceaccount.com"

   [smtp]
   server = "smtp.gmail.com"
   port = 587
   username = "your-email@gmail.com"
   password = "your-app-password"
   from_email = "no-reply@yourdomain.com"

   [app]
   url = "https://your-app-name.streamlit.app"
   ```

4. Deploy the app. Streamlit Cloud will provide a URL like `https://your-app-name.streamlit.app`

5. **Update the `app.url` in your secrets** with the actual Streamlit Cloud URL.

#### **Option 2: Local Development with Port Forwarding**

For testing approval links locally:

1. Run the app locally:
   ```bash
   streamlit run streamlit_app.py
   ```

2. Use a port forwarding service like:
   - **ngrok**: `ngrok http 8501` (provides a public URL)
   - **LocalTunnel**: `npx localtunnel --port 8501`
   - **Cloudflare Tunnel**: `cloudflared tunnel --url http://localhost:8501`

3. Update `app.url` in `.streamlit/secrets.toml` with the forwarded URL.

#### **Option 3: Other Deployment Platforms**

- **Heroku**: Create a `requirements.txt` and `Procfile`, then deploy
- **Railway**: Connect your GitHub repo
- **Render**: Deploy from GitHub
- **Vercel**: Use their Streamlit support
- **AWS/Azure/GCP**: Deploy as a containerized app

### 9. Test the Approval Workflow

After deployment:

1. Submit a scorecard as a manager
2. Check that the employee receives the email
3. Click the approval/reject links in the email
4. Verify the status updates in the app
5. Log in as an employee using an email from the `Employees` tab and confirm the employee response flow works

**Note**: If you're running locally and getting 404 errors, you need to deploy the app or use port forwarding (see deployment options above). Local URLs like `http://localhost:8501` won't work for email approval links.

## Troubleshooting

- **"This page can't be found" (404 error)**: The app is not deployed or the URL is incorrect. Deploy to Streamlit Cloud or use port forwarding.
- **Approval links don't work**: Check that `app.url` in secrets matches your deployed app's URL exactly.
- **Emails not sending**: Verify SMTP settings and that you're using an App Password for Gmail.
- If `gspread` or `google.oauth2.service_account` still show unresolved imports, check that VS Code is using the same interpreter where you installed the packages.
- If you see "Permission denied accessing Google Sheet":
  - **Most common issue**: The service account email has not been shared with your Google Sheet
  - Go to your Google Sheet → Share → Add the service account email (ends with `@your-project.iam.gserviceaccount.com`)
  - Give it "Editor" access (not just "Viewer")
  - Double-check the `GOOGLE_SHEET_ID` in `streamlit_app.py` matches your sheet URL
- If email sending fails, verify SMTP settings and credentials.
- If approval links are blank, confirm `app.url` is set correctly.

### Testing Your Setup

Run the test script to verify everything is configured:

```bash
python test_setup.py
```

This will check:
- All packages installed
- Secrets file exists and is valid
- Google Sheets connection works
- Required worksheets exist

- If `gspread` or `google.oauth2.service_account` still show unresolved imports, check that VS Code is using the same interpreter where you installed the packages.
- If email sending fails, verify SMTP settings and credentials.
- If approval links are blank, confirm `app.url` is set correctly.

## Notes

- The `Responses` sheet is created automatically if it does not exist.
- The `Employee_Responses` sheet is created automatically if it does not exist.
- The app stores approval timestamps in the responses sheet.
- Employee self-responses are stored separately and do not change manager scorecard scoring or approvals.
