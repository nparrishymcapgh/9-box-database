# Changelog

## 2026-05-06

- Added manager-side 9-box scoring flow driven by Google Sheets Questions tab.
- Implemented role-based question filtering so managers only see questions matching employee role/job title.
- Added point-based scoring: baseline 6 points plus question points for each Yes response.
- Updated manager dashboard metrics and labels to show 9-box points and derived 9-box rating.
- Updated email scorecard summaries to include question points, total points, and 9-box rating.
- Added fallback submit helper when optional response_submission module is unavailable.
- Added repository secrets template at .streamlit/secrets.toml.
- Updated README documentation for the new Questions tab schema and 9-box scoring behavior.
