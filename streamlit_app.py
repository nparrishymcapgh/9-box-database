import json
import html
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
LEVELS_TAB = "Levels"
RESOURCE_TABS = ["Resource", "Resources"]
DEFAULT_DATA_SYNC_MINUTES = 5

# Responses sheet now stores only the fields used by the manager workflow.
MANAGER_RESPONSE_COLUMNS = [
    "response_id", "created_at", "updated_at", "manager_email", "manager_name",
    "employee_id", "employee_name", "employee_email", "location", "department",
    "job_name", "questions_score", "responses", "comments",
]

RESPONSE_COLUMN_ALIASES = {
    "response_id": ["response_id"],
    "created_at": ["created_at"],
    "updated_at": ["updated_at"],
    "manager_email": ["manager_email"],
    "manager_name": ["manager_name"],
    "employee_id": ["employee_id"],
    "employee_name": ["employee_name"],
    "employee_email": ["employee_email"],
    "location": ["location", "branch"],
    "department": ["department", "dept"],
    "job_name": ["job_name", "job_title", "role"],
    "questions_score": ["questions_score"],
    "responses": ["responses"],
    "comments": ["comments"],
}


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
        return read_worksheet_dataframe(worksheet)
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()


def load_first_available_sheet(tab_names):
    for tab_name in tab_names:
        df = load_sheet(tab_name)
        if not df.empty:
            return df
    return pd.DataFrame()


def ensure_dataframe_columns(df, expected_columns):
    if df.empty:
        return pd.DataFrame(columns=expected_columns)

    for col in expected_columns:
        if col not in df.columns:
            df[col] = ""
    return df


def normalize_responses_dataframe(df):
    if df.empty:
        return pd.DataFrame(columns=MANAGER_RESPONSE_COLUMNS)

    normalized = pd.DataFrame()
    for column in MANAGER_RESPONSE_COLUMNS:
        aliases = RESPONSE_COLUMN_ALIASES.get(column, [column])
        normalized[column] = df.apply(lambda row: get_row_value(row, aliases), axis=1)
    return normalized.fillna("")


def make_unique_headers(headers):
    normalized_headers = []
    seen_counts = {}

    for index, header in enumerate(headers, start=1):
        base_header = normalize_text(header) or f"column_{index}"
        count = seen_counts.get(base_header, 0)
        seen_counts[base_header] = count + 1
        normalized_headers.append(base_header if count == 0 else f"{base_header}_{count + 1}")

    return normalized_headers


def read_worksheet_dataframe(worksheet):
    values = worksheet.get_all_values()
    if not values:
        return pd.DataFrame()

    headers = make_unique_headers(values[0])
    data_rows = []
    expected_len = len(headers)

    for raw_row in values[1:]:
        row = list(raw_row[:expected_len])
        if len(row) < expected_len:
            row.extend([""] * (expected_len - len(row)))
        if any(normalize_text(cell) for cell in row):
            data_rows.append(row)

    return pd.DataFrame(data_rows, columns=headers)


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
    df = read_worksheet_dataframe(worksheet)
    return ensure_dataframe_columns(normalize_responses_dataframe(df), MANAGER_RESPONSE_COLUMNS)


def ensure_responses_sheet(spreadsheet):
    try:
        worksheet = spreadsheet.worksheet(RESPONSES_TAB)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(RESPONSES_TAB, rows=1000, cols=len(MANAGER_RESPONSE_COLUMNS))
        worksheet.append_row(MANAGER_RESPONSE_COLUMNS)
        return worksheet

    existing_headers = make_unique_headers(worksheet.row_values(1))
    if existing_headers != MANAGER_RESPONSE_COLUMNS:
        existing_df = read_worksheet_dataframe(worksheet)
        normalized_df = normalize_responses_dataframe(existing_df)
        rows = [MANAGER_RESPONSE_COLUMNS] + normalized_df[MANAGER_RESPONSE_COLUMNS].astype(str).values.tolist()
        worksheet.clear()
        worksheet.resize(rows=max(len(rows), 1), cols=len(MANAGER_RESPONSE_COLUMNS))
        worksheet.update(
            f"A1:{column_letter(len(MANAGER_RESPONSE_COLUMNS))}{len(rows)}",
            rows,
        )
        return worksheet

    return ensure_sheet_headers(worksheet, MANAGER_RESPONSE_COLUMNS)


