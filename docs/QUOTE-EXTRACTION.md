# Source-supported quote extraction

The rules reader and the model-assisted path use the same monetary evidence checks in `quote_charges.py`. Model-generated amounts cannot bypass these checks. Every accepted currency-marked charge retains its original clause as `source_text`.

- Preserve decimal points and thousands separators when splitting sentences.
- Exclude conditional and optional clauses from the working baseline; retain them in extraction flags/notes.
- Keep unquantified hourly, daily, weight, volume, and per-container rates out of flat totals. Apply an explicitly stated minimum quantity when present.
- Interpret an explicitly named AMS/ISF pair at a price “each” as two filings; flag other unclear quantities for review.
- Count apparent repeated descriptions once for the same currency and amount, including a repeated ocean/40HQ quotation, and flag the decision. Separate named origin and destination charges remain separate even when their amounts match.
- Flag multi-amount clauses, price ranges, unexplained monetary mentions, and percentage terms for review instead of choosing a value or a percentage base.
- Require an explicit transit label. Rental periods, free time, payment terms, and validity periods are not transit estimates.
- Preserve route alternatives and require confirmation. Do not fill in a typical ocean transit duration.

The working total can be incomplete when the source is ambiguous. Review the flags and the original source before marking a quote checked. Clearer source formatting can resolve omitted charges. Existing saved quotes are not silently rewritten: correct/reparse the source, review it, and export again.

`tests/test_quote_evidence.py` reconstructs reported freight clauses for regression coverage. It is not the original email. The nine explicitly labeled baseline items in that reconstruction total USD 4,705, not USD 4,625. The conflicting handling-fee sentence in the report is tested separately as ambiguous; it is not silently assigned to origin or destination.

The Nigerian customs form is not presented for an explicitly known non-Nigerian destination. Shipment free-time fields remain optional planning inputs and require actual container, date, and rate evidence.
