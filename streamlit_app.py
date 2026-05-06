import json
import time
import uuid
from datetime import datetime

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials


# ============================================================================
# PAGE CONFIG
# ============================================================================
st.set_page_config(
    page_title="Succession Planning",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================================
# GOOGLE SHEETS CONFIG
# ============================================================================
GOOGLE_SHEET_ID = "14sMvqP4OevZoJcvk5eGuxjDlQkSr-BQUk78_6f_MrVI"
EMPLOYEES_TAB = "Employees"
QUESTIONS_TAB = "Questions"
RESPONSES_TAB = "Responses"
MANAGERS_TAB = "Managers"
DEFAULT_DATA_SYNC_MINUTES = 5

# Keep legacy response columns for compatibility with existing sheet data.
MANAGER_RESPONSE_COLUMNS = [
    "response_id", "created_at", "updated_at", "manager_email", "manager_name",
    "employee_id", "employee_name", "employee_email", "branch", "dept",
    "job_title", "executive_email", "questions_score", "number_of_nos",
    "responses", "comments", "employee_agree", "manager_agree", "executive_agree",
    "employee_agree_ts", "manager_agree_ts", "executive_agree_ts",
    "status", "employee_token", "manager_token", "executive_token",
]


# ============================================================================
# SHEETS UTILITIES
# ============================================================================
@st.cache_resource
def get_spreadsheet():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        client = gspread.authorize(creds)
        return client.open_by_key(GOOGLE_SHEET_ID)
    except KeyError:
        st.error("Google service account credentials not configured.")
        st.info("Add [gcp_service_account] to .streamlit/secrets.toml or Streamlit Cloud secrets.")
        st.stop()
    except Exception as exc:
        st.error(f"Error connecting to Google Sheets: {exc}")
        st.stop()


@st.cache_data(ttl=300)
def load_sheet(tab_name):
    spreadsheet = get_spreadsheet()
    try:
        worksheet = spreadsheet.worksheet(tab_name)
        return pd.DataFrame(worksheet.get_all_records())
    except gspread.exceptions.WorksheetNotFound:
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


@st.cache_data(ttl=300)
def load_responses():
    spreadsheet = get_spreadsheet()
    worksheet = ensure_responses_sheet(spreadsheet)
    df = pd.DataFrame(worksheet.get_all_records())
    return ensure_dataframe_columns(df, MANAGER_RESPONSE_COLUMNS)


def ensure_responses_sheet(spreadsheet):
    try:
        worksheet = spreadsheet.worksheet(RESPONSES_TAB)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(RESPONSES_TAB, rows=1000, cols=len(MANAGER_RESPONSE_COLUMNS))
        worksheet.append_row(MANAGER_RESPONSE_COLUMNS)
        return worksheet
    return ensure_sheet_headers(worksheet, MANAGER_RESPONSE_COLUMNS)


def append_response(row):
    spreadsheet = get_spreadsheet()
    worksheet = ensure_responses_sheet(spreadsheet)
    headers = worksheet.row_values(1)
    ordered = [row.get(col, "") for col in headers]
    worksheet.append_row(ordered)


# ============================================================================
# BUSINESS LOGIC
# ============================================================================
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
    return employee_role_text in role_tokens


def prepare_9box_questions(questions_df, employee_row):
    if questions_df.empty:
        return pd.DataFrame(columns=["ID", "question", "points", "role"])

    id_column = get_first_matching_column(questions_df, ["id"])
    points_column = get_first_matching_column(questions_df, ["points", "point", "point_value", "point_rating"])
    question_column = get_first_matching_column(questions_df, ["question", "questions", "prompt"])
    role_column = get_first_matching_column(questions_df, ["role", "employee_role", "job_title", "position", "title"])

    if not id_column or not points_column or not question_column:
        return pd.DataFrame(columns=["ID", "question", "points", "role"])

    employee_role = employee_row.get("role", employee_row.get("job_title", ""))
    scoped = questions_df.copy()
    if role_column:
        scoped = scoped[scoped[role_column].apply(lambda cell: row_role_matches_question(cell, employee_role))].copy()

    if scoped.empty:
        return pd.DataFrame(columns=["ID", "question", "points", "role"])

    scoped = scoped.fillna("")
    normalized = pd.DataFrame()
    normalized["ID"] = scoped[id_column].astype(str).str.strip()
    normalized["points"] = scoped[points_column].apply(parse_question_points)
    normalized["question"] = scoped[question_column].astype(str).str.strip()
    normalized["role"] = scoped[role_column].astype(str).str.strip() if role_column else ""

    normalized = normalized[normalized["ID"] != ""]
    normalized = normalized[normalized["question"] != ""]
    return normalized.reset_index(drop=True)


def calculate_9box_metrics(answers, question_rows, base_points=6):
    points_lookup = {
        str(row.get("ID", "")).strip(): parse_question_points(row.get("points", 0))
        for _, row in question_rows.iterrows()
    }

    yes_points = 0
    yes_count = 0
    no_count = 0

    for question_id, answer in answers.items():
        normalized = normalize_text_lower(answer)
        if normalized == "yes":
            yes_count += 1
            yes_points += points_lookup.get(str(question_id).strip(), 0)
        elif normalized == "no":
            no_count += 1

    total_points = base_points + yes_points
    nine_box_rating = max(1, min(9, total_points))
    return total_points, yes_count, no_count, nine_box_rating


def get_manager_sheet_columns(managers_df):
    normalized = {str(col).strip().lower(): col for col in managers_df.columns}
    email_column = normalized.get("manager_email") or normalized.get("email")
    password_column = normalized.get("password")
    manager_name_column = normalized.get("manager_name")
    return email_column, password_column, manager_name_column


def validate_manager_credentials(managers_df, email, password):
    if managers_df.empty:
        return False, "", "Managers sheet is missing or empty."

    email_column, password_column, manager_name_column = get_manager_sheet_columns(managers_df)
    if not email_column or not password_column:
        return False, "", "Managers sheet must include email (or manager_email) and password columns."

    normalized_email = normalize_text_lower(email)
    matches = managers_df[managers_df[email_column].astype(str).str.strip().str.lower() == normalized_email]
    if matches.empty:
        return False, "", "Manager email not found in Managers sheet."

    row = matches.iloc[0]
    if str(row.get(password_column, "")) != str(password):
        return False, "", "Incorrect manager password."

    manager_name = normalize_text(row.get(manager_name_column, "")) if manager_name_column else ""
    manager_name = manager_name or normalized_email
    return True, manager_name, ""


def create_response_entry(manager_email, manager_name, employee, answers, comments, metrics):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_points, _, no_count, _ = metrics
    return {
        "response_id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "manager_email": manager_email,
        "manager_name": manager_name,
        "employee_id": str(employee.get("ID", "")),
        "employee_name": str(employee.get("name", "")),
        "employee_email": str(employee.get("email", "")),
        "branch": str(employee.get("branch", "")),
        "dept": str(employee.get("dept", "")),
        "job_title": str(employee.get("job_title", "")),
        "executive_email": "",
        "questions_score": total_points,
        "number_of_nos": no_count,
        "responses": json.dumps(answers),
        "comments": comments.strip(),
        "employee_agree": "",
        "manager_agree": "",
        "executive_agree": "",
        "employee_agree_ts": "",
        "manager_agree_ts": "",
        "executive_agree_ts": "",
        "status": "Submitted",
        "employee_token": "",
        "manager_token": "",
        "executive_token": "",
    }


def get_data_sync_minutes():
    raw = st.secrets.get("app", {}).get("data_sync_minutes", DEFAULT_DATA_SYNC_MINUTES)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_DATA_SYNC_MINUTES


def clear_data_caches():
    load_sheet.clear()
    load_responses.clear()


def sync_session_data():
    st.session_state.employees_df = load_sheet(EMPLOYEES_TAB)
    st.session_state.questions_df = load_sheet(QUESTIONS_TAB)
    st.session_state.managers_df = load_sheet(MANAGERS_TAB)
    st.session_state.responses_df = load_responses()
    st.session_state.data_loaded = True
    st.session_state.last_data_sync_ts = time.time()


# ============================================================================
# APP UI
# ============================================================================
st.title("Succession Planning")

if "gcp_service_account" not in st.secrets:
    st.error("Google service account credentials not configured.")
    st.info("Add [gcp_service_account] in .streamlit/secrets.toml or Streamlit Cloud secrets.")
    st.stop()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.manager_email = ""
    st.session_state.manager_name = ""
    st.session_state.data_loaded = False

if "last_data_sync_ts" not in st.session_state:
    st.session_state.last_data_sync_ts = 0.0

sync_interval_minutes = get_data_sync_minutes()
sync_age_seconds = time.time() - float(st.session_state.get("last_data_sync_ts", 0.0))
if st.session_state.data_loaded and sync_age_seconds >= sync_interval_minutes * 60:
    clear_data_caches()
    st.session_state.data_loaded = False

if not st.session_state.data_loaded:
    with st.spinner("Loading data..."):
        sync_session_data()

if not st.session_state.logged_in:
    st.subheader("Manager Login")
    manager_email = st.text_input("Email", placeholder="manager@example.com").strip().lower()
    manager_password = st.text_input("Password", type="password")

    if st.button("Login", type="primary"):
        ok, manager_name, error_text = validate_manager_credentials(
            st.session_state.get("managers_df", pd.DataFrame()),
            manager_email,
            manager_password,
        )
        if ok:
            st.session_state.logged_in = True
            st.session_state.manager_email = manager_email
            st.session_state.manager_name = manager_name
            st.rerun()
        else:
            st.error(error_text)
    st.stop()

st.sidebar.markdown(f"**Signed in as:** {st.session_state.manager_name} ({st.session_state.manager_email})")
st.sidebar.caption("Role: Manager")
st.sidebar.caption(f"Auto-sync: every {sync_interval_minutes} minute(s)")

if st.sidebar.button("Sync Data"):
    clear_data_caches()
    st.session_state.data_loaded = False
    st.rerun()

if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.session_state.manager_email = ""
    st.session_state.manager_name = ""
    st.rerun()

employees_df = st.session_state.employees_df.copy()
responses_df = load_responses()
manager_email = st.session_state.manager_email

if employees_df.empty:
    st.warning("Employees sheet is empty.")
    st.stop()

manager_employees = employees_df[
    employees_df["manager_email"].astype(str).str.strip().str.lower() == manager_email
].copy()

if manager_employees.empty:
    st.warning("No employees are assigned to this manager email in the Employees sheet.")
    st.stop()

tab_submit, tab_status = st.tabs(["Submit 9-Box Rating", "Submitted Ratings"])

with tab_submit:
    st.markdown("### Submit a 9-box rating")

    selected_employee_id = st.selectbox(
        "Select employee",
        manager_employees["ID"].astype(str).tolist(),
        format_func=lambda eid: f"{manager_employees[manager_employees['ID'].astype(str) == eid].iloc[0]['name']} ({eid})",
    )

    selected_employee = manager_employees[manager_employees["ID"].astype(str) == selected_employee_id].iloc[0]
    st.write(
        f"Employee: {selected_employee.get('name', '')} | "
        f"Branch: {selected_employee.get('branch', '')} | "
        f"Dept: {selected_employee.get('dept', '')} | "
        f"Title: {selected_employee.get('job_title', '')}"
    )

    scoped_questions = prepare_9box_questions(st.session_state.questions_df, selected_employee)
    if scoped_questions.empty:
        st.warning(
            "No matching questions found for this employee role. "
            "Questions tab must include columns: ID, points, question, role."
        )
        st.stop()

    answers = {}
    for _, question in scoped_questions.iterrows():
        qid = str(question.get("ID", ""))
        points_value = parse_question_points(question.get("points", 0))
        prompt = f"{question.get('question', '')} (+{points_value} if Yes)"
        answers[qid] = st.radio(prompt, options=["Yes", "No"], key=f"q_{selected_employee_id}_{qid}")

    total_points, yes_count, no_count, nine_box_rating = calculate_9box_metrics(answers, scoped_questions)

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Points", f"{total_points}")
    m2.metric("9-Box Rating", f"{nine_box_rating}")
    m3.metric("Yes / No", f"{yes_count} / {no_count}")
    st.caption("Scoring: start at 6 points, add question points for each Yes answer.")

    comments = st.text_area("Manager comments (optional)", height=120)

    if st.button("Submit Rating", type="primary"):
        entry = create_response_entry(
            st.session_state.manager_email,
            st.session_state.manager_name,
            selected_employee,
            answers,
            comments,
            (total_points, yes_count, no_count, nine_box_rating),
        )
        append_response(entry)
        clear_data_caches()
        st.success("9-box rating submitted.")
        st.rerun()

with tab_status:
    st.markdown("### Your submitted ratings")
    mine = responses_df[
        responses_df["manager_email"].astype(str).str.strip().str.lower() == manager_email
    ].copy()

    if mine.empty:
        st.info("No ratings submitted yet.")
    else:
        mine = mine.sort_values("created_at", ascending=False)
        display_cols = [
            "employee_name", "employee_id", "branch", "dept", "job_title",
            "questions_score", "number_of_nos", "status", "created_at", "updated_at",
        ]
        available = [c for c in display_cols if c in mine.columns]
        df = mine[available].rename(
            columns={
                "employee_name": "Employee",
                "employee_id": "Employee ID",
                "branch": "Branch",
                "dept": "Dept",
                "job_title": "Role",
                "questions_score": "Total Points",
                "number_of_nos": "No Answers",
                "status": "Status",
                "created_at": "Created",
                "updated_at": "Updated",
            }
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
