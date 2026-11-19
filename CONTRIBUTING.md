# Contributing

Thanks for looking. fitslog is a small, single-purpose tool; these
house rules keep changes easy to review.

## Run the tests

```console
$ python3 run_tests.py
```

All tests must pass before a change is considered. Add tests in `tests/`
for any new behaviour. Tests use synthetic FITS files generated with
Astropy — please do the same rather than committing real observations.

## House rules

- Keep the tool single-purpose and headers-only: fitslog never loads
  image data. Do not add a dependency without raising it in an issue
  first.
- Keyword spellings live in exactly one place: the `ALIASES` table in
  `fitslog/core.py`. A new spelling is a one-line change there.
- The README's Honest limits section is a promise. If a change alters a
  documented limit or behaviour, update the README in the same pull
  request — and SKILL.md too if the CLI, its flags or its exit codes
  changed.
- Plain words in docs and messages. No marketing language.

## Claiming an issue

Comment on the issue saying you are taking it, then open a pull request
that mentions the issue number.
