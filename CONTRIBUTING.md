# Contributing

Thanks for looking. repograph is small, dependency-free and deliberately boring to run.

## Ground rules

1. **No required third-party dependencies.** The tool must work on a bare Python 3.9+ install.
   Optional accelerators are fine; required libraries are not.
2. **Evidence or silence.** If repograph says something about a repository, it must be able to
   point at the file and line that justifies it.
3. **Never crash a scan.** Odd input degrades to a warning in `meta.warnings`.
4. **Deterministic output.** Same input, same bytes out. Fix your seeds.

## Getting set up

```bash
git clone https://github.com/WindyBanana/repograph
cd repograph
make test          # unit + end-to-end tests, stdlib unittest only
make demo          # scan the bundled example monorepo
./bin/repograph scan . -o /tmp/self   # dogfood: repograph on itself
```

## Adding a language analyzer

1. Add extensions to `LANGUAGES` in `packages/repograph-core/src/repograph_core/walker.py`.
2. Write an analyzer in `languages/` and register it with `@register("YourLanguage")`. Return
   imports, symbols, endpoints and framework hints.
3. Teach `resolve.py` how to turn its import strings into files or packages.
4. Add a test in `tests/test_analysis.py`, and ideally a small fixture in `examples/`.

## Adding a security rule

Add a `Rule` to `security/patterns.py` with a CWE, a severity, a confidence and — most importantly
— a remediation that tells someone what to actually do. Then add a case to `TestSecurity`.

## Adding an external system signature

Add a row to `SIGNATURES` in `integrations.py`: `(id, display name, kind, technology, regex)`. Keep
the regex specific enough that it does not fire on the word appearing in a comment.

## Adding an output format

Write a module in `packages/repograph-render/` that consumes a `ScanResult` (and, for diagrams, the
layouts from `diagrams.build_all`), then wire it into `render.py` and `ALL_FORMATS`.

## Style

`ruff` config lives in `pyproject.toml`; line length is 108. Type hints on public functions.
Comments explain *why*, not *what*.