def append_response(row):
    spreadsheet = get_spreadsheet()
    worksheet = ensure_responses_sheet(spreadsheet)
    headers = worksheet.row_values(1)
    ordered = [row.get(col, "") for col in headers]
    worksheet.append_row(ordered)


def delete_response(response_id):
    spreadsheet = get_spreadsheet()
    worksheet = ensure_responses_sheet(spreadsheet)
    headers = worksheet.row_values(1)
    try:
        response_id_col = headers.index("response_id") + 1
    except ValueError:
        return False

    response_ids = worksheet.col_values(response_id_col)
    target_id = normalize_text(response_id)
    for row_index, value in enumerate(response_ids[1:], start=2):
        if normalize_text(value) == target_id:
            worksheet.delete_rows(row_index)
            return True
    return False


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


def parse_level_score(value):
    text = normalize_text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def row_role_matches_question(role_cell, employee_role):
    role_cell_text = normalize_text_lower(role_cell)
    employee_role_text = normalize_text_lower(employee_role)

    if not role_cell_text:
        return True
    if not employee_role_text:
        return False

    role_tokens = [token.strip() for token in role_cell_text.replace("|", ",").split(",") if token.strip()]
    return employee_role_text in role_tokens


def get_row_value(row, candidates, default=""):
    if row is None:
        return default

    if hasattr(row, "keys"):
        keys = list(row.keys())
    elif isinstance(row, dict):
        keys = list(row.keys())
    else:
        keys = []

    lowered = {str(key).strip().lower(): key for key in keys}
    for candidate in candidates:
        actual = lowered.get(str(candidate).strip().lower())
        if actual is None:
            continue
        value = normalize_text(row.get(actual, ""))
        if value:
            return value
    return default


def get_employee_id(employee_row):
    return get_row_value(employee_row, ["ID", "id"])


def get_employee_name(employee_row):
    return get_row_value(employee_row, ["name", "employee_name"])


def get_employee_email(employee_row):
    return get_row_value(employee_row, ["email", "employee_email"])


def get_employee_role(employee_row):
    return get_row_value(employee_row, ["role", "job_name", "job_title"])


def get_employee_job_name(employee_row):
    return get_row_value(employee_row, ["job_name", "job_title", "role"])


def get_employee_location(employee_row):
    return get_row_value(employee_row, ["location", "branch"])


def get_employee_department(employee_row):
    return get_row_value(employee_row, ["department", "dept"])


def prepare_9box_questions(questions_df, employee_row):
    if questions_df.empty:
        return pd.DataFrame(columns=["ID", "question", "points", "role"])

    id_column = get_first_matching_column(questions_df, ["id"])
    points_column = get_first_matching_column(questions_df, ["points", "point", "point_value", "point_rating"])
    question_column = get_first_matching_column(questions_df, ["question", "questions", "prompt"])
    role_column = get_first_matching_column(questions_df, ["role", "employee_role", "job_title", "position", "title"])

    if not id_column or not points_column or not question_column:
        return pd.DataFrame(columns=["ID", "question", "points", "role"])

    employee_role = get_employee_role(employee_row)
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


