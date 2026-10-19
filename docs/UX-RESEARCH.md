# Quote desk workflow review

Research and implementation: 19 October 2026.

This is a review of the current product against published UX guidance. It is not a usability study with clearing agents; the proposed workflow still needs observation with actual users.

## Findings and evidence

| Existing friction | Research principle | Implemented response |
| --- | --- | --- |
| Setup, purchase buttons, charts, uploads, and payment actions compete on one screen. | NN/g: match the user's task, minimize competing information, make the next action clear. | Quotes, Approvals, Connections, and Settings have separate navigation. Quote work starts at the inbox. |
| Upload immediately produces downloads without an explicit check. | GOV.UK: let users check information before submitting; provide a way back to correct mistakes. | Add quote → Check details → Export. A selected quote has its own route, charges, notes, original text, and saved check. Correcting text creates a new quote, with its parse cost stated. |
| Company tools silently operate on the first quote in the list. | NN/g: error prevention, recognition instead of recall. | Finance, ledger, and payout-plan actions live inside the selected quote. Delete and approval decisions require a contextual confirmation. |
| Network failures can leave buttons busy; polling failures look like an empty inbox. | NN/g: system status and recovery; W3C: descriptive errors and programmatic status messages. | Request timeouts, busy states, retry controls, preserved input, last-update information, and separate loading, empty, no-match, and unavailable states. |
| Different currencies are summed into one unlabelled dashboard total. | NN/g: match real-world concepts; prevent misleading information. | Counts replace the combined monetary total. Every quote retains its currency; NGN planning estimates appear in its details. |
| Uploaded work disappears from the inbox after refresh. | NN/g: user control and predictable feedback. | API intake now saves quotes, company-scoped check metadata, and source text. A current batch can be reopened using an account-scoped batch ID saved in the browser. |
| Incorrect/oversized files can consume earlier files' quota before failing. | GOV.UK: file upload guidance and useful validation errors. | File type, 10 MB size, text extraction, and quota checks precede batch parsing. Errors name the affected file. |
| New users see a dense tools panel without a clear starting point. | GOV.UK: task-based service patterns. | A first-quote empty state, three-step intake, Telegram linking instructions, and usage in the sidebar. |

## Main journeys

1. Sign in or create a company workspace.
2. Add a quote using PDF/TXT files or pasted text. The interface shows required and available parses.
3. Inspect the selected carrier, route, terms, charges, extraction notes, and currency estimates. Missing route or priced-charge information blocks the saved check.
4. Correct the source and parse it again if needed. The original quote remains available until explicitly deleted.
5. Mark the quote checked. The check records the account and time, persists in the quote payload, and uses no additional parse.
6. Download that quote as PDF or Excel. For uploaded batches, check all quotes before the interface offers pack downloads.
7. Open Approvals separately to inspect and confirm a payment or clearance request. A quote check does not authorize either action.

Connections and company preferences can be visited independently. Purchase actions live in Settings and return to an explicit payment verification result.

## Scope and implementation notes

- The production Next.js dashboard is the main application described in the README. The separate Vite parser demonstration is unchanged.
- No new database tables or schema migration are needed. Check metadata and original text use the existing quote JSON payload.
- Inbox display remains limited to the API's 20 most recent records plus the current pack. Search and filters apply to those records, not the full historical database.
- A check records the user's inspection; it does not guarantee quote accuracy. Exports remain accessible through the existing API contract; the browser guides users through checking first.
- The latest pack is restored in the same browser/account. This is not a full batch history feature.
- Company settings expose the existing company-scoped parallel rate and port risk. Service-wide official/fallback rate editing is not presented as a company preference.
- The pre-existing payment review endpoint now rejects already handled requests, and accepts both SQLite JSON strings and Supabase JSON objects. Concurrent execution across multiple server processes still needs an atomic claim and provider-side idempotency before relying on payment execution in production.
- Other security and operational findings from the earlier project review are separate follow-up work.

## Sources

- [Nielsen Norman Group: 10 usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/) — status, user control, error prevention, and reducing competing information.
- [GOV.UK: Check answers](https://design-system.service.gov.uk/patterns/check-answers/) — review and correction before proceeding.
- [GOV.UK: File upload](https://design-system.service.gov.uk/components/file-upload/) — clear file selection and file guidance.
- [GOV.UK: Error summary](https://design-system.service.gov.uk/components/error-summary/) — identify validation errors and connect them to their inputs.
- [W3C: Error identification](https://www.w3.org/WAI/WCAG22/Understanding/error-identification) — explain which input failed in text.
- [W3C: Status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html) — expose updates to assistive technology.

## Follow-up user research

Observe clearing agents handling a new quote, correcting a wrong currency, checking a two-file pack, recovering from a failed upload, and approving a stored request. Record completion, wrong-quote actions, errors, and requests for help. Validate whether “Checked” and “Approval” are clearly distinguished and whether users can identify the next step without prompting. No measured improvement is claimed before these sessions.

## Implementation validation

- The dashboard's Python tests cover quote persistence, company ownership, cloud quota and JSON payload handling, batch validation before quota use, current pack contents, and review invalidation after changes. The latest local Telegram/unit run is documented in [TELEGRAM-WORKFLOW.md](TELEGRAM-WORKFLOW.md); the full HTTP integration suite was not rerun for the Telegram changes.
- 9 JavaScript workflow checks for record identity, filters, status rules, file/quota validation, currencies, and request error recovery.
- Production Next.js build.
- Chrome workflow checks at 1440 × 1000 and 390 × 844: account creation, empty inbox, TXT upload, check-before-export controls, saved checks and pack restoration after refresh, PDF/Excel downloads with valid file signatures, search/no-results recovery, approval confirmation/cancel/rejection, settings persistence, Telegram instructions, and recovery after a deliberately blocked network request.
- Browser runs use temporary storage and mocked external integrations. No real payment, clearance, Telegram, or email messages are sent. These checks are not a full accessibility audit or a substitute for usability sessions.
