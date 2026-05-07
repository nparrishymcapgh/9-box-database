# Unreleased

- Added hierarchical team visibility so Submitted 9 Box Evaluations includes all descendants (direct and indirect reports) instead of only the current manager's direct reports.
- Limited 9 Box Evaluation submissions to direct reports only, while preserving full descendant visibility on summary/grid pages.
- Added explicit completed_by_email and completed_by_name response fields and surfaced evaluator identity in saved evaluation details and team summary.
- Added a Team Summary table on Submitted 9 Box Evaluations listing every descendant employee, relationship (direct/indirect), status, evaluator, and last saved timestamp.
- Restricted delete/start-over actions so only the manager who completed an evaluation can delete it.
- Standardized nine-box axis formatting by matching Potential to Performance styling and rotating the Potential axis 90 degrees left with a right-pointing arrow and Low-to-High labels.
- Fixed nine-box dark-mode styling so axis labels and text render in white and grid-cell fills render black for proper contrast.
- Reduced spacing on the rotated Potential axis labels for a tighter High/Potential/Low fit and expanded dark-mode detection so nine-box text and cell fills switch reliably.
- Tightened the rotated Potential Low/Potential/High spacing further to approximately half of the Performance-axis spacing.
- Reworked nine-box theming to rely on Streamlit theme variables only so text, borders, and backgrounds switch dynamically with app light/dark mode.
- Added runtime theme synchronization for the nine-box UI so grid fills and axis text follow the active app theme mode consistently.
- Reduced the Responses sheet schema to the fields used by the manager-only workflow and removed legacy executive, agreement, token, status, and no-count columns.
- Fixed the submitted-evaluations delete action crash caused by an undefined employee identifier in the expander button key.
- Restyled the nine-box grid to use theme-aware outlines, higher-contrast axis labels, and employee name plus job name in each cell.
- Added a 3x3 nine-box grid to Submitted 9 Box Evaluations so managers can see every rated employee plotted by score before the saved-evaluations list.
- Stopped storing per-response no counts and removed that legacy field from the Responses sheet schema.
- Added tolerant worksheet loading to handle blank or duplicate Google Sheets headers without crashing startup.
- Updated the manager evaluation flow to advance to the next pending employee automatically and show a completion message after all assigned employees are reviewed.
- Expanded submitted evaluation summaries to show employee role, location, and department and moved delete/start-over actions there.
- Restored the manager workflow title to Succession Planning.
- Changed 9-box scoring to start from 8 points and removed the visible base-score caption.
- Removed per-question point labels and yes-no count summaries from the manager evaluation screen.
- Added Levels sheet support and surfaced the matching level name, performance, and potential during score calculation.
- Moved full level details to Submitted 9 Box Evaluations and removed the standalone Levels tab.

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
