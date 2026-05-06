import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json
import uuid
import smtplib
import io
from email.message import EmailMessage
from urllib.parse import urlencode
import time
from xml.sax.saxutils import escape
try:
    from response_submission import submit_manager_scorecard
except ImportError:
    def submit_manager_scorecard(response_entry, existing_draft, append_fn, delete_fn, delete_all_drafts=None):
        """Fallback submit helper when response_submission module is unavailable."""
        try:
            if delete_all_drafts:
                delete_all_drafts(
                    response_entry.get('manager_email', ''),
                    response_entry.get('employee_id', ''),
                    exclude_response_id=(existing_draft or {}).get('response_id') if existing_draft else None
                )
            if existing_draft and existing_draft.get('response_id'):
                delete_fn(existing_draft.get('response_id'))
            append_fn(response_entry)
            return True, response_entry, ""
        except Exception as exc:
            return False, response_entry, str(exc)
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# ============================================================================
# PAGE CONFIG
# ============================================================================
st.set_page_config(
    page_title="Leader Level Balanced Score Card",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Minimal CSS to avoid breaking Streamlit's UI rendering
custom_css = """
<style>
    .stApp {
        background:
            radial-gradient(1200px 400px at 15% -10%, color-mix(in srgb, var(--primary-color) 10%, transparent), transparent 60%),
            radial-gradient(1000px 350px at 90% 0%, color-mix(in srgb, var(--primary-color) 8%, transparent), transparent 55%),
            var(--background-color);
    }

    [data-baseweb="tab-list"] {
        gap: 0.5rem;
    }

    [data-baseweb="tab"] {
        border-radius: 10px;
        padding: 0.5rem 0.9rem;
        background: color-mix(in srgb, var(--secondary-background-color) 88%, var(--background-color));
        border: 1px solid color-mix(in srgb, var(--text-color) 12%, transparent);
    }

    [data-baseweb="tab"][aria-selected="true"] {
        border-color: color-mix(in srgb, var(--primary-color) 45%, transparent);
    }

    [data-testid="stMetricValue"] {
        color: var(--primary-color);
    }

    .stButton>button {
        background-color: var(--primary-color);
        color: var(--background-color);
        border: none;
        border-radius: 8px;
        font-weight: 500;
    }
    
    .stButton>button:hover {
        filter: brightness(0.92);
    }
    
    code {
        background-color: color-mix(in srgb, var(--secondary-background-color) 92%, var(--background-color));
        color: var(--text-color);
        border-radius: 4px;
        padding: 2px 4px;
    }
    
    /* Expander styling only */
    .streamlit-expanderHeader {
        font-weight: bold;
        color: var(--text-color);
    }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

# ============================================================================
# GOOGLE SHEETS CONFIG
# ============================================================================
GOOGLE_SHEET_ID = "1DfYJwlKy01G0tcZ11FUen4fPjSnK9vWT33a2sKfRKko"
EMPLOYEES_TAB = "Employees"
QUESTIONS_TAB = "Questions"
RESPONSES_TAB = "Responses"
EMPLOYEE_QUESTIONS_TAB = "Employee_Questions"
EMPLOYEE_RESPONSES_TAB = "Employee_Responses"
MANAGERS_TAB = "Managers"
EXECUTIVES_TAB = "Executives"
PASSWORD_ADMIN_EMAIL = "nparrish@ymcapgh.org"
EXECUTIVE_ADMIN_EMAIL = "nparrish@ymcapgh.org"
DEFAULT_DATA_SYNC_MINUTES = 5

MANAGER_RESPONSE_COLUMNS = [
    "response_id", "created_at", "updated_at", "manager_email", "manager_name",
    "employee_id", "employee_name", "employee_email", "branch", "dept",
    "job_title", "executive_email", "questions_score", "number_of_nos",
    "responses", "comments", "employee_agree", "manager_agree", "executive_agree",
    "employee_agree_ts", "manager_agree_ts", "executive_agree_ts",
    "status", "employee_token", "manager_token", "executive_token"
]

EMPLOYEE_RESPONSE_COLUMNS = [
    "response_id", "created_at", "updated_at", "employee_id", "employee_name",
    "employee_email", "branch", "dept", "job_title", "responses", "status"
]

# Optional Streamlit secrets values:
# [gcp_service_account]
# ... your service account JSON fields ...
# [smtp]
# server = "smtp.example.com"
# port = 587
# username = "user@example.com"
# password = "secret"
# from_email = "no-reply@example.com"
# [app]
# url = "https://your-app-url.streamlit.app"
# data_sync_minutes = 5

# ============================================================================
# GOOGLE SHEETS UTILITIES
# ============================================================================

@st.cache_resource
def get_spreadsheet():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        client = gspread.authorize(creds)
        return client.open_by_key(GOOGLE_SHEET_ID)
    except KeyError:
        st.error("Google service account credentials not found in secrets.")
        st.info("Please configure your `.streamlit/secrets.toml` file with the service account credentials.")
        st.stop()
    except PermissionError:
        st.error("Permission denied accessing Google Sheet.")
        st.info("Make sure:")
        st.info("1. The service account email has been shared with the Google Sheet")
        st.info("2. The GOOGLE_SHEET_ID is correct")
        st.info("3. The service account has 'Editor' access to the sheet")
        st.stop()
    except Exception as e:
        st.error(f"Error connecting to Google Sheets: {e}")
        st.info("Please check your service account configuration and Google Sheet permissions.")
        st.stop()

@st.cache_data(ttl=300)
def load_sheet(tab_name):
    spreadsheet = get_spreadsheet()
    try:
        worksheet = spreadsheet.worksheet(tab_name)
        records = worksheet.get_all_records()
        return pd.DataFrame(records)
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()
    except Exception as exc:
        st.error(f"Unable to load `{tab_name}` sheet: {exc}")
        return pd.DataFrame()


def ensure_dataframe_columns(df, expected_columns):
    if df.empty:
        return pd.DataFrame(columns=expected_columns)

    for col in expected_columns:
        if col not in df.columns:
            df[col] = ""

    return df


def column_letter(index):
    result = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def ensure_sheet_headers(worksheet, headers):
    existing_headers = worksheet.row_values(1)
    if not existing_headers:
        worksheet.append_row(headers)
        return worksheet

    if existing_headers != headers:
        worksheet.update(f"A1:{column_letter(len(headers))}1", [headers])

    return worksheet


def get_data_sync_minutes():
    raw_value = st.secrets.get("app", {}).get("data_sync_minutes", DEFAULT_DATA_SYNC_MINUTES)
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return DEFAULT_DATA_SYNC_MINUTES


def clear_data_caches():
    load_sheet.clear()
    load_responses.clear()
    load_employee_responses.clear()


def sync_session_data():
    st.session_state.employees_df = load_sheet(EMPLOYEES_TAB)
    st.session_state.questions_df = load_sheet(QUESTIONS_TAB)
    st.session_state.managers_df = load_sheet(MANAGERS_TAB)
    st.session_state.executives_df = load_sheet(EXECUTIVES_TAB)
    st.session_state.responses_df = load_responses()
    st.session_state.data_loaded = True
    st.session_state.last_data_sync_ts = time.time()

@st.cache_data(ttl=300)
def load_responses():
    """Load responses from the Responses sheet."""
    try:
        spreadsheet = get_spreadsheet()
        worksheet = ensure_responses_sheet(spreadsheet)
        records = worksheet.get_all_records()
        df = pd.DataFrame(records)
        return ensure_dataframe_columns(df, MANAGER_RESPONSE_COLUMNS)
        
    except Exception as e:
        st.error("Could not load responses from the sheet.")
        st.error(str(e))
        return pd.DataFrame()

def ensure_responses_sheet(spreadsheet):
    try:
        worksheet = spreadsheet.worksheet(RESPONSES_TAB)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(RESPONSES_TAB, rows=1000, cols=len(MANAGER_RESPONSE_COLUMNS))
        worksheet.append_row(MANAGER_RESPONSE_COLUMNS)
        return worksheet

    return ensure_sheet_headers(worksheet, MANAGER_RESPONSE_COLUMNS)


def ensure_employee_responses_sheet(spreadsheet):
    try:
        worksheet = spreadsheet.worksheet(EMPLOYEE_RESPONSES_TAB)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(EMPLOYEE_RESPONSES_TAB, rows=1000, cols=len(EMPLOYEE_RESPONSE_COLUMNS))
        worksheet.append_row(EMPLOYEE_RESPONSE_COLUMNS)
        return worksheet

    return ensure_sheet_headers(worksheet, EMPLOYEE_RESPONSE_COLUMNS)


@st.cache_data(ttl=300)
def load_employee_responses():
    try:
        spreadsheet = get_spreadsheet()
        worksheet = ensure_employee_responses_sheet(spreadsheet)
        records = worksheet.get_all_records()
        df = pd.DataFrame(records)
        return ensure_dataframe_columns(df, EMPLOYEE_RESPONSE_COLUMNS)
    except Exception as e:
        st.error("Could not load employee responses from the sheet.")
        st.error(str(e))
        return pd.DataFrame()

# ============================================================================
# EMAIL UTILITIES
# ============================================================================

def get_app_url():
    return st.secrets.get("app", {}).get("url", "").rstrip("/")


def get_manager_sender_email(default_email=""):
    session_manager_email = str(st.session_state.get("manager_email", "")).strip().lower()
    if session_manager_email and "@" in session_manager_email:
        return session_manager_email

    fallback_email = str(default_email).strip().lower()
    if fallback_email and "@" in fallback_email:
        return fallback_email

    return ""

def build_action_link(response_id, token, action):
    base = get_app_url()
    if not base:
        return ""
    params = {
        "response_id": response_id,
        "token": token,
        "action": action
    }
    return f"{base}/?{urlencode(params)}"


def send_email(subject, html_body, recipient, sender_email="", require_sender=False):
    smtp_config = st.secrets.get("smtp", {})
    if not smtp_config:
        return False

    try:
        resolved_sender = get_manager_sender_email(sender_email)
        if require_sender and not resolved_sender:
            st.error("Email send failed: valid manager email is required as the sender.")
            return False

        default_sender = smtp_config.get("from_email", smtp_config.get("username"))
        from_header = resolved_sender or default_sender
        envelope_sender = resolved_sender or smtp_config.get("username") or default_sender

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = from_header
        message["To"] = recipient
        if resolved_sender:
            message["Reply-To"] = resolved_sender
        message.set_content("Please view this message in an HTML-capable email client.")
        message.add_alternative(html_body, subtype="html")

        server = smtplib.SMTP(smtp_config["server"], int(smtp_config.get("port", 587)))
        server.starttls()
        server.login(smtp_config["username"], smtp_config["password"])
        server.send_message(message, from_addr=envelope_sender, to_addrs=[recipient])
        server.quit()
        return True
    except Exception as exc:
        st.error(f"Email send failed: {exc}")
        return False


def get_manager_sheet_columns(managers_df):
    normalized_columns = {str(col).strip().lower(): col for col in managers_df.columns}
    email_column = normalized_columns.get("manager_email") or normalized_columns.get("email")
    password_column = normalized_columns.get("password")
    manager_name_column = normalized_columns.get("manager_name")
    return email_column, password_column, manager_name_column


def get_executive_sheet_columns(executives_df):
    normalized_columns = {str(col).strip().lower(): col for col in executives_df.columns}
    email_column = normalized_columns.get("executive_email") or normalized_columns.get("email")
    password_column = normalized_columns.get("password")
    return email_column, password_column


def send_manager_password_email(manager_email, manager_password, manager_name=""):
    app_url = get_app_url()
    subject = "Leader Level Balanced Score Card - Manager Login Password"
    greeting_name = str(manager_name).strip() or manager_email
    body = [f"<h2>Manager Login Details</h2>"]
    body.append(f"<p>Hello {greeting_name},</p>")
    body.append("<p>Here are your current manager login details for the Leader Level Balanced Score Card app:</p>")
    body.append(f"<p><strong>Email:</strong> {manager_email}<br><strong>Password:</strong> {manager_password}</p>")
    if app_url:
        body.append(f"<p><a href=\"{app_url}\" style=\"background:#006B6B;color:white;padding:10px 14px;text-decoration:none;border-radius:4px;\">Open the app</a></p>")
    body.append("<p>If you were not expecting this email, contact the app administrator.</p>")
    return send_email(subject, "".join(body), manager_email, sender_email=manager_email)


def email_all_manager_passwords(managers_df):
    if managers_df.empty:
        return 0, [], "Managers sheet is missing or empty."

    email_column, password_column, manager_name_column = get_manager_sheet_columns(managers_df)
    if not email_column or not password_column:
        return 0, [], "Managers sheet must include email (or manager_email) and password columns."

    unique_managers = managers_df.copy()
    unique_managers[email_column] = unique_managers[email_column].astype(str).str.strip().str.lower()
    unique_managers = unique_managers[unique_managers[email_column] != ""]
    unique_managers = unique_managers.drop_duplicates(subset=[email_column], keep="first")

    if unique_managers.empty:
        return 0, [], "Managers sheet does not contain any valid manager email addresses."

    sent_count = 0
    failed_emails = []

    for _, manager_row in unique_managers.iterrows():
        manager_email = str(manager_row.get(email_column, "")).strip().lower()
        manager_password = str(manager_row.get(password_column, ""))
        manager_name = str(manager_row.get(manager_name_column, "")).strip() if manager_name_column else ""

        if not manager_password:
            failed_emails.append(f"{manager_email} (missing password)")
            continue

        if send_manager_password_email(manager_email, manager_password, manager_name):
            sent_count += 1
        else:
            failed_emails.append(manager_email)

    return sent_count, failed_emails, ""


def send_executive_password_email(executive_email, executive_password):
    app_url = get_app_url()
    subject = "Leader Level Balanced Score Card - Executive Login Password"
    body = ["<h2>Executive Login Details</h2>"]
    body.append(f"<p>Hello {executive_email},</p>")
    body.append("<p>Here are your current executive login details for the Leader Level Balanced Score Card app:</p>")
    body.append(f"<p><strong>Email:</strong> {executive_email}<br><strong>Password:</strong> {executive_password}</p>")
    if app_url:
        body.append(f"<p><a href=\"{app_url}\" style=\"background:#006B6B;color:white;padding:10px 14px;text-decoration:none;border-radius:4px;\">Open the app</a></p>")
    body.append("<p>If you were not expecting this email, contact the app administrator.</p>")
    return send_email(subject, "".join(body), executive_email)


def email_all_executive_passwords(executives_df):
    if executives_df.empty:
        return 0, [], "Executives sheet is missing or empty."

    email_column, password_column = get_executive_sheet_columns(executives_df)
    if not email_column or not password_column:
        return 0, [], "Executives sheet must include executive_email (or email) and password columns."

    unique_executives = executives_df.copy()
    unique_executives[email_column] = unique_executives[email_column].astype(str).str.strip().str.lower()
    unique_executives = unique_executives[unique_executives[email_column] != ""]
    unique_executives = unique_executives.drop_duplicates(subset=[email_column], keep="first")

    if unique_executives.empty:
        return 0, [], "Executives sheet does not contain any valid executive email addresses."

    sent_count = 0
    failed_emails = []

    for _, executive_row in unique_executives.iterrows():
        executive_email = str(executive_row.get(email_column, "")).strip().lower()
        executive_password = str(executive_row.get(password_column, ""))

        if not executive_password:
            failed_emails.append(f"{executive_email} (missing password)")
            continue

        if send_executive_password_email(executive_email, executive_password):
            sent_count += 1
        else:
            failed_emails.append(executive_email)

    return sent_count, failed_emails, ""


def render_mass_email_confirmation(action_key, trigger_label, prompt_text):
    state_key = f"mass_email_confirm_{action_key}"
    if st.button(trigger_label, key=f"{action_key}_trigger"):
        st.session_state[state_key] = True

    if not st.session_state.get(state_key, False):
        return False

    st.warning(prompt_text)
    yes_col, no_col = st.columns(2)
    yes_clicked = yes_col.button("Yes", type='primary', key=f"{action_key}_yes")
    no_clicked = no_col.button("No", key=f"{action_key}_no")

    if no_clicked:
        st.session_state[state_key] = False
        st.info("Mass email canceled.")
        return False

    if yes_clicked:
        st.session_state[state_key] = False
        return True

    return False


def format_scorecard_summary(employee, question_rows, answers):
    lines = []
    lines.append(f"<p><strong>Employee:</strong> {employee['name']} ({employee['ID']})</p>")
    lines.append(f"<p><strong>Branch:</strong> {employee.get('branch', '')} &nbsp;&nbsp; <strong>Dept:</strong> {employee.get('dept', '')} &nbsp;&nbsp; <strong>Job Title:</strong> {employee.get('job_title', '')}</p>")
    lines.append("<table border='0' cellpadding='6' cellspacing='0' style='border-collapse:collapse;'>")
    lines.append("<tr><th align='left'>Section</th><th align='left'>Question</th><th align='left'>Points</th><th align='left'>Answer</th></tr>")
    for _, row in question_rows.iterrows():
        answer = answers.get(str(row['ID']), "")
        points_value = parse_question_points(row.get('points', 0))
        lines.append(
            f"<tr><td>{row['question_section']}</td><td>{row['question']}</td><td>{points_value}</td><td>{answer}</td></tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def format_email_body(subject, employee, question_rows, answers, stage, approve_link, reject_link, comment=""):
    questions_score, number_of_nos, yes_count, nine_box_rating = calculate_9box_metrics(answers, question_rows)

    html = [f"<h2>{subject}</h2>"]
    html.append(format_scorecard_summary(employee, question_rows, answers))
    html.append(f"<p><strong>Total Points:</strong> {questions_score}</p>")
    html.append(f"<p><strong>Yes Answers:</strong> {yes_count}</p>")
    html.append(f"<p><strong>Number of No answers:</strong> {number_of_nos}</p>")
    html.append(f"<p><strong>9-Box Rating:</strong> {nine_box_rating}</p>")

    if approve_link or reject_link:
        html.append("<p>Please approve or reject using the links below.</p>")
        if approve_link:
            html.append(f"<p><a href=\"{approve_link}\" style=\"background:#006B6B;color:white;padding:10px 14px;text-decoration:none;border-radius:4px;\">Approve</a></p>")
        if reject_link:
            html.append(f"<p><a href=\"{reject_link}\" style=\"background:#A80000;color:white;padding:10px 14px;text-decoration:none;border-radius:4px;\">Reject</a></p>")
    html.append("<p>If you have any questions, please contact your manager.</p>")

    # Keep comments at the end for all stages (employee, manager, executive).
    if comment.strip():
        html.append(f"<p><strong>Manager Comments:</strong></p><blockquote style='border-left: 4px solid #006B6B; padding-left: 10px; margin: 10px 0; font-style: italic;'>{comment.strip()}</blockquote>")

    return "".join(html)


def calculate_score_metrics(answers):
    total_points = 6 + sum(1 for _, v in answers.items() if str(v).strip().lower() == "yes")
    number_of_nos = sum(1 for _, v in answers.items() if str(v).strip().lower() == "no")
    return total_points, number_of_nos


def normalize_text(value):
    return str(value or "").strip()


def normalize_text_lower(value):
    return normalize_text(value).lower()


def get_first_matching_column(df, candidates):
    lowered = {str(col).strip().lower(): col for col in df.columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def parse_question_points(value):
    text = normalize_text(value)
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def row_role_matches_question(role_cell, employee_role):
    role_cell_text = normalize_text_lower(role_cell)
    employee_role_text = normalize_text_lower(employee_role)

    if not role_cell_text:
        return True
    if not employee_role_text:
        return False

    role_tokens = [token.strip() for token in role_cell_text.replace("|", ",").split(",") if token.strip()]
    if not role_tokens:
        return True

    return employee_role_text in role_tokens


def prepare_9box_questions(questions_df, employee_row):
    if questions_df.empty:
        return pd.DataFrame(columns=["ID", "question", "points", "question_section", "header"])

    role_column = get_first_matching_column(questions_df, ["role", "employee_role", "job_title", "position", "title"])
    points_column = get_first_matching_column(questions_df, ["points", "point", "point_value", "point_rating", "value", "score"])
    id_column = get_first_matching_column(questions_df, ["id"])
    question_column = get_first_matching_column(questions_df, ["question", "questions", "prompt"])
    section_column = get_first_matching_column(questions_df, ["question_section", "section"])
    header_column = get_first_matching_column(questions_df, ["header"])

    if not id_column or not question_column:
        return pd.DataFrame(columns=["ID", "question", "points", "question_section", "header"])

    employee_role = employee_row.get('role', employee_row.get('job_title', ''))
    scoped = questions_df.copy()
    if role_column:
        scoped = scoped[
            scoped[role_column].apply(lambda cell: row_role_matches_question(cell, employee_role))
        ].copy()

    if scoped.empty:
        return pd.DataFrame(columns=["ID", "question", "points", "question_section", "header"])

    scoped = scoped.fillna("")
    normalized = pd.DataFrame()
    normalized["ID"] = scoped[id_column].astype(str).str.strip()
    normalized["question"] = scoped[question_column].astype(str).str.strip()
    normalized["points"] = scoped[points_column].apply(parse_question_points) if points_column else 1
    normalized["question_section"] = scoped[section_column].astype(str).str.strip() if section_column else ""
    normalized["header"] = scoped[header_column].astype(str).str.strip() if header_column else ""

    normalized = normalized[normalized["question"] != ""]
    normalized = normalized[normalized["ID"] != ""]
    normalized = normalized.reset_index(drop=True)
    return normalized


def normalize_question_rows_for_display(questions_df):
    if questions_df.empty:
        return pd.DataFrame(columns=["ID", "question", "points", "question_section", "header"])

    id_column = get_first_matching_column(questions_df, ["id"])
    question_column = get_first_matching_column(questions_df, ["question", "questions", "prompt"])
    points_column = get_first_matching_column(questions_df, ["points", "point", "point_value", "point_rating", "value", "score"])
    section_column = get_first_matching_column(questions_df, ["question_section", "section"])
    header_column = get_first_matching_column(questions_df, ["header"])

    if not id_column or not question_column:
        return pd.DataFrame(columns=["ID", "question", "points", "question_section", "header"])

    normalized = pd.DataFrame()
    normalized["ID"] = questions_df[id_column].astype(str).str.strip()
    normalized["question"] = questions_df[question_column].astype(str).str.strip()
    normalized["points"] = questions_df[points_column].apply(parse_question_points) if points_column else 0
    normalized["question_section"] = questions_df[section_column].astype(str).str.strip() if section_column else ""
    normalized["header"] = questions_df[header_column].astype(str).str.strip() if header_column else ""
    normalized = normalized[normalized["question"] != ""]
    normalized = normalized[normalized["ID"] != ""]
    return normalized.reset_index(drop=True)


def get_question_rows_for_answers(questions_df, answers):
    normalized = normalize_question_rows_for_display(questions_df)
    if normalized.empty:
        return normalized

    answer_ids = {str(question_id).strip() for question_id in (answers or {}).keys()}
    if not answer_ids:
        return normalized

    filtered = normalized[normalized['ID'].astype(str).isin(answer_ids)].copy()
    return filtered.reset_index(drop=True) if not filtered.empty else normalized


def calculate_9box_metrics(answers, question_rows, base_points=6):
    points_lookup = {}
    if not question_rows.empty:
        points_lookup = {
            str(row.get('ID', '')).strip(): parse_question_points(row.get('points', 0))
            for _, row in question_rows.iterrows()
        }

    yes_points = 0
    no_count = 0
    yes_count = 0

    for question_id, answer in answers.items():
        normalized_answer = normalize_text_lower(answer)
        if normalized_answer == 'yes':
            yes_count += 1
            yes_points += points_lookup.get(str(question_id).strip(), 0)
        elif normalized_answer == 'no':
            no_count += 1

    total_points = base_points + yes_points
    nine_box_rating = max(1, min(9, total_points))
    return total_points, no_count, yes_count, nine_box_rating


def get_latest_manager_draft_response(responses_df, manager_email, employee_id):
    if responses_df.empty:
        return None

    matches = responses_df[
        (responses_df['manager_email'].astype(str).str.strip().str.lower() == manager_email.strip().lower())
        & (responses_df['employee_id'].astype(str) == str(employee_id))
        & (responses_df['status'].astype(str).str.strip().str.lower() == "draft")
    ].copy()

    if matches.empty:
        return None

    matches['sort_timestamp'] = matches['updated_at'].astype(str)
    return matches.sort_values('sort_timestamp', ascending=False).iloc[0].to_dict()


def get_latest_manager_response_for_employee(responses_df, employee_id):
    if responses_df.empty:
        return None

    matches = responses_df[
        responses_df['employee_id'].astype(str).str.strip() == str(employee_id).strip()
    ].copy()

    if matches.empty:
        return None

    if 'updated_at' in matches.columns:
        matches['sort_timestamp'] = matches['updated_at'].astype(str)
    elif 'created_at' in matches.columns:
        matches['sort_timestamp'] = matches['created_at'].astype(str)
    else:
        matches['sort_timestamp'] = ""

    return matches.sort_values('sort_timestamp', ascending=False).iloc[0].to_dict()


def manager_response_locks_employee_self_eval(manager_response):
    if not manager_response:
        return False

    status = str(manager_response.get('status', '')).strip().lower()
    if not status:
        return False

    # Draft reviews can coexist with editable self-evals; any non-draft status is in/after approval flow.
    return status != 'draft'


def get_missing_scorecards_by_manager(employees_df, responses_df, branch_names=None):
    if employees_df.empty:
        return {}

    scoped_employees = employees_df.copy()
    if branch_names:
        normalized_branch_names = {str(branch).strip().lower() for branch in branch_names if str(branch).strip()}
        scoped_employees = scoped_employees[
            scoped_employees['branch'].astype(str).str.strip().str.lower().isin(normalized_branch_names)
        ]

    if scoped_employees.empty:
        return {}

    submitted_lookup = set()
    if not responses_df.empty:
        submitted_responses = responses_df[
            responses_df['status'].astype(str).str.strip().str.lower() != "draft"
        ].copy()

        for _, row in submitted_responses.iterrows():
            manager_key = str(row.get('manager_email', '')).strip().lower()
            employee_key = str(row.get('employee_id', '')).strip()
            if manager_key and employee_key:
                submitted_lookup.add((manager_key, employee_key))

    missing_by_manager = {}

    for _, employee_row in scoped_employees.iterrows():
        manager_email = str(employee_row.get('manager_email', '')).strip().lower()
        employee_id = str(employee_row.get('ID', '')).strip()

        if not manager_email or not employee_id:
            continue

        if (manager_email, employee_id) in submitted_lookup:
            continue

        missing_by_manager.setdefault(manager_email, []).append(
            {
                "employee_name": str(employee_row.get('name', '')).strip() or employee_id,
                "employee_id": employee_id,
                "branch": str(employee_row.get('branch', '')).strip(),
                "manager_name": str(employee_row.get('manager_name', '')).strip()
            }
        )

    return missing_by_manager


def send_missing_scorecard_email_to_manager(manager_email, manager_name, missing_employees):
    if not manager_email or '@' not in manager_email:
        return False

    app_url = get_app_url()
    greeting_name = manager_name or manager_email
    subject = "Action Required: Missing balanced scorecards"
    body = ["<h2>Balanced scorecards missing</h2>"]
    body.append(f"<p>Hello {greeting_name},</p>")
    body.append("<p>The following employees do not yet have a submitted balanced scorecard:</p>")
    body.append("<ul>")
    for item in missing_employees:
        branch_text = f" - {item.get('branch', '')}" if item.get('branch', '') else ""
        body.append(f"<li>{item.get('employee_name', '')} ({item.get('employee_id', '')}){branch_text}</li>")
    body.append("</ul>")

    if app_url:
        body.append(f"<p><a href=\"{app_url}\" style=\"background:#006B6B;color:white;padding:10px 14px;text-decoration:none;border-radius:4px;\">Open the app</a></p>")

    body.append("<p>Please submit these reviews as soon as possible.</p>")
    return send_email(subject, "".join(body), manager_email, sender_email=manager_email)


def email_managers_with_missing_scorecards(missing_by_manager):
    sent_count = 0
    failed_emails = []

    for manager_email, items in missing_by_manager.items():
        manager_name = str(items[0].get('manager_name', '')).strip() if items else ""
        if send_missing_scorecard_email_to_manager(manager_email, manager_name, items):
            sent_count += 1
        else:
            failed_emails.append(manager_email)

    return sent_count, failed_emails


def generate_scorecard_pdf(response, manager_questions_df, employee_questions_df, employee_self_eval):
    from reportlab.lib.units import inch

    MARGIN = 1 * inch
    PAGE_WIDTH = letter[0] - 2 * MARGIN  # usable width between 1-inch margins

    # Column widths: section(15%), question(50%), answer(35%)
    col_widths = [PAGE_WIDTH * 0.15, PAGE_WIDTH * 0.50, PAGE_WIDTH * 0.35]
    # Approval table: role(20%), decision(15%), timestamp(65%)
    approval_col_widths = [PAGE_WIDTH * 0.20, PAGE_WIDTH * 0.15, PAGE_WIDTH * 0.65]

    styles = getSampleStyleSheet()
    cell_style = styles['Normal']
    cell_style.fontSize = 8
    cell_style.leading = 10
    header_style = styles['Normal']

    def para(text):
        """Wrap plain text in a Paragraph so it word-wraps within its cell."""
        return Paragraph(escape(str(text)), cell_style)

    def make_table(rows, col_w, repeat_rows=1):
        """Build a Table with Paragraph cells so long text wraps."""
        para_rows = [[para(cell) if isinstance(cell, str) else cell for cell in row] for row in rows]
        tbl = Table(para_rows, colWidths=col_w, repeatRows=repeat_rows)
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        return tbl

    story = []
    story.append(Paragraph("Leader Level Balanced Score Card", styles['Title']))
    story.append(Spacer(1, 6))

    employee_name = escape(str(response.get('employee_name', '')))
    employee_id = escape(str(response.get('employee_id', '')))
    manager_name = escape(str(response.get('manager_name', '')))
    manager_email = escape(str(response.get('manager_email', '')))
    status = escape(str(response.get('status', '')))
    story.append(Paragraph(f"<b>Employee:</b> {employee_name} ({employee_id})", styles['Normal']))
    story.append(Paragraph(f"<b>Manager:</b> {manager_name} ({manager_email})", styles['Normal']))
    story.append(Paragraph(f"<b>Branch:</b> {escape(str(response.get('branch', '')))} &nbsp; <b>Dept:</b> {escape(str(response.get('dept', '')))}", styles['Normal']))
    story.append(Paragraph(f"<b>Status:</b> {status}", styles['Normal']))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Balanced Scorecard Responses", styles['Heading2']))
    manager_answers = parse_response_blob(response.get('responses', {}))
    manager_rows = [["Section", "Question", "Answer"]]
    for _, question in manager_questions_df.fillna("").iterrows():
        manager_rows.append([
            str(question.get('question_section', '')),
            str(question.get('question', '')),
            str(manager_answers.get(str(question.get('ID', '')), ''))
        ])
    story.append(make_table(manager_rows, col_widths))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Employee Self-Evaluation", styles['Heading2']))
    if employee_self_eval:
        self_answers = parse_response_blob(employee_self_eval.get('responses', {}))
        self_rows = [["Section", "Question", "Response"]]
        prepared_questions = prepare_employee_questions(employee_questions_df.fillna(""))
        for _, question in prepared_questions.iterrows():
            question_id = str(question.get('ID', ''))
            response_key = str(question.get('_response_key', ''))
            question_type = question.get('type', '')
            stored_value = self_answers.get(response_key)
            if stored_value is None:
                stored_value = self_answers.get(question_id, "")
            self_rows.append([
                str(question.get('question_section', '')),
                str(question.get('question', '')),
                format_compact_employee_answer(question_type, stored_value)
            ])
        story.append(make_table(self_rows, col_widths))
    else:
        story.append(Paragraph("No employee self-evaluation response found.", styles['Normal']))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Manager Comments", styles['Heading2']))
    manager_comments = str(response.get('comments', '')).strip()
    if manager_comments:
        comments_html = escape(manager_comments).replace("\n", "<br/>")
        story.append(Paragraph(comments_html, styles['Normal']))
    else:
        story.append(Paragraph("No manager comments provided.", styles['Normal']))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Approvals", styles['Heading2']))
    approvals_rows = [
        ["Role", "Decision", "Timestamp"],
        ["Employee", str(response.get('employee_agree', '')), str(response.get('employee_agree_ts', ''))],
        ["Manager", str(response.get('manager_agree', '')), str(response.get('manager_agree_ts', ''))],
        ["Executive", str(response.get('executive_agree', '')), str(response.get('executive_agree_ts', ''))]
    ]
    story.append(make_table(approvals_rows, approval_col_widths))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN
    )
    doc.build(story)
    return buffer.getvalue()

# ============================================================================
# RESPONSE OPERATIONS
# ============================================================================

def find_response_by_id(response_id):
    spreadsheet = get_spreadsheet()
    worksheet = ensure_responses_sheet(spreadsheet)
    records = worksheet.get_all_records()
    df = ensure_dataframe_columns(pd.DataFrame(records), MANAGER_RESPONSE_COLUMNS)
    if df.empty:
        return None, None, None
    matches = df[df['response_id'] == response_id]
    if matches.empty:
        return None, None, None
    row = matches.iloc[0]
    row_index = matches.index[0] + 2  # account for header row
    return row.to_dict(), row_index, df


def update_response(response_id, updates):
    try:
        spreadsheet = get_spreadsheet()
        worksheet = ensure_responses_sheet(spreadsheet)
        records = worksheet.get_all_records()
        df = ensure_dataframe_columns(pd.DataFrame(records), MANAGER_RESPONSE_COLUMNS)
        
        if df.empty:
            return False

        match = df[df['response_id'] == response_id]
        if match.empty:
            return False

        row_index = match.index[0] + 2
        header = worksheet.row_values(1)
        row_values = worksheet.row_values(row_index)
        row_data = {header[i]: row_values[i] if i < len(row_values) else "" for i in range(len(header))}

        for key, value in updates.items():
            if key not in header:
                header.append(key)
                # Update the worksheet header row with the new column
                worksheet.update(f"{column_letter(len(header))}{1}", [[key]])
                row_data[key] = value
            row_data[key] = value

        ordered_row = [row_data.get(col, "") for col in header]
        update_range = f"A{row_index}:{column_letter(len(header))}{row_index}"
        worksheet.update(update_range, [ordered_row])

        return True
    except Exception as e:
        st.error(f"Unable to update response: {e}")
        return False


def append_response(row):
    spreadsheet = get_spreadsheet()
    worksheet = ensure_responses_sheet(spreadsheet)
    header = worksheet.row_values(1)
    ordered_row = [row.get(col, "") for col in header]
    worksheet.append_row(ordered_row)


def find_employee_response_by_email(employee_email):
    spreadsheet = get_spreadsheet()
    worksheet = ensure_employee_responses_sheet(spreadsheet)
    records = worksheet.get_all_records()
    df = ensure_dataframe_columns(pd.DataFrame(records), EMPLOYEE_RESPONSE_COLUMNS)
    if df.empty:
        return None, None, None

    matches = df[df['employee_email'].astype(str).str.strip().str.lower() == employee_email.strip().lower()]
    if matches.empty:
        return None, None, df

    row = matches.sort_values('created_at', ascending=False).iloc[0]
    row_index = matches.sort_values('created_at', ascending=False).index[0] + 2
    return row.to_dict(), row_index, df


def get_latest_employee_response_for_email(employee_responses_df, employee_email):
    if employee_responses_df.empty:
        return None

    matches = employee_responses_df[
        employee_responses_df['employee_email'].astype(str).str.strip().str.lower() == employee_email.strip().lower()
    ].copy()

    if matches.empty:
        return None

    if 'updated_at' in matches.columns:
        matches['sort_timestamp'] = matches['updated_at'].astype(str)
    elif 'created_at' in matches.columns:
        matches['sort_timestamp'] = matches['created_at'].astype(str)
    else:
        matches['sort_timestamp'] = ""

    latest_row = matches.sort_values('sort_timestamp', ascending=False).iloc[0]
    return latest_row.to_dict()


def append_employee_response(row):
    spreadsheet = get_spreadsheet()
    worksheet = ensure_employee_responses_sheet(spreadsheet)
    header = worksheet.row_values(1)
    ordered_row = [row.get(col, "") for col in header]
    worksheet.append_row(ordered_row)


def update_employee_response(response_id, updates):
    try:
        spreadsheet = get_spreadsheet()
        worksheet = ensure_employee_responses_sheet(spreadsheet)
        records = worksheet.get_all_records()
        df = ensure_dataframe_columns(pd.DataFrame(records), EMPLOYEE_RESPONSE_COLUMNS)

        if df.empty:
            return False

        match = df[df['response_id'] == response_id]
        if match.empty:
            return False

        row_index = match.index[0] + 2
        header = worksheet.row_values(1)
        row_values = worksheet.row_values(row_index)
        row_data = {header[i]: row_values[i] if i < len(row_values) else "" for i in range(len(header))}

        for key, value in updates.items():
            if key not in header:
                header.append(key)
                worksheet.update(f"{column_letter(len(header))}{1}", [[key]])
                row_data[key] = value
            row_data[key] = value

        ordered_row = [row_data.get(col, "") for col in header]
        update_range = f"A{row_index}:{column_letter(len(header))}{row_index}"
        worksheet.update(update_range, [ordered_row])
        return True
    except Exception as e:
        st.error(f"Unable to update employee response: {e}")
        return False


def delete_employee_response(response_id):
    try:
        spreadsheet = get_spreadsheet()
        worksheet = ensure_employee_responses_sheet(spreadsheet)
        records = worksheet.get_all_records()
        df = ensure_dataframe_columns(pd.DataFrame(records), EMPLOYEE_RESPONSE_COLUMNS)
        if df.empty or 'response_id' not in df.columns:
            return False

        matches = df[df['response_id'] == response_id]
        if matches.empty:
            return False

        row_index = matches.index[0] + 2
        worksheet.delete_rows(row_index)
        return True
    except Exception as e:
        st.error(f"Unable to delete employee response: {e}")
        return False


def delete_response(response_id):
    """Delete a response row by response_id so manager can resubmit a new review."""
    try:
        spreadsheet = get_spreadsheet()
        worksheet = ensure_responses_sheet(spreadsheet)
        records = worksheet.get_all_records()
        df = pd.DataFrame(records)
        if df.empty or 'response_id' not in df.columns:
            return False

        matches = df[df['response_id'] == response_id]
        if matches.empty:
            return False

        row_index = matches.index[0] + 2  # header row offset
        worksheet.delete_rows(row_index)
        return True
    except Exception as e:
        st.error(f"Unable to delete response: {e}")
        return False


def delete_all_manager_drafts_for_employee(manager_email, employee_id, exclude_response_id=None):
    """Delete ALL draft rows for a manager+employee pair. Returns count of rows deleted.
    Pass exclude_response_id to protect one row from deletion (e.g. a draft just updated)."""
    try:
        spreadsheet = get_spreadsheet()
        worksheet = ensure_responses_sheet(spreadsheet)
        records = worksheet.get_all_records()
        df = pd.DataFrame(records)
        required_columns = {'response_id', 'status', 'manager_email', 'employee_id'}
        if df.empty or not required_columns.issubset(set(df.columns)):
            return 0

        mask = (
            (df['manager_email'].astype(str).str.strip().str.lower() == str(manager_email).strip().lower())
            & (df['employee_id'].astype(str).str.strip() == str(employee_id).strip())
            & (df['status'].astype(str).str.strip().str.lower() == 'draft')
        )
        if exclude_response_id:
            mask = mask & (df['response_id'].astype(str).str.strip() != str(exclude_response_id).strip())
        draft_rows = df[mask]
        if draft_rows.empty:
            return 0

        # Delete in reverse order so row indices stay valid after each deletion
        row_indices = sorted([i + 2 for i in draft_rows.index.tolist()], reverse=True)
        for row_index in row_indices:
            worksheet.delete_rows(row_index)
        return len(row_indices)
    except Exception as e:
        st.error(f"Unable to delete stale drafts: {e}")
        return 0


def scrape_duplicate_manager_drafts(responses_df=None):
    """
    Retroactively clean up duplicate draft rows in the Responses sheet:
    1. If a non-draft submission exists for a manager+employee pair, delete ALL
       drafts for that same pair (they are superseded).
    2. If only drafts exist for a pair, keep the latest one and delete the rest.

    Provide responses_df to reuse already-loaded data and avoid an extra read.
    Returns the total number of rows removed.
    """
    try:
        if responses_df is None:
            spreadsheet = get_spreadsheet()
            worksheet = ensure_responses_sheet(spreadsheet)
            records = worksheet.get_all_records()
            df = pd.DataFrame(records)
        else:
            df = pd.DataFrame(responses_df).copy()

        required_columns = {'response_id', 'status', 'manager_email', 'employee_id'}
        if df.empty or not required_columns.issubset(set(df.columns)):
            return 0

        sort_col = 'updated_at' if 'updated_at' in df.columns else ('created_at' if 'created_at' in df.columns else None)
        df['_sort'] = df[sort_col].astype(str) if sort_col else ''
        df['_manager_key'] = df['manager_email'].astype(str).str.strip().str.lower()
        df['_employee_key'] = df['employee_id'].astype(str).str.strip()

        is_draft = df['status'].astype(str).str.strip().str.lower() == 'draft'

        submitted_pairs = {
            (row['_manager_key'], row['_employee_key'])
            for _, row in df[~is_draft].iterrows()
            if row['_manager_key'] and row['_employee_key']
        }

        to_delete_indices = []

        drafts = df[is_draft].copy()
        if not drafts.empty:
            # Pass 1: delete all drafts for pairs that already have a submitted evaluation
            draft_pairs = list(zip(drafts['_manager_key'], drafts['_employee_key']))
            drafts_superseded = drafts[[pair in submitted_pairs for pair in draft_pairs]]
            to_delete_indices.extend(drafts_superseded.index.tolist())

            # Pass 2: for remaining drafts (no submitted evaluation yet), keep only the latest per pair
            remaining_drafts = drafts[~drafts.index.isin(to_delete_indices)].copy()
            if not remaining_drafts.empty:
                remaining_drafts = remaining_drafts.sort_values('_sort', ascending=False)
                seen = set()
                for idx, row in remaining_drafts.iterrows():
                    key = (row['_manager_key'], row['_employee_key'])
                    if key in seen:
                        to_delete_indices.append(idx)
                    else:
                        seen.add(key)

        if not to_delete_indices:
            return 0

        if responses_df is not None:
            spreadsheet = get_spreadsheet()
            worksheet = ensure_responses_sheet(spreadsheet)

        # Delete in reverse order so row indices stay valid after each deletion
        row_indices = sorted([i + 2 for i in to_delete_indices], reverse=True)
        for row_index in row_indices:
            worksheet.delete_rows(row_index)
        return len(row_indices)
    except Exception as e:
        st.error(f"Unable to scrape duplicate drafts: {e}")
        return 0


def create_response_entry(manager, employee, answers, comment=""):
    questions_score, number_of_nos = calculate_score_metrics(answers)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "response_id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "manager_email": manager['manager_email'],
        "manager_name": manager.get('manager_name', ""),
        "employee_id": str(employee['ID']),
        "employee_name": employee['name'],
        "employee_email": employee['email'],
        "branch": employee.get('branch', ""),
        "dept": employee.get('dept', ""),
        "job_title": employee.get('job_title', ""),
        "executive_email": employee.get('executive_email', ""),
        "questions_score": questions_score,
        "number_of_nos": number_of_nos,
        "responses": json.dumps(answers),
        "comments": comment.strip(),
        "employee_agree": "",
        "manager_agree": "",
        "executive_agree": "",
        "employee_agree_ts": "",
        "manager_agree_ts": "",
        "executive_agree_ts": "",
        "status": "Pending Employee",
        "employee_token": str(uuid.uuid4()),
        "manager_token": str(uuid.uuid4()),
        "executive_token": str(uuid.uuid4())
    }
    return entry


def create_employee_response_entry(employee, answers):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "response_id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "employee_id": str(employee['ID']),
        "employee_name": employee['name'],
        "employee_email": employee['email'],
        "branch": employee.get('branch', ""),
        "dept": employee.get('dept', ""),
        "job_title": employee.get('job_title', ""),
        "responses": json.dumps(answers),
        "status": "Submitted"
    }


def load_manager_questions():
    df = load_sheet(QUESTIONS_TAB)
    if df.empty:
        st.warning("Questions sheet is empty or missing. Please check the Google Sheet.")
    return df


def load_employee_questions():
    df = load_sheet(EMPLOYEE_QUESTIONS_TAB)
    if df.empty:
        st.warning("Employee_Questions sheet is empty or missing. Please check the Google Sheet.")
    return df


def validate_manager_credentials(managers_df, email, password):
    if managers_df.empty:
        return False, "", "Managers sheet is missing or empty. Please add manager email and password records."

    email_column, password_column, manager_name_column = get_manager_sheet_columns(managers_df)

    if not email_column or not password_column:
        return False, "", "Managers sheet must include email (or manager_email) and password columns."

    normalized_email = str(email).strip().lower()
    normalized_password = str(password)

    manager_matches = managers_df[
        managers_df[email_column].astype(str).str.strip().str.lower() == normalized_email
    ]

    if manager_matches.empty:
        return False, "", "Manager email not found in the Managers sheet."

    manager_row = manager_matches.iloc[0]
    stored_password = str(manager_row.get(password_column, ""))

    if normalized_password != stored_password:
        return False, "", "Incorrect manager password."

    manager_name = str(manager_row.get(manager_name_column, "")).strip() if manager_name_column else ""
    manager_name = manager_name or normalized_email
    return True, manager_name, ""


def validate_executive_credentials(executives_df, email, password):
    if executives_df.empty:
        return False, "", "Executives sheet is missing or empty. Please add executive email and password records."

    email_column, password_column = get_executive_sheet_columns(executives_df)

    if not email_column or not password_column:
        return False, "", "Executives sheet must include executive_email (or email) and password columns."

    normalized_email = str(email).strip().lower()
    normalized_password = str(password)

    executive_matches = executives_df[
        executives_df[email_column].astype(str).str.strip().str.lower() == normalized_email
    ]

    if executive_matches.empty:
        return False, "", "Executive email not found in the Executives sheet."

    executive_row = executive_matches.iloc[0]
    stored_password = str(executive_row.get(password_column, ""))

    if normalized_password != stored_password:
        return False, "", "Incorrect executive password."

    return True, normalized_email, ""


def parse_response_blob(response_blob):
    try:
        return json.loads(response_blob) if isinstance(response_blob, str) else response_blob
    except Exception:
        return {}


def normalize_employee_question_type(question_type):
    normalized = str(question_type).strip().lower().replace("-", " ")
    return "three_line" if normalized == "three line" else "multi_line"


def employee_answer_complete(answer):
    if isinstance(answer, list):
        return any(str(line).strip() for line in answer)
    return bool(str(answer).strip())


def ensure_employee_answer_shape(question_type, answer):
    if normalize_employee_question_type(question_type) == "three_line":
        if isinstance(answer, list):
            values = [str(item) for item in answer[:3]]
        else:
            values = []
        values.extend([""] * (3 - len(values)))
        return values[:3]
    return str(answer or "")


def prepare_employee_questions(question_rows):
    prepared_questions = question_rows.fillna("").copy().reset_index(drop=True)

    if 'question_section' not in prepared_questions.columns:
        prepared_questions['question_section'] = ""

    if 'ID' not in prepared_questions.columns:
        prepared_questions['ID'] = ""

    id_counts = prepared_questions['ID'].astype(str).str.strip().value_counts()
    id_occurrences = {}
    response_keys = []

    for row_index, raw_id in enumerate(prepared_questions['ID'].astype(str).str.strip()):
        base_id = raw_id or f"row_{row_index + 1}"
        id_occurrences[base_id] = id_occurrences.get(base_id, 0) + 1

        if raw_id and id_counts.get(raw_id, 0) == 1:
            response_key = raw_id
        else:
            response_key = f"{base_id}__{id_occurrences[base_id]}"

        response_keys.append(response_key)

    prepared_questions['_response_key'] = response_keys
    return prepared_questions


def render_employee_question_inputs(question_rows, key_prefix, initial_answers=None, read_only=False):
    answers = {}
    prepared_questions = prepare_employee_questions(question_rows)
    initial_answers = initial_answers or {}

    grouped_sections = prepared_questions.groupby('question_section', dropna=False, sort=False)

    for section_name, section_rows in grouped_sections:
        if section_name:
            st.markdown(f"#### {section_name}")

        for _, question in section_rows.iterrows():
            question_id = str(question['ID'])
            response_key = str(question['_response_key'])
            question_type = normalize_employee_question_type(question.get('type', ''))

            stored_value = initial_answers.get(response_key)
            if stored_value is None:
                stored_value = initial_answers.get(question_id, [] if question_type == "three_line" else "")
            value = ensure_employee_answer_shape(question.get('type', ''), stored_value)

            st.markdown(f"**{question['question']}**")
            if question_type == "three_line":
                line_values = []
                for line_number, line_value in enumerate(value, start=1):
                    widget_key = f"{key_prefix}_{response_key}_line_{line_number}"
                    if widget_key not in st.session_state:
                        st.session_state[widget_key] = line_value
                    line_values.append(
                        st.text_input(
                            f"Line {line_number}",
                            key=widget_key,
                            disabled=read_only
                        )
                    )
                answers[response_key] = line_values
            else:
                widget_key = f"{key_prefix}_{response_key}"
                if widget_key not in st.session_state:
                    st.session_state[widget_key] = value
                answers[response_key] = st.text_area(
                    "Response",
                    key=widget_key,
                    height=120,
                    disabled=read_only,
                    label_visibility='collapsed'
                )
            st.divider()

    return answers


def display_employee_response(question_rows, answers, key_prefix, read_only=True):
    prepared_questions = prepare_employee_questions(question_rows)

    grouped_sections = prepared_questions.groupby('question_section', dropna=False, sort=False)

    for section_name, section_rows in grouped_sections:
        if section_name:
            st.markdown(f"#### {section_name}")

        for _, question in section_rows.iterrows():
            question_id = str(question['ID'])
            response_key = str(question['_response_key'])
            question_type = normalize_employee_question_type(question.get('type', ''))
            stored_value = answers.get(response_key)
            if stored_value is None:
                stored_value = answers.get(question_id, [] if question_type == "three_line" else "")

            value = ensure_employee_answer_shape(question.get('type', ''), stored_value)

            st.markdown(f"**{question['question']}**")
            if question_type == "three_line":
                for line_number, line_value in enumerate(value, start=1):
                    st.text_input(
                        f"Line {line_number}",
                        value=line_value,
                        disabled=read_only,
                        key=f"{key_prefix}_{response_key}_line_{line_number}"
                    )
            else:
                st.text_area(
                    "Response",
                    value=value,
                    height=120,
                    disabled=read_only,
                    label_visibility='collapsed',
                    key=f"{key_prefix}_{response_key}"
                )
            st.divider()


def format_compact_employee_answer(question_type, answer):
    value = ensure_employee_answer_shape(question_type, answer)
    if isinstance(value, list):
        cleaned_lines = [str(item).strip() for item in value if str(item).strip()]
        return " | ".join(cleaned_lines) if cleaned_lines else "(No response)"

    text_value = str(value).strip()
    return text_value if text_value else "(No response)"


def display_employee_response_compact(question_rows, answers):
    prepared_questions = prepare_employee_questions(question_rows)
    compact_rows = []

    for _, question in prepared_questions.iterrows():
        question_id = str(question['ID'])
        response_key = str(question['_response_key'])
        question_type = question.get('type', '')

        stored_value = answers.get(response_key)
        if stored_value is None:
            stored_value = answers.get(question_id, [] if normalize_employee_question_type(question_type) == "three_line" else "")

        compact_rows.append(
            {
                "Section": str(question.get('question_section', '')).strip() or "General",
                "Question": str(question.get('question', '')).strip(),
                "Response": format_compact_employee_answer(question_type, stored_value)
            }
        )

    if compact_rows:
        st.dataframe(pd.DataFrame(compact_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No self-evaluation answers available to display.")


def reset_login_state():
    st.session_state.logged_in = False
    st.session_state.user_role = ''
    st.session_state.manager_email = ''
    st.session_state.manager_name = ''
    st.session_state.executive_email = ''
    st.session_state.employee_email = ''
    st.session_state.employee_name = ''

# ============================================================================
# APPROVAL WORKFLOW
# ============================================================================

def get_stage_links(response):
    approve_link = None
    reject_link = None
    if response['status'] == 'Pending Employee':
        approve_link = build_action_link(response['response_id'], response['employee_token'], 'employee_approve')
        reject_link = build_action_link(response['response_id'], response['employee_token'], 'employee_reject')
    elif response['status'] == 'Pending Manager':
        approve_link = build_action_link(response['response_id'], response['manager_token'], 'manager_approve')
        reject_link = build_action_link(response['response_id'], response['manager_token'], 'manager_reject')
    elif response['status'] == 'Pending Executive':
        approve_link = build_action_link(response['response_id'], response['executive_token'], 'executive_approve')
        reject_link = build_action_link(response['response_id'], response['executive_token'], 'executive_reject')
    return approve_link, reject_link


def send_stage_email(response, stage):
    try:
        answers = parse_response_blob(response['responses'])
    except Exception:
        answers = {}

    question_rows = load_manager_questions()
    questions_for_email = get_question_rows_for_answers(question_rows, answers)

    approve_link, reject_link = get_stage_links(response)
    stage_label = {
        'employee': 'Employee Verification',
        'manager': 'Manager Approval',
        'executive': 'Executive Approval'
    }.get(stage, stage)

    subject = f"Leader Level Balanced Score Card - {stage_label}"
    
    # Create employee object from response data for email formatting
    employee = {
        'name': response.get('employee_name', ''),
        'ID': response.get('employee_id', ''),
        'branch': response.get('branch', ''),
        'dept': response.get('dept', ''),
        'job_title': response.get('job_title', '')
    }
    
    body = format_email_body(subject, employee, questions_for_email, answers, stage, approve_link, reject_link, response.get('comments', ''))
    recipient = ''

    if stage == 'employee':
        recipient = response.get('employee_email', '')
    elif stage == 'manager':
        recipient = response.get('manager_email', '')
    elif stage == 'executive':
        recipient = response.get('executive_email', '')
    else:
        recipient = response.get('manager_email', '')

    # Only send email if recipient is valid
    if recipient and '@' in recipient:
        success = send_email(subject, body, recipient, sender_email=response.get('manager_email', ''))
        return success, recipient, body
    else:
        # No valid recipient, return success=False but don't show error for missing executive emails
        return False, recipient, body


def get_pending_stage_from_status(status):
    status_key = str(status).strip().lower()
    stage_map = {
        'pending employee': 'employee',
        'pending manager': 'manager',
        'pending executive': 'executive'
    }
    return stage_map.get(status_key)


def resend_pending_stage_email(response):
    stage = get_pending_stage_from_status(response.get('status', ''))
    if not stage:
        return False, '', 'Resend is only available while a scorecard is pending approval.'

    sent, recipient, _ = send_stage_email(response, stage)
    if sent:
        return True, recipient, ''

    if recipient and '@' in str(recipient):
        return False, recipient, 'Email delivery failed. SMTP may not be configured.'

    role_name = stage.title()
    return False, recipient, f"No valid {role_name} recipient email is configured for this scorecard."


def send_rejection_notice_to_manager(response, rejected_by_role, rejected_by_name, rejection_comment):
    """Notify manager that the review was rejected and removed for resubmission."""
    recipient = response.get('manager_email', '')
    if not recipient or '@' not in recipient:
        return False, recipient

    app_url = get_app_url()
    subject = "Leader Level Balanced Score Card - Rejected and Reset"
    body = [f"<h2>{subject}</h2>"]
    body.append("<p>The balanced score card below was rejected and has been removed.</p>")
    body.append(f"<p><strong>Rejected By:</strong> {rejected_by_name} ({rejected_by_role})</p>")
    body.append(f"<p><strong>Employee:</strong> {response.get('employee_name', '')} ({response.get('employee_id', '')})</p>")
    body.append(f"<p><strong>Manager:</strong> {response.get('manager_name', '')} ({response.get('manager_email', '')})</p>")

    if rejection_comment.strip():
        body.append("<p><strong>Rejection Comments:</strong></p>")
        body.append(
            f"<blockquote style='border-left:4px solid #A80000;padding-left:10px;margin:10px 0;font-style:italic;'>{rejection_comment.strip()}</blockquote>"
        )

    if app_url:
        body.append(f"<p>Please return to the app and submit a new review: <a href=\"{app_url}\">{app_url}</a></p>")
    else:
        body.append("<p>Please return to the app and submit a new review.</p>")

    success = send_email(subject, "".join(body), recipient, sender_email=response.get('manager_email', ''))
    return success, recipient


def send_self_evaluation_reminder_email(employee, manager_name, manager_email):
    recipient = str(employee.get('email', '')).strip()
    if not recipient or '@' not in recipient:
        return False, recipient, ""

    app_url = get_app_url()
    subject = "Action Required: Complete your self-evaluation"
    body = [
        "<h2>Self-evaluation required</h2>",
        f"<p>Hello {employee.get('name', 'Employee')},</p>",
        f"<p>{manager_name} is ready to complete your balanced score card review, but your self-evaluation has not been submitted yet.</p>",
        "<p>Please log in to the Leader Level Balanced Score Card app using your employee email and submit your self-evaluation.</p>",
        "<p><a href=\"https://drive.google.com/file/d/1ZboHZAlHWBv-2eqPiTEaBtqygg-9qRya/view?usp=sharing\">Learn more about YMCA Leadership Competencies here!</a></p>"
    ]

    if app_url:
        body.append(f"<p><a href=\"{app_url}\" style=\"background:#006B6B;color:white;padding:10px 14px;text-decoration:none;border-radius:4px;\">Open the App</a></p>")
        body.append(f"<p>Direct link: <a href=\"{app_url}\">{app_url}</a></p>")
    else:
        body.append("<p>Please contact your manager for the app link.</p>")

    body.append("<p>Thank you.</p>")

    success = send_email(
        subject,
        "".join(body),
        recipient,
        sender_email=manager_email,
        require_sender=True
    )
    return success, recipient, app_url


def get_employees_missing_self_evaluation(employees_df, employee_responses_df):
    if employees_df.empty:
        return employees_df

    if employee_responses_df.empty or 'employee_email' not in employee_responses_df.columns:
        return employees_df.copy()

    submitted_emails = set(
        employee_responses_df['employee_email']
        .astype(str)
        .str.strip()
        .str.lower()
    )

    return employees_df[
        ~employees_df['email'].astype(str).str.strip().str.lower().isin(submitted_emails)
    ].copy()


def process_action(action, response_id, token):
    try:
        response, _, _ = find_response_by_id(response_id)
        if not response:
            st.error("Approval record not found. Please check that the link is correct and the record exists.")
            return

        rejector_map = {
            'employee_reject': ('Employee', response.get('employee_name', 'Employee')),
            'manager_reject': ('Manager', response.get('manager_name', response.get('manager_email', 'Manager'))),
            'executive_reject': ('Executive', response.get('executive_email', 'Executive'))
        }

        rejection_comment = ""
        if action in rejector_map:
            role_label, rejector_name = rejector_map[action]
            st.warning(f"You are rejecting this score card as {role_label}.")
            rejection_comment = st.text_area(
                "Please provide a rejection comment (required):",
                key=f"reject_comment_{response_id}_{action}",
                height=120
            )
            if not st.button("Submit Rejection", type='primary', key=f"submit_reject_{response_id}_{action}"):
                return
            if not rejection_comment.strip():
                st.error("A rejection comment is required.")
                return

        valid = False
        stage_email = None
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updates = {"updated_at": now}

        if action == 'employee_approve' and response['status'] == 'Pending Employee' and token == response.get('employee_token'):
            valid = True
            updates['employee_agree'] = 'Yes'
            updates['employee_agree_ts'] = now
            updates['status'] = 'Pending Manager'
            stage_email = 'manager'
        elif action == 'employee_reject' and response['status'] == 'Pending Employee' and token == response.get('employee_token'):
            valid = True
            updates['employee_agree'] = 'No'
            updates['employee_agree_ts'] = now
            updates['status'] = 'Rejected by Employee'
        elif action == 'manager_approve' and (response['status'] == 'Pending Employee' or response['status'] == 'Pending Manager') and token == response.get('manager_token'):
            valid = True
            updates['manager_agree'] = 'Yes'
            updates['manager_agree_ts'] = now
            if response['status'] == 'Pending Employee':
                # If employee hasn't responded yet, mark as manager-approved and pending executive
                updates['status'] = 'Pending Executive'
            else:
                # If employee already approved, just move to executive
                updates['status'] = 'Pending Executive'
            stage_email = 'executive'
        elif action == 'manager_reject' and (response['status'] == 'Pending Employee' or response['status'] == 'Pending Manager') and token == response.get('manager_token'):
            valid = True
            updates['manager_agree'] = 'No'
            updates['manager_agree_ts'] = now
            updates['status'] = 'Rejected by Manager'
        elif action == 'executive_approve' and response['status'] == 'Pending Executive' and token == response.get('executive_token'):
            valid = True
            updates['executive_agree'] = 'Yes'
            updates['executive_agree_ts'] = now
            updates['status'] = 'Approved'
            # No stage_email for final approval
        elif action == 'executive_reject' and response['status'] == 'Pending Executive' and token == response.get('executive_token'):
            valid = True
            updates['executive_agree'] = 'No'
            updates['executive_agree_ts'] = now
            updates['status'] = 'Rejected by Executive'

        if not valid:
            st.error("This approval link is invalid or the action is not allowed.")
            return

        if action in rejector_map:
            role_label, rejector_name = rejector_map[action]
            deleted = delete_response(response_id)
            if not deleted:
                st.error("Unable to reset this review after rejection. Please contact support.")
                return

            sent, recipient = send_rejection_notice_to_manager(response, role_label, rejector_name, rejection_comment)
            st.success("Thank you. The scorecard was rejected and removed so a new review can be submitted.")
            if sent:
                st.info(f"Manager notification sent to {recipient}.")
            else:
                st.warning("Could not send manager notification email. Please notify the manager manually.")
            return

        if update_response(response_id, updates):
            st.success("Thank you. The scorecard status has been updated.")
            if stage_email:
                sent, recipient, body = send_stage_email({**response, **updates}, stage_email)
                if sent:
                    st.info(f"Notification email sent to {recipient}.")
                else:
                    if recipient and '@' in recipient:
                        st.info("Email could not be sent. Please use the app URL or email preview instead.")
                    else:
                        st.info("No email recipient configured for this stage.")
        else:
            st.error("Unable to update the response record. Please try again or contact support.")
    except Exception as e:
        st.error(f"An error occurred while processing the approval: {e}")
        st.info("Please try again or contact support if the issue persists.")

# ============================================================================
# MAIN UI
# ============================================================================

st.title("Leader Level Balanced Score Card")

# Check if secrets are configured
if "gcp_service_account" not in st.secrets:
    st.error("Google service account credentials not configured.")
    st.info("**Setup Required:**")
    st.info("1. Create a Google Cloud service account and download the JSON key")
    st.info("2. Share your Google Sheet with the service account email")
    st.info("3. Add the credentials to `.streamlit/secrets.toml`")
    st.info("See README.md for detailed setup instructions.")
    st.stop()

query_params = st.query_params
action = query_params.get('action')
response_id = query_params.get('response_id')
token = query_params.get('token')
debug_mode = query_params.get('debug') == 'connection'

if action and response_id and token:
    st.info("Processing approval link...")
    process_action(action, response_id, token)
    st.stop()

# Debug mode bypasses login and shows all data
if debug_mode:
    st.session_state.logged_in = True
    st.session_state.user_role = 'manager'
    st.session_state.manager_email = 'debug@mode.com'
    st.session_state.manager_name = 'Debug User'

if 'logged_in' not in st.session_state:
    reset_login_state()
    st.session_state.data_loaded = False

if 'user_role' not in st.session_state:
    st.session_state.user_role = ''

if 'employee_email' not in st.session_state:
    st.session_state.employee_email = ''

if 'employee_name' not in st.session_state:
    st.session_state.employee_name = ''

if 'executive_email' not in st.session_state:
    st.session_state.executive_email = ''

if 'managers_df' not in st.session_state:
    st.session_state.managers_df = load_sheet(MANAGERS_TAB)

if 'executives_df' not in st.session_state:
    st.session_state.executives_df = load_sheet(EXECUTIVES_TAB)

if 'last_data_sync_ts' not in st.session_state:
    st.session_state.last_data_sync_ts = 0.0

if 'sync_notice' not in st.session_state:
    st.session_state.sync_notice = ""

sync_interval_minutes = get_data_sync_minutes()
sync_age_seconds = time.time() - float(st.session_state.get('last_data_sync_ts', 0.0))
if st.session_state.data_loaded and sync_age_seconds >= sync_interval_minutes * 60:
    clear_data_caches()
    st.session_state.data_loaded = False

if not st.session_state.data_loaded:
    with st.spinner("Loading data..."):
        sync_session_data()

if not st.session_state.logged_in:
    manager_col, employee_col = st.columns(2)

    with manager_col:
        st.subheader("Manager Login")
        manager_login_email = st.text_input(
            "Enter your manager email:",
            placeholder="manager@example.com",
            key='manager_login_email'
        ).strip().lower()
        manager_login_password = st.text_input(
            "Enter your manager password:",
            type="password",
            key='manager_login_password'
        )
        if st.button("Login as Manager", type='primary'):
            if not manager_login_email:
                st.error("Please enter your manager email.")
            elif not manager_login_password:
                st.error("Please enter your manager password.")
            else:
                is_valid_manager, manager_name, manager_error = validate_manager_credentials(
                    st.session_state.get('managers_df', pd.DataFrame()),
                    manager_login_email,
                    manager_login_password
                )
                if is_valid_manager:
                    st.session_state.logged_in = True
                    st.session_state.user_role = 'manager'
                    st.session_state.manager_email = manager_login_email
                    st.session_state.manager_name = manager_name
                    st.session_state.employee_email = ''
                    st.session_state.employee_name = ''
                    st.rerun()
                else:
                    st.error(manager_error)

    with employee_col:
        st.subheader("Employee Login")
        employee_login_email = st.text_input(
            "Enter your employee email:",
            placeholder="employee@example.com",
            key='employee_login_email'
        ).strip().lower()
        if st.button("Login as Employee", type='primary'):
            employee_emails = st.session_state.employees_df['email'].astype(str).str.lower().values
            if employee_login_email and employee_login_email in employee_emails:
                employee_row = st.session_state.employees_df[
                    st.session_state.employees_df['email'].astype(str).str.lower() == employee_login_email
                ].iloc[0]
                st.session_state.logged_in = True
                st.session_state.user_role = 'employee'
                st.session_state.employee_email = employee_login_email
                st.session_state.employee_name = employee_row.get('name', employee_login_email)
                st.session_state.manager_email = ''
                st.session_state.manager_name = ''
                st.rerun()
            else:
                st.error("Employee email not found. Please enter an email listed in the Employees sheet.")

    st.divider()
    st.subheader("Executive Login")
    executive_login_email = st.text_input(
        "Enter your executive email:",
        placeholder="executive@example.com",
        key='executive_login_email'
    ).strip().lower()
    executive_login_password = st.text_input(
        "Enter your executive password:",
        type="password",
        key='executive_login_password'
    )

    if st.button("Login as Executive", type='primary'):
        if not executive_login_email:
            st.error("Please enter your executive email.")
        elif not executive_login_password:
            st.error("Please enter your executive password.")
        else:
            is_valid_executive, executive_email, executive_error = validate_executive_credentials(
                st.session_state.get('executives_df', pd.DataFrame()),
                executive_login_email,
                executive_login_password
            )
            if is_valid_executive:
                st.session_state.logged_in = True
                st.session_state.user_role = 'executive'
                st.session_state.executive_email = executive_email
                st.session_state.manager_email = ''
                st.session_state.manager_name = ''
                st.session_state.employee_email = ''
                st.session_state.employee_name = ''
                st.rerun()
            else:
                st.error(executive_error)

    st.stop()

if st.session_state.user_role == 'manager':
    sidebar_identity = f"{st.session_state.manager_name} ({st.session_state.manager_email})"
elif st.session_state.user_role == 'executive':
    sidebar_identity = st.session_state.executive_email
else:
    sidebar_identity = f"{st.session_state.employee_name} ({st.session_state.employee_email})"

st.sidebar.markdown(f"**Signed in as:** {sidebar_identity}")
st.sidebar.caption(f"Role: {st.session_state.user_role.title()}")
st.sidebar.caption(f"Auto-sync: every {sync_interval_minutes} minute(s)")

if st.sidebar.button("Sync Data from Google Sheets Now"):
    clear_data_caches()
    st.session_state.data_loaded = False
    st.session_state.sync_notice = "Data synced from Google Sheets."
    st.rerun()

if st.session_state.get('sync_notice'):
    st.sidebar.success(st.session_state.sync_notice)
    st.session_state.sync_notice = ""

if st.sidebar.button("Logout"):
    reset_login_state()
    st.rerun()

if st.session_state.user_role == 'manager':
    if debug_mode:
        manager_employees = st.session_state.employees_df
    else:
        manager_employees = st.session_state.employees_df[
            st.session_state.employees_df['manager_email'].astype(str).str.lower() == st.session_state.manager_email
        ]

    responses_df = load_responses()
    responses_df['employee_id'] = responses_df['employee_id'].astype(str)

    manager_has_responses = not responses_df[
        responses_df['manager_email'].astype(str).str.lower() == st.session_state.manager_email
    ].empty if not debug_mode else True

    if not debug_mode and manager_employees.empty and not manager_has_responses:
        st.warning("Manager email not found in the Employees sheet.")
        st.info("You can still view scorecard statuses for any scorecards you've submitted.")

    employee_self_responses_df = load_employee_responses()

    st.subheader("Manager Dashboard")

    if st.session_state.manager_email == PASSWORD_ADMIN_EMAIL:
        st.markdown("### Manager Password Administration")
        st.caption("This action emails the current password in the Managers sheet to each manager.")
        if render_mass_email_confirmation(
            "manager_passwords_admin",
            "Email All Manager Passwords",
            "Are you sure you want to email manager passwords to all managers?"
        ):
            sent_count, failed_emails, admin_error = email_all_manager_passwords(
                st.session_state.get('managers_df', pd.DataFrame())
            )
            if admin_error:
                st.error(admin_error)
            elif failed_emails:
                st.warning(f"Sent {sent_count} manager password emails. Failed: {', '.join(failed_emails)}")
            else:
                st.success(f"Sent manager password emails to {sent_count} managers.")

        st.markdown("### Draft Cleanup Administration")
        st.caption("Run this only when needed to remove stale duplicate drafts in the Responses sheet.")
        if render_mass_email_confirmation(
            "cleanup_duplicate_manager_drafts",
            "Cleanup Duplicate Drafts",
            "Are you sure you want to run duplicate draft cleanup now?"
        ):
            with st.spinner("Cleaning duplicate drafts..."):
                removed_count = scrape_duplicate_manager_drafts(responses_df=responses_df)

            if removed_count > 0:
                st.success(f"Removed {removed_count} duplicate draft rows.")
                clear_data_caches()
                st.rerun()
            else:
                st.info("No duplicate drafts found.")
        st.divider()

    tab_new, tab_status, tab_self_eval = st.tabs(["Submit Scorecard", "Scorecard Status", "Employee Self-Evaluations"])

    with tab_new:
        st.markdown("### Submit a new balanced score card")
        can_submit = True

        if debug_mode and manager_employees.empty:
            st.info("No employees found matching current filters.")
            can_submit = False
        elif not debug_mode and manager_employees.empty:
            st.info("You don't have any employees assigned as a manager in the system.")
            st.info("You can still view the status of any scorecards you've submitted using the Scorecard Status tab.")
            can_submit = False

        if can_submit:
            reviewed_employee_ids = set()
            if not responses_df.empty:
                if debug_mode:
                    submitted_responses = responses_df[
                        responses_df['status'].astype(str).str.strip().str.lower() != 'draft'
                    ]
                    reviewed_employee_ids = set(submitted_responses['employee_id'].astype(str).unique())
                else:
                    manager_submissions = responses_df[
                        responses_df['manager_email'].astype(str).str.lower() == st.session_state.manager_email
                    ]
                    manager_submissions = manager_submissions[
                        manager_submissions['status'].astype(str).str.strip().str.lower() != 'draft'
                    ]
                    reviewed_employee_ids = set(manager_submissions['employee_id'].astype(str).unique())

            if debug_mode:
                available_employees = st.session_state.employees_df[
                    ~st.session_state.employees_df['ID'].astype(str).isin(reviewed_employee_ids)
                ]
            else:
                available_employees = manager_employees[
                    ~manager_employees['ID'].astype(str).isin(reviewed_employee_ids)
                ]

            if available_employees.empty:
                if debug_mode:
                    st.success("All employees in the system have been reviewed.")
                else:
                    st.success("All employees under your supervision have been reviewed.")
                can_submit = False

        if can_submit:
            selected_employee_id = st.selectbox(
                "Select employee to rate",
                available_employees['ID'].astype(str).tolist(),
                format_func=lambda eid: f"{available_employees[available_employees['ID'].astype(str) == eid].iloc[0]['name']} ({eid})"
            )

            missing_self_eval_employees = get_employees_missing_self_evaluation(
                available_employees,
                employee_self_responses_df
            )

            st.markdown("### Bulk reminder emails")
            if missing_self_eval_employees.empty:
                st.info("All employees who still need a scorecard already submitted their self-evaluation.")
            else:
                st.caption(
                    f"{len(missing_self_eval_employees)} employees under you still need to submit a self-evaluation before their scorecard can be completed."
                )
                if render_mass_email_confirmation(
                    "send_bulk_self_eval_reminders",
                    "Send Reminder Emails to All Incomplete Employees",
                    "Are you sure you want to email all incomplete employees?"
                ):
                    sent_recipients = []
                    failed_recipients = []
                    app_url_hint = ""

                    with st.spinner("Sending reminder emails..."):
                        for _, employee_row in missing_self_eval_employees.iterrows():
                            sent, recipient, app_url = send_self_evaluation_reminder_email(
                                employee_row,
                                st.session_state.manager_name,
                                st.session_state.manager_email
                            )
                            if app_url and not app_url_hint:
                                app_url_hint = app_url
                            if sent:
                                sent_recipients.append(recipient)
                            else:
                                failed_recipients.append(recipient or str(employee_row.get('name', 'Unknown employee')))

                    if sent_recipients:
                        st.success(f"Sent {len(sent_recipients)} reminder emails.")

                    if failed_recipients:
                        st.warning(f"Could not send {len(failed_recipients)} reminder emails.")
                        st.write("Failed recipients:")
                        for recipient in failed_recipients[:10]:
                            st.write(f"- {recipient}")
                        if len(failed_recipients) > 10:
                            st.write(f"- ... and {len(failed_recipients) - 10} more")

                    if failed_recipients and app_url_hint:
                        st.info("Share this app link with employees if email is unavailable:")
                        st.code(app_url_hint)

                    if failed_recipients and not app_url_hint:
                        st.info("Set app.url in Streamlit secrets so reminder emails can include a direct link.")

            st.divider()

            selected_employee = available_employees[available_employees['ID'].astype(str) == selected_employee_id].iloc[0]
            selected_employee_email = str(selected_employee.get('email', '')).strip().lower()
            selected_draft = get_latest_manager_draft_response(
                responses_df,
                st.session_state.manager_email,
                selected_employee_id
            )
            selected_draft_answers = parse_response_blob(selected_draft.get('responses', {})) if selected_draft else {}
            selected_draft_comment = str(selected_draft.get('comments', '')) if selected_draft else ''

            selected_employee_self_eval = get_latest_employee_response_for_email(
                employee_self_responses_df,
                selected_employee_email
            )

            if selected_draft:
                st.info("A saved draft exists for this employee. Update it or submit it when ready.")

            st.write(f"Employee: {selected_employee['name']} | Branch: {selected_employee.get('branch', '')} | Dept: {selected_employee.get('dept', '')}")
            st.write(f"Title: {selected_employee.get('job_title', '')} | Executive: {selected_employee.get('executive_email', '')}")
            st.divider()

            st.markdown("### Employee Self-Evaluation")
            employee_questions_df = load_employee_questions()

            if selected_employee_self_eval:
                st.success("Self-evaluation submitted. You can proceed with manager review.")
                if employee_questions_df.empty:
                    st.info("Employee questions are not configured, so the self-evaluation detail cannot be rendered.")
                else:
                    show_selected_self_eval = st.toggle(
                        "Show employee self-evaluation",
                        value=False,
                        key=f"manager_toggle_self_eval_{selected_employee_id}"
                    )
                    if show_selected_self_eval:
                        display_employee_response_compact(
                            employee_questions_df,
                            parse_response_blob(selected_employee_self_eval.get('responses', {}))
                        )
            else:
                st.warning("This employee has not submitted a self-evaluation yet. Manager review is disabled until they submit one.")
                reminder_button_key = f"send_self_eval_reminder_{selected_employee_id}"
                if st.button("Send Self-Evaluation Reminder Email", key=reminder_button_key):
                    sent, recipient, app_url = send_self_evaluation_reminder_email(
                        selected_employee,
                        st.session_state.manager_name,
                        st.session_state.manager_email
                    )
                    if sent:
                        st.success(f"Reminder email sent to {recipient}.")
                    else:
                        st.warning("Could not send reminder email. SMTP may not be configured.")
                        if app_url:
                            st.info("Share this app link with the employee:")
                            st.code(app_url)
                        else:
                            st.info("Set app.url in Streamlit secrets so a direct login link can be included.")

            if selected_employee_self_eval:
                questions_df = prepare_9box_questions(st.session_state.questions_df, selected_employee)
                if questions_df.empty:
                    st.warning("No 9-box questions were found for this employee role. Check the Questions sheet role mapping and required columns.")
                else:
                    questions_df = questions_df.fillna("")
                    answers = {}
                    questions_df['question_section'] = questions_df['question_section'].astype(str).fillna('').str.strip()
                    grouped_sections = questions_df.groupby('question_section', dropna=False, sort=False)

                    selected_employee_state_key = "manager_selected_employee_for_form"
                    if st.session_state.get(selected_employee_state_key) != str(selected_employee_id):
                        for _, question in questions_df.iterrows():
                            question_key = str(question['ID'])
                            widget_key = f"q_{selected_employee_id}_{question['ID']}"
                            st.session_state[widget_key] = str(selected_draft_answers.get(question_key, 'No'))
                        st.session_state[f"manager_comment_{selected_employee_id}"] = selected_draft_comment
                        st.session_state[selected_employee_state_key] = str(selected_employee_id)

                    for section_name, section_rows in grouped_sections:
                        if section_name:
                            st.markdown(f"#### {section_name}")

                        for _, question in section_rows.iterrows():
                            header_text = str(question.get('header', '')).strip()
                            if header_text:
                                st.caption(header_text)

                            key = f"q_{selected_employee_id}_{question['ID']}"
                            points_value = parse_question_points(question.get('points', 0))
                            answers[str(question['ID'])] = st.radio(
                                f"{question['question']} (+{points_value} if Yes)",
                                options=['Yes', 'No'],
                                key=key
                            )
                            st.divider()

                    total_points, no_answers, yes_answers, nine_box_rating = calculate_9box_metrics(answers, questions_df)

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Points", f"{total_points}")
                    with col2:
                        st.metric("9-Box Rating", f"{nine_box_rating}")
                    with col3:
                        st.metric("Yes / No", f"{yes_answers} / {no_answers}")

                    st.caption("Scoring rule: start at 6 points, then add each question's point value for every Yes answer.")

                    st.divider()

                    st.markdown("### Additional Comments (Optional)")
                    manager_comment = st.text_area(
                        "Add any additional comments or notes about this employee:",
                        height=100,
                        placeholder="Enter your comments here...",
                        help="These comments will be included in the email sent to the employee but won't affect the score.",
                        key=f"manager_comment_{selected_employee_id}"
                    )

                    st.divider()

                    draft_col, submit_col = st.columns(2)

                    save_draft_clicked = draft_col.button("Save as Draft")
                    submit_clicked = submit_col.button("Submit Scorecard", type='primary')

                    if save_draft_clicked:
                        manager_lookup = manager_employees[
                            manager_employees['manager_email'].astype(str).str.lower() == st.session_state.manager_email
                        ]
                        manager_row = manager_lookup.iloc[0] if not manager_lookup.empty else {
                            'manager_email': st.session_state.manager_email,
                            'manager_name': st.session_state.manager_name
                        }
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        score, no_count, _, _ = calculate_9box_metrics(answers, questions_df)
                        draft_updates = {
                            'responses': json.dumps(answers),
                            'comments': manager_comment.strip(),
                            'questions_score': score,
                            'number_of_nos': no_count,
                            'status': 'Draft',
                            'updated_at': now
                        }

                        if selected_draft:
                            if update_response(selected_draft['response_id'], draft_updates):
                                # Delete any other stale drafts for this employee (keep just the updated one)
                                delete_all_manager_drafts_for_employee(
                                    st.session_state.manager_email, selected_employee_id,
                                    exclude_response_id=selected_draft['response_id']
                                )
                                st.success("Draft saved successfully.")
                                st.rerun()
                            else:
                                st.error("Unable to update draft. Please try again.")
                        else:
                            # Remove any orphaned drafts before creating the new one
                            delete_all_manager_drafts_for_employee(
                                st.session_state.manager_email, selected_employee_id
                            )
                            response_entry = create_response_entry(manager_row, selected_employee, answers, manager_comment)
                            response_entry['status'] = 'Draft'
                            response_entry['employee_agree'] = ''
                            response_entry['manager_agree'] = ''
                            response_entry['executive_agree'] = ''
                            response_entry['employee_agree_ts'] = ''
                            response_entry['manager_agree_ts'] = ''
                            response_entry['executive_agree_ts'] = ''
                            append_response(response_entry)
                            st.success("Draft saved successfully.")
                            st.rerun()

                    if submit_clicked:
                        missing = [qid for qid, value in answers.items() if value in [None, '']]
                        if missing:
                            st.error("Please answer every question before submitting.")
                        else:
                            manager_lookup = manager_employees[
                                manager_employees['manager_email'].astype(str).str.lower() == st.session_state.manager_email
                            ]
                            manager_row = manager_lookup.iloc[0] if not manager_lookup.empty else {
                                'manager_email': st.session_state.manager_email,
                                'manager_name': st.session_state.manager_name
                            }

                            score, no_count, _, _ = calculate_9box_metrics(answers, questions_df)
                            response_entry = create_response_entry(manager_row, selected_employee, answers, manager_comment)
                            response_entry['responses'] = json.dumps(answers)
                            response_entry['comments'] = manager_comment.strip()
                            response_entry['questions_score'] = score
                            response_entry['number_of_nos'] = no_count

                            submitted, response_entry, submit_error = submit_manager_scorecard(
                                response_entry,
                                selected_draft,
                                append_response,
                                delete_response,
                                delete_all_drafts=delete_all_manager_drafts_for_employee,
                            )
                            if not submitted:
                                st.error(submit_error)
                                st.stop()

                            stage_email = 'employee'
                            sent, recipient, preview = send_stage_email(response_entry, stage_email)

                            st.success("Scorecard submitted successfully.")
                            if recipient:
                                st.info(f"Verification email sent to employee: {recipient}")

                            reviewed_employee_ids = set()
                            if not responses_df.empty:
                                manager_submissions = responses_df[
                                    responses_df['manager_email'].astype(str).str.lower() == st.session_state.manager_email
                                ]
                                manager_submissions = manager_submissions[
                                    manager_submissions['status'].astype(str).str.strip().str.lower() != 'draft'
                                ]
                                reviewed_employee_ids = set(manager_submissions['employee_id'].astype(str).unique())

                            remaining_employees = []
                            for _, emp in manager_employees.iterrows():
                                if str(emp['ID']) not in reviewed_employee_ids:
                                    remaining_employees.append(f"{emp['name']} ({emp['ID']})")

                            if remaining_employees:
                                st.warning(f"{len(remaining_employees)} employees still need review:")
                                for emp in remaining_employees[:3]:
                                    st.write(f"• {emp}")
                                if len(remaining_employees) > 3:
                                    st.write(f"• ... and {len(remaining_employees) - 3} more")
                            else:
                                st.success("All employees under your supervision have been reviewed.")

                            if not sent:
                                st.warning("Email not configured. Copy approval links below and send manually:")
                                approve_link, reject_link = get_stage_links(response_entry)
                                st.code(f"Approve: {approve_link}")
                                st.code(f"Reject: {reject_link}")

                            time.sleep(3)
                            st.rerun()

    with tab_status:
        st.markdown("### Your scorecard status dashboard")
        st.caption("Track approvals and progress for scorecards you've submitted.")

        try:
            current_responses_df = load_responses()
            manager_email = st.session_state.get('manager_email', '').strip().lower()

            if current_responses_df.empty:
                st.info("No scorecards submitted yet.")
            else:
                if debug_mode:
                    manager_responses = current_responses_df.copy()
                else:
                    manager_responses = current_responses_df[
                        current_responses_df['manager_email'].astype(str).str.strip().str.lower() == manager_email
                    ].copy()

                if manager_responses.empty:
                    st.info("No scorecards found for your manager email.")
                else:
                    manager_responses = manager_responses.sort_values(['created_at'], ascending=False)

                    total_count = len(manager_responses)
                    approved_count = int((manager_responses['status'].astype(str) == 'Approved').sum())
                    pending_count = int(manager_responses['status'].astype(str).str.startswith('Pending').sum())
                    rejected_count = int(manager_responses['status'].astype(str).str.contains('Rejected').sum())

                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("Total Submitted", total_count)
                    k2.metric("Approved", approved_count)
                    k3.metric("Pending", pending_count)
                    k4.metric("Rejected", rejected_count)

                    st.markdown("#### Submission Summary")
                    summary_columns = [
                        'employee_name', 'employee_email', 'status',
                        'questions_score', 'number_of_nos', 'created_at', 'updated_at'
                    ]
                    available_summary_columns = [c for c in summary_columns if c in manager_responses.columns]
                    summary_df = manager_responses[available_summary_columns].copy()
                    summary_df = summary_df.rename(columns={
                        'employee_name': 'Employee',
                        'employee_email': 'Email',
                        'status': 'Status',
                        'questions_score': '9-Box Points',
                        'number_of_nos': 'No Answers',
                        'created_at': 'Created',
                        'updated_at': 'Updated'
                    })
                    st.dataframe(summary_df, use_container_width=True, hide_index=True)

                    st.markdown("#### Scorecard Details")
                    manager_questions_for_pdf = load_manager_questions()
                    employee_questions_for_pdf = load_employee_questions()
                    employee_responses_for_pdf = load_employee_responses()

                    for _, row in manager_responses.iterrows():
                        title = f"{row.get('employee_name', 'Unknown Employee')} • {row.get('status', '')}"
                        with st.expander(title):
                            c1, c2 = st.columns(2)
                            with c1:
                                st.write(f"9-Box points: {row.get('questions_score', '')}")
                                st.write(f"No answers: {row.get('number_of_nos', '')}")
                                st.write(f"Created: {row.get('created_at', '')}")
                            with c2:
                                st.write(f"Updated: {row.get('updated_at', '')}")
                                st.write(f"Employee: {row.get('employee_email', '')}")
                                st.write(f"Manager: {row.get('manager_email', '')}")

                            pending_stage = get_pending_stage_from_status(row.get('status', ''))
                            if pending_stage:
                                resend_button_label = f"Resend {pending_stage.title()} Email"
                                if st.button(resend_button_label, key=f"manager_resend_stage_{row.get('response_id', '')}"):
                                    sent, recipient, error_msg = resend_pending_stage_email(row)
                                    if sent:
                                        st.success(f"Resent pending-stage email to {recipient}.")
                                    else:
                                        st.warning(error_msg)

                            if str(row.get('status', '')).strip() == 'Approved':
                                employee_self_eval = get_latest_employee_response_for_email(
                                    employee_responses_for_pdf,
                                    str(row.get('employee_email', '')).strip().lower()
                                )
                                pdf_bytes = generate_scorecard_pdf(
                                    row,
                                    manager_questions_for_pdf,
                                    employee_questions_for_pdf,
                                    employee_self_eval
                                )
                                file_name = f"scorecard_{str(row.get('employee_id', 'employee')).strip()}_{str(row.get('response_id', 'response')).strip()}.pdf"
                                st.download_button(
                                    "Download Approved PDF",
                                    data=pdf_bytes,
                                    file_name=file_name,
                                    mime="application/pdf",
                                    key=f"manager_pdf_{row.get('response_id', '')}"
                                )
                            else:
                                st.caption("PDF download is available only after full approval.")
        except Exception as e:
            st.error(f"Error loading scorecard status: {e}")
            import traceback
            st.code(traceback.format_exc())

    with tab_self_eval:
        st.markdown("### Employee self-evaluations")
        st.caption("View submitted self-evaluations for employees assigned to you.")

        show_all_self_eval_details = st.toggle(
            "Show self-evaluation details",
            value=False,
            key="manager_toggle_all_self_eval_details"
        )

        if manager_employees.empty:
            st.info("No employees found for this manager.")
        elif employee_self_responses_df.empty:
            st.info("No employee self-evaluations have been submitted yet.")
        else:
            employee_questions_df = load_employee_questions()
            if employee_questions_df.empty:
                st.warning("Employee_Questions sheet is empty. Add questions to render self-evaluation details.")
            else:
                for _, manager_employee in manager_employees.iterrows():
                    employee_name = manager_employee.get('name', 'Unknown Employee')
                    employee_id = str(manager_employee.get('ID', ''))
                    employee_email = str(manager_employee.get('email', '')).strip().lower()

                    self_eval = get_latest_employee_response_for_email(employee_self_responses_df, employee_email)
                    title_suffix = "Submitted" if self_eval else "Not Submitted"

                    with st.expander(f"{employee_name} ({employee_id}) • {title_suffix}"):
                        st.write(f"Email: {manager_employee.get('email', '')}")
                        if not self_eval:
                            st.info("No self-evaluation submitted.")
                        else:
                            st.write(f"Last updated: {self_eval.get('updated_at', self_eval.get('created_at', ''))}")
                            if show_all_self_eval_details:
                                display_employee_response_compact(
                                    employee_questions_df,
                                    parse_response_blob(self_eval.get('responses', {}))
                                )
elif st.session_state.user_role == 'executive':
    st.subheader("Executive Dashboard")

    responses_df = load_responses()
    responses_df['employee_id'] = responses_df['employee_id'].astype(str)
    employees_df = st.session_state.employees_df.copy()

    executive_email = st.session_state.get('executive_email', '').strip().lower()

    executive_branches = set(
        employees_df[
            employees_df['executive_email'].astype(str).str.strip().str.lower() == executive_email
        ]['branch'].astype(str).str.strip()
    )
    executive_branches = {branch for branch in executive_branches if branch}

    branch_responses = responses_df[
        responses_df['branch'].astype(str).str.strip().isin(executive_branches)
    ].copy() if executive_branches else pd.DataFrame(columns=responses_df.columns)

    if branch_responses.empty:
        branch_responses = responses_df[
            responses_df['executive_email'].astype(str).str.strip().str.lower() == executive_email
        ].copy()

    total_count = len(branch_responses)
    approved_count = int((branch_responses['status'].astype(str) == 'Approved').sum()) if total_count else 0
    pending_count = int(branch_responses['status'].astype(str).str.startswith('Pending').sum()) if total_count else 0
    rejected_count = int(branch_responses['status'].astype(str).str.contains('Rejected').sum()) if total_count else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Scorecards", total_count)
    k2.metric("Approved", approved_count)
    k3.metric("Pending", pending_count)
    k4.metric("Rejected", rejected_count)

    if executive_branches:
        st.caption(f"Branch scope: {', '.join(sorted(executive_branches))}")
    else:
        st.caption("No branch assignment found. Showing scorecards tied directly to your executive email.")

    st.markdown("### Branch Status View")
    if branch_responses.empty:
        st.info("No scorecards found for your executive scope.")
    else:
        branch_responses = branch_responses.sort_values(['created_at'], ascending=False)
        st.dataframe(
            branch_responses[[
                'employee_name', 'employee_email', 'branch', 'manager_email',
                'status', 'questions_score', 'created_at', 'updated_at'
            ]],
            use_container_width=True,
            hide_index=True
        )

        manager_questions_for_pdf = load_manager_questions()
        employee_questions_for_pdf = load_employee_questions()
        employee_responses_for_pdf = load_employee_responses()

        st.markdown("### Scorecard Details")
        for _, row in branch_responses.iterrows():
            with st.expander(f"{row.get('employee_name', 'Unknown Employee')} ({row.get('employee_id', '')}) • {row.get('status', '')}"):
                st.write(f"Manager: {row.get('manager_name', '')} ({row.get('manager_email', '')})")
                st.write(f"Branch: {row.get('branch', '')} | Dept: {row.get('dept', '')}")
                st.write(f"9-Box points: {row.get('questions_score', '')} | No answers: {row.get('number_of_nos', '')}")
                st.write(f"Employee approval: {row.get('employee_agree', '')} at {row.get('employee_agree_ts', '')}")
                st.write(f"Manager approval: {row.get('manager_agree', '')} at {row.get('manager_agree_ts', '')}")
                st.write(f"Executive approval: {row.get('executive_agree', '')} at {row.get('executive_agree_ts', '')}")

                pending_stage = get_pending_stage_from_status(row.get('status', ''))
                if pending_stage:
                    resend_button_label = f"Resend {pending_stage.title()} Email"
                    if st.button(resend_button_label, key=f"executive_resend_stage_{row.get('response_id', '')}"):
                        sent, recipient, error_msg = resend_pending_stage_email(row)
                        if sent:
                            st.success(f"Resent pending-stage email to {recipient}.")
                        else:
                            st.warning(error_msg)

                if str(row.get('status', '')).strip() == 'Approved':
                    employee_self_eval = get_latest_employee_response_for_email(
                        employee_responses_for_pdf,
                        str(row.get('employee_email', '')).strip().lower()
                    )
                    pdf_bytes = generate_scorecard_pdf(
                        row,
                        manager_questions_for_pdf,
                        employee_questions_for_pdf,
                        employee_self_eval
                    )
                    file_name = f"scorecard_{str(row.get('employee_id', 'employee')).strip()}_{str(row.get('response_id', 'response')).strip()}.pdf"
                    st.download_button(
                        "Download Approved PDF",
                        data=pdf_bytes,
                        file_name=file_name,
                        mime="application/pdf",
                        key=f"executive_pdf_{row.get('response_id', '')}"
                    )
                else:
                    st.caption("PDF download is available only after full approval.")

    st.divider()
    st.markdown("### Missing Scorecard Notifications")

    missing_by_manager_branch = get_missing_scorecards_by_manager(
        employees_df,
        responses_df,
        executive_branches if executive_branches else None
    )

    if missing_by_manager_branch:
        missing_employee_total = sum(len(items) for items in missing_by_manager_branch.values())
        st.caption(
            f"{len(missing_by_manager_branch)} managers are missing {missing_employee_total} employee scorecards in your scope."
        )
        if render_mass_email_confirmation(
            "executive_branch_missing_reviews",
            "Email All Managers Missing Reviews In My Scope",
            "Are you sure you want to email every manager in your scope who is missing scorecards?"
        ):
            sent_count, failed_emails = email_managers_with_missing_scorecards(missing_by_manager_branch)
            if failed_emails:
                st.warning(f"Sent {sent_count} manager notifications. Failed: {', '.join(failed_emails)}")
            else:
                st.success(f"Sent notifications to {sent_count} managers.")
    else:
        st.info("No missing scorecards found in your scope.")

    if executive_email == EXECUTIVE_ADMIN_EMAIL:
        st.divider()
        st.markdown("### Executive Administration")

        if render_mass_email_confirmation(
            "executive_passwords_admin",
            "Email Executive Passwords to All Executives",
            "Are you sure you want to email passwords to all executives?"
        ):
            sent_count, failed_emails, admin_error = email_all_executive_passwords(
                st.session_state.get('executives_df', pd.DataFrame())
            )
            if admin_error:
                st.error(admin_error)
            elif failed_emails:
                st.warning(f"Sent {sent_count} executive password emails. Failed: {', '.join(failed_emails)}")
            else:
                st.success(f"Sent executive password emails to {sent_count} executives.")

        missing_by_manager_global = get_missing_scorecards_by_manager(employees_df, responses_df)
        if missing_by_manager_global:
            if render_mass_email_confirmation(
                "executive_global_missing_reviews",
                "Email All Managers Everywhere Missing Reviews",
                "Are you sure you want to email all managers everywhere who are missing reviews?"
            ):
                sent_count, failed_emails = email_managers_with_missing_scorecards(missing_by_manager_global)
                if failed_emails:
                    st.warning(f"Sent {sent_count} global manager reminders. Failed: {', '.join(failed_emails)}")
                else:
                    st.success(f"Sent global reminders to {sent_count} managers.")
        else:
            st.info("No global manager reminders are currently needed.")
else:
    employee_row = st.session_state.employees_df[
        st.session_state.employees_df['email'].astype(str).str.lower() == st.session_state.employee_email
    ]

    st.subheader("Employee Dashboard")

    if employee_row.empty:
        st.error("Employee email not found in the Employees sheet.")
        st.stop()

    employee_record = employee_row.iloc[0]
    st.write(f"Employee: {employee_record['name']} | Branch: {employee_record.get('branch', '')} | Dept: {employee_record.get('dept', '')}")
    st.write(f"Title: {employee_record.get('job_title', '')}")
    st.divider()

    employee_questions_df = load_employee_questions()
    manager_responses_df = load_responses()
    manager_responses_df['employee_id'] = manager_responses_df['employee_id'].astype(str)
    existing_response, _, _ = find_employee_response_by_email(st.session_state.employee_email)

    if employee_questions_df.empty:
        st.warning("The Employee_Questions sheet is empty. Please add questions to the Google Sheet.")
        st.stop()

    latest_manager_response = get_latest_manager_response_for_employee(
        manager_responses_df,
        str(employee_record['ID'])
    )
    self_eval_locked = manager_response_locks_employee_self_eval(latest_manager_response)
    manager_status = str(latest_manager_response.get('status', '')).strip() if latest_manager_response else ""

    if existing_response:
        existing_answers = parse_response_blob(existing_response.get('responses', {}))

        if self_eval_locked:
            st.markdown("### Your submitted response")
            if manager_status:
                st.caption(f"Your self-evaluation is locked because your manager scorecard is currently in status: {manager_status}.")
            else:
                st.caption("Your self-evaluation is locked because your manager scorecard has entered approval.")
            display_employee_response(
                employee_questions_df,
                existing_answers,
                key_prefix=f"employee_locked_{existing_response['response_id']}",
                read_only=True
            )
        else:
            st.markdown("### Edit your submitted response")
            st.caption("You can edit your self-evaluation until your manager scorecard enters approval.")
            editable_answers = render_employee_question_inputs(
                employee_questions_df,
                key_prefix=f"employee_edit_{existing_response['response_id']}",
                initial_answers=existing_answers,
                read_only=False
            )

            if st.button("Update Employee Response", type='primary'):
                missing_answers = [
                    question_id for question_id, answer in editable_answers.items()
                    if not employee_answer_complete(answer)
                ]

                if missing_answers:
                    st.error("Please answer every employee question before updating.")
                else:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    updated = update_employee_response(
                        existing_response['response_id'],
                        {
                            'responses': json.dumps(editable_answers),
                            'updated_at': now,
                            'status': 'Submitted'
                        }
                    )
                    if updated:
                        st.success("Your employee response has been updated.")
                        st.rerun()
                    else:
                        st.error("Unable to update your response. Please try again.")
    else:
        st.markdown("### Submit your employee response")
        st.caption("Each employee can submit one response for themselves. Your answers do not affect scorecard scoring.")
        employee_answers = render_employee_question_inputs(
            employee_questions_df,
            key_prefix=f"employee_form_{employee_record['ID']}"
        )

        if st.button("Submit Employee Response", type='primary'):
            missing_answers = [
                question_id for question_id, answer in employee_answers.items()
                if not employee_answer_complete(answer)
            ]

            if missing_answers:
                st.error("Please answer every employee question before submitting.")
            else:
                response_entry = create_employee_response_entry(employee_record, employee_answers)
                append_employee_response(response_entry)
                st.success("Your employee response has been submitted.")
                st.rerun()
