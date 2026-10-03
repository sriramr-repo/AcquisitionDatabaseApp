## Change summary

<!-- What changed and why? -->

## Testing checklist

- [ ] Added or updated unit tests for new deterministic logic or business rules.
- [ ] Added a regression test for each bug fixed.
- [ ] Covered relevant edge cases: empty input, null versus zero, malformed input, duplicates, and boundaries.
- [ ] Used isolated fixtures/temp databases; no production data or ingestion artifacts were modified.
- [ ] Added or updated integration tests where a real component boundary changed.
- [ ] Added or updated end-to-end coverage where a user workflow changed.
- [ ] Ran focused tests and related regression tests.
- [ ] Ran `npm run build` for dashboard changes.
- [ ] No unrelated failures were fixed or suppressed.

## Test commands and results

```text
# Paste commands and concise results here.
```

## Risk and data safety

- [ ] Gold/scoring behavior is unchanged, or the change is explicitly documented.
- [ ] Schema/source-of-truth behavior is unchanged, or migrations and compatibility are documented.
- [ ] External calls are mocked or bounded and failure behavior is tested.
