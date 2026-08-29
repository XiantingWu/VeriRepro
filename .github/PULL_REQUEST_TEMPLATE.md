## Summary

<!-- What changes and why? -->

## Evidence / verification

<!-- Tests, fixture, paper/repository case, or report artifact that verifies the change. -->

## Trust-boundary checklist

- [ ] This does not silently broaden model-generated shell authority.
- [ ] Host filesystem/network access is unchanged or explicitly documented and tested.
- [ ] Secrets are not passed into third-party experiment containers.
- [ ] New external downloads have size/integrity/redirect controls where applicable.
- [ ] PASS/FAIL evidence remains deterministic and auditable.

## Public quality checks

- [ ] `ruff check src tests scripts`
- [ ] `mypy`
- [ ] `pytest -q`
- [ ] `python scripts/release_check.py`
- [ ] `python scripts/launch_surface_check.py`
- [ ] `verirepro doctor --json`

## Release-facing changes

<!-- Leave these unchecked when the change does not alter release-relevant source/policy. -->

- [ ] If this changes runtime/package/measurement/release-policy/workflow bytes, I understand prior trusted release evidence becomes stale until maintainers regenerate exact-head evidence.
- [ ] If this changes a public API/schema, compatibility and migration impact are documented and tested.
