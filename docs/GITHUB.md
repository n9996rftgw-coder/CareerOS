# Review and publish the code

Use a private, code-only repository by default. Keep the runnable source separate from the private working installation.

## Prepare

Run `python tools/prepare_repository.py` from the working installation. The tool copies named app, engine, renderer, test, web, export and documentation files; anonymises candidate-specific display strings in the copy; and includes only fictional examples with empty tracker tables.

It excludes real evidence, applications, contacts, JDs, research, CVs, exports, source archives, integrations, credentials and local runtimes. It checks candidate identifiers, non-example email addresses, absolute home paths and common credential patterns, then writes `PUBLICATION_MANIFEST.json`, `PRIVACY_REPORT.json` and a source-only ZIP.

An allowlist and pattern scan reduce accidental disclosure. They do not establish that every future code change is safe. Inspect the exact files and manifest before uploading. Do not upload the whole working installation.

## Verify

Install the core dependencies separately and run the three core test commands in the README from the clean copy. Workbook fixtures are additional checks only when the Codex bundled spreadsheet runtime is available. Do not commit runtimes or `node_modules` to make those fixtures run.

The demo seeder creates local runtime files from fictional examples and refuses to overwrite existing files. Active data folders remain ignored by Git.

## Publish

1. Create an empty **private** GitHub repository, for example `careeros`, in the intended account.
2. Supply its link to the assistant, or upload the reviewed clean files yourself. Keep tokens and passwords out of chat and source files.
3. Commit only the reviewed manifest's files. Verify repository visibility, file list and commit contents.
4. Keep the evidence store and canonical Google Sheet separate from GitHub. Private visibility is not a reason to upload candidate records.

Preparation does not authenticate, create a repository, push a commit, configure a live Sheet or deploy a site. Verify each external result from the service after it succeeds.