def prepare_levels(levels_df):
    expected_columns = ["score", "performance", "potential", "name", "steps", "focus", "description"]
    if levels_df.empty:
        return pd.DataFrame(columns=expected_columns)

    score_column = get_first_matching_column(levels_df, ["score", "rating", "level", "9_box_rating", "nine_box_rating"])
    performance_column = get_first_matching_column(levels_df, ["performance"])
    potential_column = get_first_matching_column(levels_df, ["potential"])
    name_column = get_first_matching_column(levels_df, ["name", "level_name"])
    steps_column = get_first_matching_column(levels_df, ["steps", "next_steps"])
    focus_column = get_first_matching_column(levels_df, ["focus", "development_focus"])
    description_column = get_first_matching_column(levels_df, ["description", "summary"])

    if not score_column:
        return pd.DataFrame(columns=expected_columns)

    normalized = pd.DataFrame()
    normalized["score"] = levels_df[score_column].apply(parse_level_score)
    normalized["performance"] = levels_df[performance_column].astype(str).str.strip() if performance_column else ""
    normalized["potential"] = levels_df[potential_column].astype(str).str.strip() if potential_column else ""
    normalized["name"] = levels_df[name_column].astype(str).str.strip() if name_column else ""
    normalized["steps"] = levels_df[steps_column].astype(str).str.strip() if steps_column else ""
    normalized["focus"] = levels_df[focus_column].astype(str).str.strip() if focus_column else ""
    normalized["description"] = levels_df[description_column].astype(str).str.strip() if description_column else ""

    normalized = normalized.dropna(subset=["score"])
    normalized["score"] = normalized["score"].astype(int)
    normalized = normalized.drop_duplicates(subset=["score"], keep="first")
    return normalized.reset_index(drop=True)


def prepare_resources(resources_df):
    expected_columns = [
        "score",
        "resource_1_name",
        "resource_1_link",
        "resource_2_name",
        "resource_2_link",
        "resource_3_name",
        "resource_3_link",
    ]
    if resources_df.empty:
        return pd.DataFrame(columns=expected_columns)

    score_column = get_first_matching_column(resources_df, ["score", "rating", "level", "9_box_rating", "nine_box_rating"])
    if not score_column:
        return pd.DataFrame(columns=expected_columns)

    normalized = pd.DataFrame()
    normalized["score"] = resources_df[score_column].apply(parse_level_score)
    for column in expected_columns[1:]:
        source_column = get_first_matching_column(resources_df, [column])
        normalized[column] = resources_df[source_column].astype(str).str.strip() if source_column else ""

    normalized = normalized.dropna(subset=["score"])
    normalized["score"] = normalized["score"].astype(int)
    normalized = normalized.drop_duplicates(subset=["score"], keep="first")
    return normalized.reset_index(drop=True)


def get_level_details(levels_df, score):
    if levels_df.empty:
        return None

    matches = levels_df[levels_df["score"] == int(score)]
    if matches.empty:
        return None
    return matches.iloc[0]


def get_resources_for_score(resources_df, score):
    if resources_df.empty or score is None:
        return []

    matches = resources_df[resources_df["score"] == int(score)]
    if matches.empty:
        return []

    row = matches.iloc[0]
    resources = []
    for index in range(1, 4):
        name = normalize_text(row.get(f"resource_{index}_name", ""))
        link = normalize_text(row.get(f"resource_{index}_link", ""))
        if name and link:
            resources.append({"name": name, "link": link})
    return resources


def score_to_9box_rating(total_points):
    try:
        return max(1, min(9, int(float(total_points))))
    except (TypeError, ValueError):
        return None


def get_level_name(levels_df, score):
    level_details = get_level_details(levels_df, score)
    if level_details is None:
        return f"Score {score}"
    return normalize_text(level_details.get("name", "")) or f"Score {score}"


def get_manager_employee_row(manager_employees, employee_id):
    matches = manager_employees[manager_employees["ID"].astype(str).str.strip() == str(employee_id).strip()]
    if matches.empty:
        return None
    return matches.iloc[0]


