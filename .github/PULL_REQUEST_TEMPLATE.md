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

## Tests

- [ ] `pytest -q`
- [ ] `verirepro --version`
- [ ] `verirepro doctor --json`
