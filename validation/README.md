# Validation suite

Run `powershell -ExecutionPolicy Bypass -File validation/run_phase4.ps1` after installing dependencies. Results are written beneath `validation/results/` and are ignored by Git.

The acceptance gates are deliberately explicit: unit tests must pass; health endpoints must respond; scheduler outputs must be feasible; API p95 is reported separately for chat and planning; RAG questions must cite expected documents; and the GPU capture shows whether the configured inference limits leave usable headroom. A single workstation validates one-node capacity and failure recovery only—not multi-node high availability.