def get_saved_employee_summary(saved_row, manager_employees):
    employee_id = normalize_text(saved_row.get("employee_id", ""))
    employee_row = get_manager_employee_row(manager_employees, employee_id)
    summary_row = employee_row if employee_row is not None else saved_row
    return {
        "employee_id": employee_id,
        "employee_row": employee_row,
        "employee_name": get_employee_name(summary_row) or normalize_text(saved_row.get("employee_name", "")),
        "employee_role": get_employee_role(summary_row) or normalize_text(saved_row.get("role", "")),
        "employee_job_name": get_employee_job_name(summary_row) or normalize_text(saved_row.get("job_name", saved_row.get("job_title", ""))),
        "employee_location": get_employee_location(summary_row) or normalize_text(saved_row.get("location", saved_row.get("branch", ""))),
        "employee_department": get_employee_department(summary_row) or normalize_text(saved_row.get("department", saved_row.get("dept", ""))),
    }


def build_9box_grid_cells(saved_evaluations_df, manager_employees, levels_df):
    cells = {
        score: {"score": score, "name": get_level_name(levels_df, score), "employees": []}
        for score in range(1, 10)
    }

    for _, saved_row in saved_evaluations_df.iterrows():
        score = score_to_9box_rating(parse_question_points(saved_row.get("questions_score", 0)))
        if score is None:
            continue

        employee_summary = get_saved_employee_summary(saved_row, manager_employees)
        cells[score]["employees"].append(
            {
                "name": employee_summary["employee_name"] or "Unnamed employee",
                "job_name": employee_summary["employee_job_name"],
            }
        )

    return cells


