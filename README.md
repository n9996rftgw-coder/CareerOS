# CareerOS

An evidence-first job-search workspace, operated through chat with a local review dashboard. CareerOS connects the evidence store, applications, contacts, outreach, document versions and outcome history.

## How it works

1. Supply a job description and the latest approved CV in chat. Preserve the JD before matching it against the evidence store.
2. The assistant assesses fit and maps requirements to evidence. Unsupported capabilities remain gaps.
3. The local engine selects and orders master bullets verbatim. The assistant and candidate humanise summary and outreach wording, with evidence references and confirmation. The engine does not infer claims.
4. Review the evidence gaps and rendered layout. Draft summaries, unresolved flags, pending public clearance or unverified pagination prevent a ready result.
5. The user sends the reviewed document through Claude. There is no automatic Claude handoff or submission.
6. When configured, the assistant logs confirmed events through connected Google Sheets tools and reads the changed cells back. This is a chat-led connector workflow, not automatic local OAuth synchronisation. Local CSVs and the dashboard are snapshots of that live record.

Goals, location, sector and level are configurable in the candidate context. Examples are fictional. No background search, automatic applications, external sending or recurring schedule is installed.

## Local setup

Use Python 3.10 or later and Node.js 20 or later:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm install
.venv/bin/python examples/seed_demo.py
.venv/bin/python server.py --port 8765
```

Open the local address printed by the server. It binds to the loopback interface. The demo seeder refuses to overwrite existing files. Replace fictional evidence locally before preparing real documents.

The core runtime needs **PyYAML** and the public **docx** Node package. PDF generation and page verification additionally need **LibreOffice** and **pdfinfo**. A missing or failed page check never produces a ready-to-send result. An optional `.runtime.json` can select a Node executable and module path; see `examples/runtime.example.json`.

## Evidence and records

- `sot/master.yaml`: facts, role IDs, bullet IDs and evidence notes.
- `sot/personal_context.yaml`: goals and summary variants. A confirmed summary needs `evidence` references such as `role-01`, `education.0.award` or `profile.city`. Confirmation is human wording approval; references alone are not semantic proof.
- `data/`: application, network and target snapshots. Stable IDs, dated events and append-only activity history retain previous outcomes.
- `jobs/`, `research/`, `outputs/`, `exports/`: private intake, sourced research, immutable document revisions and spreadsheet snapshots.

The dashboard can explicitly change local records. Reconcile these with the canonical live Sheet before the next action. A local save does not establish a verified cloud write. Confirm submissions and message dates before recording them as sent.

```sh
.venv/bin/python cli.py validate
.venv/bin/python cli.py today
.venv/bin/python cli.py stats
.venv/bin/python cli.py --help
```

Validation reads records without changing them. Keyword coverage measures printed lexical overlap; it is not an ATS score or interview prediction. Supplied facts are not independently verified by the system.

## Verification

Core tests use synthetic temporary records:

```sh
.venv/bin/python -m unittest discover -s tests -p test_evidence.py
.venv/bin/python -m unittest discover -s tests -p test_tracker.py
.venv/bin/python -m unittest discover -s tests -p test_server.py
```

Workbook export and `test_workbook.py` are optional. They require the **Codex bundled `@oai/artifact-tool` runtime**, which is not supplied by this repository and should not be assumed to be installable from a public package registry. See `tools/WORKBOOK.md`. Core records, the dashboard and CV rendering do not require it.

## Code-only publication

Keep personal evidence, contacts, CVs, live records, source documents, integration IDs, credentials and runtime configuration outside Git. `.gitignore` is a convenience; publication uses an explicit allowlist and privacy scan.

```sh
.venv/bin/python tools/prepare_repository.py
```

This creates a new clean directory, relative-path hash manifest, privacy report and source-only ZIP. It does not overwrite earlier publication directories or push to GitHub. Inspect the exact artifacts before uploading; see `docs/GITHUB.md`.
