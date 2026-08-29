# Examples

These examples illustrate VeriRepro's public manifest and artifact-evidence contracts. They are intentionally small and should not be read as claims that a real paper was reproduced.

## `verirepro.yaml`

`verirepro.yaml` is the preferred manifest spelling. It demonstrates:

- a repository-owned execution command request;
- default-disabled experiment networking;
- dataset declaration shapes;
- scalar metric expectations;
- Figure and Table artifact declarations.

Repository-authored metric/artifact expectations do **not** automatically become scientific authority. VeriRepro uses them for verdicts only after the operator explicitly authorizes the repository contract.

`reproagent.yaml` is retained only as the 0.x compatibility spelling.

## `artifact-demo/`

`artifact-demo/` is a tiny deterministic repository-layout fixture that shows how an experiment can emit:

- `VERIREPRO_METRIC accuracy=...`;
- a generated figure file;
- a generated CSV table;
- manifest declarations that compare those outputs to repository reference artifacts.

The underlying demo script can be inspected or run directly:

```bash
cd examples/artifact-demo
python reproduce.py
```

That direct command demonstrates the output contract only; it is not itself a paper-level VeriRepro run and does not establish scientific `PASS`.

For a real first VeriRepro invocation, use the pinned no-execution Quick Start in the repository `README.md` or `docs/GETTING_STARTED.md`.
