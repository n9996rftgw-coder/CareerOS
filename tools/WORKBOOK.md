# Local tracker export

The workbook is a local CSV snapshot. It does not fetch from or publish to Google Sheets. Check the live canonical Sheet before relying on a local count.

Build it from the CareerOS directory:

```sh
.runtime/venv/bin/python build_sheet.py . exports/CareerOS_Tracker.xlsx
```

For the calculation fixtures and all five sheet previews:

```sh
.runtime/venv/bin/python build_sheet.py . exports/CareerOS_Tracker.xlsx --self-test --preview-dir exports/.verification
```

The Python wrapper reads the current schema, dropdown choices and CSV rows from `careeros.tracker`, then sends that data to `tools/build_tracker.mjs`. The bundled `@oai/artifact-tool` authors the workbook. `node_modules` must point to the Codex bundled packages; no repository packages are installed or needed. `CAREEROS_NODE` can identify another compatible Codex bundled Node executable.

The export retains Dashboard, Applications, Network, Targets and Lists. Data columns follow the tracker schema. First response and interview dates preserve history when a role later moves to rejected or withdrawn. Existing current response/interview statuses provide a disclosed legacy fallback only when the corresponding first date is blank. Every sent metric requires Date Applied. Blank and invalid dates do not create follow-up counts. Next IDs use the greatest existing numeric ID plus one. Formula and dropdown ranges reserve at least 1,000 additional records and expand on every rebuild.

Workbook edits do not automatically change the local CSVs or the live Sheet. Preserve the local and live records until an explicit reconciliation has been checked.

The fixtures test submission evidence, history after status changes, missing and invalid dates, maturity cutoffs, gapped IDs, the next appended row and recalculation after a cell edit. Previews and XML checks verify the local export. They do not establish behaviour in native Microsoft Excel or Google Sheets.