def render_9box_grid(saved_evaluations_df, manager_employees, levels_df):
    grid_order = [3, 2, 1, 6, 5, 4, 9, 8, 7]
    cells = build_9box_grid_cells(saved_evaluations_df, manager_employees, levels_df)
    cell_markup = []

    for score in grid_order:
        cell = cells[score]
        employee_markup = "".join(
            (
                f"<div class='ninebox-employee'>"
                f"<div class='ninebox-employee-name'>{html.escape(employee['name'])}</div>"
                f"<div class='ninebox-employee-role'>{html.escape(employee['job_name'] or 'Job not provided')}</div>"
                f"</div>"
            )
            for employee in cell["employees"]
        )
        empty_state = "<div class='ninebox-empty'>No employees</div>" if not employee_markup else ""
        cell_markup.append(
            f"<div class='ninebox-cell'>"
            f"<div class='ninebox-cell-header'>"
            f"<span class='ninebox-score'>{score}</span>"
            f"<span class='ninebox-level-name'>{html.escape(cell['name'])}</span>"
            f"</div>"
            f"<div class='ninebox-cell-body'>{employee_markup}{empty_state}</div>"
            f"</div>"
        )

    st.markdown(
        """
        <style>
        .ninebox-layout {
            --ninebox-text: var(--text-color, #111827);
            --ninebox-border: color-mix(in srgb, var(--ninebox-text) 28%, transparent);
            --ninebox-soft-border: color-mix(in srgb, var(--ninebox-text) 18%, transparent);
            --ninebox-muted: color-mix(in srgb, var(--ninebox-text) 76%, transparent);
            --ninebox-empty: color-mix(in srgb, var(--ninebox-text) 52%, transparent);
            --ninebox-cell-bg: var(--background-color, #ffffff);
            display: grid;
            grid-template-columns: 92px minmax(0, 1fr);
            gap: 0;
            align-items: stretch;
            margin: 1rem 0 1.5rem 0;
        }
        .ninebox-y-axis {
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--text-color, var(--ninebox-text));
            min-height: 560px;
            padding-bottom: 0;
        }
        .ninebox-y-axis-rotated {
            width: auto;
            transform: rotate(-90deg);
            transform-origin: center;
            display: block;
            text-align: center;
            white-space: pre;
        }
        .ninebox-axis-label-row {
            color: var(--text-color, var(--ninebox-text));
            font-size: 1.05rem;
            font-weight: 700;
            text-shadow: 0 0 0.01px currentColor;
        }
        .ninebox-main {
            display: flex;
            flex-direction: column;
            gap: 0.65rem;
            overflow-x: auto;
        }
        .ninebox-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.65rem;
            min-width: 720px;
        }
        .ninebox-cell {
            min-height: 182px;
            border: 1.5px solid var(--ninebox-border);
            border-radius: 14px;
            padding: 0.85rem;
            background: var(--ninebox-cell-bg);
            box-shadow: none;
        }
        .ninebox-cell-header {
            display: flex;
            align-items: center;
            gap: 0.55rem;
            margin-bottom: 0.7rem;
        }
        .ninebox-score {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 1.7rem;
            height: 1.7rem;
            padding: 0 0.35rem;
            border-radius: 999px;
            border: 1.5px solid var(--ninebox-text);
            background: transparent;
            color: var(--ninebox-text);
            font-size: 0.82rem;
            font-weight: 700;
        }
        .ninebox-level-name {
            font-size: 0.95rem;
            font-weight: 600;
            color: var(--ninebox-text);
            line-height: 1.2;
        }
        .ninebox-cell-body {
            display: flex;
            flex-direction: column;
            gap: 0.45rem;
        }
        .ninebox-employee {
            border-radius: 10px;
            border: 1px solid var(--ninebox-soft-border);
            background: transparent;
            padding: 0.45rem 0.55rem;
        }
        .ninebox-employee-name {
            color: var(--ninebox-text);
            font-size: 0.88rem;
            font-weight: 600;
            line-height: 1.2;
        }
        .ninebox-employee-role {
            color: var(--ninebox-muted);
            font-size: 0.76rem;
            margin-top: 0.15rem;
            line-height: 1.2;
        }
        .ninebox-empty {
            color: var(--ninebox-empty);
            font-size: 0.8rem;
            font-style: italic;
        }
        .ninebox-x-axis {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            align-items: center;
            color: var(--text-color, var(--ninebox-text));
            font-size: 1.05rem;
            gap: 0.65rem;
            min-width: 720px;
            font-weight: 700;
        }
        .ninebox-x-axis-center {
            text-align: center;
        }
        .ninebox-x-axis-right {
            text-align: right;
        }
        @media (max-width: 900px) {
            .ninebox-layout {
                grid-template-columns: 1fr;
            }
            .ninebox-y-axis {
                min-height: auto;
                justify-content: flex-start;
            }
            .ninebox-y-axis-rotated {
                width: 100%;
                transform: none;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <script>
        (function () {
            if (window.__nineboxThemeSyncInitialized) {
                if (typeof window.__nineboxApplyTheme === "function") {
                    window.__nineboxApplyTheme();
                }
                return;
            }

            function parseRgb(colorValue) {
                var match = (colorValue || "").match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/i);
                if (!match) {
                    return null;
                }
                return {
                    r: Number(match[1]),
                    g: Number(match[2]),
                    b: Number(match[3])
                };
            }

            function isDarkColor(colorValue) {
                var rgb = parseRgb(colorValue);
                if (!rgb) {
                    return false;
                }
                var luminance = (0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b) / 255;
                return luminance < 0.5;
            }

            function applyTheme() {
                var appRoot = document.querySelector('.stApp') || document.body;
                var layouts = document.querySelectorAll('.ninebox-layout');
                if (!appRoot || !layouts.length) {
                    return;
                }

                var styles = window.getComputedStyle(appRoot);
                var appText = styles.color || '#111827';
                var appBg = styles.backgroundColor || '#ffffff';
                var dark = isDarkColor(appBg);

                layouts.forEach(function (layout) {
                    layout.style.setProperty('--ninebox-text', appText);
                    layout.style.setProperty('--ninebox-cell-bg', dark ? '#000000' : '#ffffff');
                });
            }

            window.__nineboxApplyTheme = applyTheme;
            window.__nineboxThemeSyncInitialized = true;
            applyTheme();

            var observer = new MutationObserver(applyTheme);
            observer.observe(document.documentElement, {
                subtree: true,
                attributes: true,
                attributeFilter: ['class', 'style', 'data-theme']
            });

            window.addEventListener('resize', applyTheme);
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        (
            "<div class='ninebox-layout'>"
            "<div class='ninebox-y-axis'>"
            "<div class='ninebox-y-axis-rotated ninebox-axis-label-row'>Low&#9;&#9;&#9;&#9;&#9;&#9;&#9;Potential &rarr;&#9;&#9;&#9;&#9;&#9;&#9;&#9;High</div>"
            "</div>"
            "<div class='ninebox-main'>"
            f"<div class='ninebox-grid'>{''.join(cell_markup)}</div>"
            "<div class='ninebox-x-axis'>"
            "<div class='ninebox-axis-label-row'>Low</div>"
            "<div class='ninebox-x-axis-center'>Performance &rarr;</div>"
            "<div class='ninebox-axis-label-row ninebox-x-axis-right'>High</div>"
            "</div>"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def get_existing_employee_evaluation(responses_df, manager_email, employee_id):
    if responses_df.empty:
        return None

    matches = responses_df[
        (responses_df["manager_email"].astype(str).str.strip().str.lower() == normalize_text_lower(manager_email))
        & (responses_df["employee_id"].astype(str).str.strip() == str(employee_id).strip())
    ].copy()

    if matches.empty:
        return None

    matches = matches.sort_values("created_at", ascending=False)
    return matches.iloc[0]


def parse_saved_answers(raw_value):
    text = normalize_text(raw_value)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def render_level_summary(level_details, score_label, score_value):
    score_col = st.columns(1)[0]
    score_col.metric(score_label, f"{score_value}")
    name_col, performance_col, potential_col = st.columns(3)
    name_col.metric("Level", level_details.get("name", "") if level_details is not None else "")
    performance_col.metric(
        "Performance",
        level_details.get("performance", "") if level_details is not None else "",
    )
    potential_col.metric(
        "Potential",
        level_details.get("potential", "") if level_details is not None else "",
    )


def render_resources(resources):
    if not resources:
        return

    st.markdown("**Resources**")
    for resource in resources:
        st.markdown(f"- [{resource['name']}]({resource['link']})")


def render_saved_evaluation_details(saved_row, levels_df, resources_df, question_rows=None):
    saved_total_points = parse_question_points(saved_row.get("questions_score", 0))
    saved_score = score_to_9box_rating(saved_total_points)
    level_details = get_level_details(levels_df, saved_score) if saved_score is not None else None
    resources = get_resources_for_score(resources_df, saved_score)

    render_level_summary(level_details, "Score", saved_score or "")
    st.caption(f"Saved: {saved_row.get('created_at', '')}")

    if normalize_text(saved_row.get("comments", "")):
        st.markdown(f"**Manager comments:** {saved_row.get('comments', '')}")

    if level_details is not None:
        if normalize_text(level_details.get("description", "")):
            st.markdown(f"**Description:** {level_details.get('description', '')}")
        if normalize_text(level_details.get("focus", "")):
            st.markdown(f"**Focus:** {level_details.get('focus', '')}")
        if normalize_text(level_details.get("steps", "")):
            st.markdown(f"**Steps:** {level_details.get('steps', '')}")

    render_resources(resources)

    if question_rows is not None and not question_rows.empty:
        saved_answers = parse_saved_answers(saved_row.get("responses", ""))
        if saved_answers:
            with st.expander("Questions and responses", expanded=False):
                for _, question in question_rows.iterrows():
                    question_id = str(question.get("ID", "")).strip()
                    prompt = str(question.get("question", "")).strip()
                    answer = saved_answers.get(question_id, "")
                    st.markdown(
                        f"<div style='font-size:0.9rem; margin-bottom:0.35rem;'><strong>{prompt}</strong><br>{answer}</div>",
                        unsafe_allow_html=True,
                    )


def calculate_9box_metrics(answers, question_rows, base_points=8):
    points_lookup = {
        str(row.get("ID", "")).strip(): parse_question_points(row.get("points", 0))
        for _, row in question_rows.iterrows()
    }

    yes_points = 0

    for question_id, answer in answers.items():
        normalized = normalize_text_lower(answer)
        if normalized == "yes":
            yes_points += points_lookup.get(str(question_id).strip(), 0)

    total_points = base_points + yes_points
    nine_box_rating = max(1, min(9, total_points))
    return total_points, nine_box_rating


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
    total_points, _ = metrics
    employee_id = get_employee_id(employee)
    employee_name = get_employee_name(employee)
    employee_email = get_employee_email(employee)
    employee_location = get_employee_location(employee)
    employee_department = get_employee_department(employee)
    employee_job_name = get_employee_job_name(employee)
    return {
        "response_id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "manager_email": manager_email,
        "manager_name": manager_name,
        "employee_id": employee_id,
        "employee_name": employee_name,
        "employee_email": employee_email,
        "location": employee_location,
        "department": employee_department,
        "job_name": employee_job_name,
        "questions_score": total_points,
        "responses": json.dumps(answers),
        "comments": comments.strip(),
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
    st.session_state.levels_df = prepare_levels(load_sheet(LEVELS_TAB))
    st.session_state.resources_df = prepare_resources(load_first_available_sheet(RESOURCE_TABS))
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

if "submission_message" not in st.session_state:
    st.session_state.submission_message = ""

if "submission_message_type" not in st.session_state:
    st.session_state.submission_message_type = "success"

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
manager_employees = manager_employees.sort_values("name").copy()

if manager_employees.empty:
    st.warning("No employees are assigned to this manager email in the Employees sheet.")
    st.stop()

pending_manager_employees = manager_employees[
    manager_employees.apply(
        lambda row: get_existing_employee_evaluation(responses_df, manager_email, get_employee_id(row)) is None,
        axis=1,
    )
].copy()

if st.session_state.submission_message:
    if st.session_state.submission_message_type == "success":
        st.success(st.session_state.submission_message)
    elif st.session_state.submission_message_type == "warning":
        st.warning(st.session_state.submission_message)
    else:
        st.info(st.session_state.submission_message)
    st.session_state.submission_message = ""
    st.session_state.submission_message_type = "success"

tab_submit, tab_status = st.tabs(["9 Box Evaluation", "Submitted 9 Box Evaluations"])

with tab_submit:
    st.markdown("### Complete 9 Box Evaluation")

    levels_df = st.session_state.get("levels_df", pd.DataFrame())
    resources_df = st.session_state.get("resources_df", pd.DataFrame())
    if pending_manager_employees.empty:
        st.success("All assigned employees have been reviewed. You're good to go.")
    else:
        employee = pending_manager_employees.iloc[0]
        employee_id = get_employee_id(employee)
        employee_name = get_employee_name(employee)
        employee_role = get_employee_role(employee)
        employee_location = get_employee_location(employee)
        employee_department = get_employee_department(employee)

        st.info(
            f"Next employee in line: {employee_name}"
            f" | Role: {employee_role or 'Not provided'}"
            f" | Location: {employee_location or 'Not provided'}"
            f" | Department: {employee_department or 'Not provided'}"
        )
        st.caption(
            f"Remaining evaluations including this one: {len(pending_manager_employees)} "
            f"of {len(manager_employees)} assigned employees"
        )

        scoped_questions = prepare_9box_questions(st.session_state.questions_df, employee)
        if scoped_questions.empty:
            st.warning(
                "No matching questions found for this employee role. "
                "Questions tab must include columns: ID, points, question, role."
            )
        else:
            answers = {}
            for _, question in scoped_questions.iterrows():
                qid = str(question.get("ID", "")).strip()
                prompt = str(question.get("question", "")).strip()
                answers[qid] = st.radio(prompt, options=["Yes", "No"], key=f"q_{employee_id}_{qid}")

            total_points, nine_box_rating = calculate_9box_metrics(answers, scoped_questions)
            level_details = get_level_details(levels_df, nine_box_rating)
            comments = st.text_area("Manager comments (optional)", height=120, key=f"comments_{employee_id}")

            st.divider()
            render_level_summary(level_details, "Score", nine_box_rating)

            if st.button("Submit Rating", type="primary", key=f"submit_{employee_id}"):
                latest_responses = load_responses()
                duplicate = get_existing_employee_evaluation(
                    latest_responses,
                    st.session_state.manager_email,
                    employee_id,
                )
                if duplicate is not None:
                    st.session_state.submission_message = f"{employee_name} already has a saved evaluation. Delete it to redo the evaluation."
                    st.session_state.submission_message_type = "warning"
                    st.rerun()

                entry = create_response_entry(
                    st.session_state.manager_email,
                    st.session_state.manager_name,
                    employee,
                    answers,
                    comments,
                    (total_points, nine_box_rating),
                )
                append_response(entry)
                clear_data_caches()
                st.session_state.data_loaded = False
                st.session_state.submission_message = f"Saved evaluation for {employee_name}."
                st.session_state.submission_message_type = "success"
                st.rerun()

with tab_status:
    st.markdown("### Submitted 9 Box Evaluations")
    mine = responses_df[
        responses_df["manager_email"].astype(str).str.strip().str.lower() == manager_email
    ].copy()

    if mine.empty:
        st.info("No ratings submitted yet.")
    else:
        mine = mine.sort_values("created_at", ascending=False)
        levels_df = st.session_state.get("levels_df", pd.DataFrame())
        resources_df = st.session_state.get("resources_df", pd.DataFrame())

        st.markdown("#### 9 Box Grid")
        render_9box_grid(mine, manager_employees, levels_df)

        for _, saved_row in mine.iterrows():
            employee_summary = get_saved_employee_summary(saved_row, manager_employees)
            employee_id = employee_summary["employee_id"]
            employee_name = employee_summary["employee_name"]
            employee_role = employee_summary["employee_role"]
            employee_location = employee_summary["employee_location"]
            employee_department = employee_summary["employee_department"]
            label = (
                f"{employee_name}"
                f" | Role: {employee_role or 'Not provided'}"
                f" | Location: {employee_location or 'Not provided'}"
                f" | Department: {employee_department or 'Not provided'}"
            )

            question_rows = pd.DataFrame()
            if employee_summary["employee_row"] is not None:
                question_rows = prepare_9box_questions(st.session_state.questions_df, employee_summary["employee_row"])

            with st.expander(label):
                st.write(
                    f"Employee: {employee_name} | Role: {employee_role or 'Not provided'} | "
                    f"Location: {employee_location or 'Not provided'} | "
                    f"Department: {employee_department or 'Not provided'}"
                )
                render_saved_evaluation_details(saved_row, levels_df, resources_df, question_rows)
                if st.button("Delete and start over", key=f"status_delete_{saved_row.get('response_id', employee_id)}"):
                    deleted = delete_response(saved_row.get("response_id", ""))
                    clear_data_caches()
                    st.session_state.data_loaded = False
                    if deleted:
                        st.session_state.submission_message = f"Deleted saved evaluation for {employee_name}."
                        st.session_state.submission_message_type = "success"
                    else:
                        st.session_state.submission_message = f"Could not delete saved evaluation for {employee_name}."
                        st.session_state.submission_message_type = "warning"
                    st.rerun()
