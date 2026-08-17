# Local validation record — 2026-08-17

Environment: Windows workstation, Docker Desktop 29.6.2, Python 3.13 local test environment, NVIDIA RTX 5060 Ti 16 GB. These results validate the repository on one machine only.

| Check | Result |
|---|---|
| Python compile | Pass |
| Inherited unit/integration suite | 46 passed in 4.86 s |
| Example lexical RAG recall@5 | 1.0 (1/1 case; demonstration only) |
| API `/health/live`, `/health/ready`, `/metrics` | Pass |
| Unsafe production-setting guards | Pass |
| Alembic clean migration | `0001_initial (head)` |
| Docker Compose configuration render | Pass |
| Kubernetes production Kustomize render | Pass |
| YAML parsing | 15 files pass |
| React production build | Pass inside multi-stage image build |
| Production image build | Pass; `prometheus-planning:phase5`, 212,812,127 bytes, runtime user `planner` |
| Container readiness smoke test | Pass: database, retrieval, and LLM client configured |
| Private-data copy check | Only placeholders and sanitized example SOP present |

Not yet measured because it requires representative client data, a real secret configuration, and an agreed workload: semantic/dense RAG quality set, Kimi answer quality, end-to-end planning latency percentiles, simultaneous-user capacity, queue saturation, solver scaling by task/resource count, GPU VRAM/thermal/power behavior during a soak, PostgreSQL backup restore time, failure/recovery objectives, multi-node failover, penetration testing, and client acceptance. Use the Phase 4 harness and `acceptance.json` before promoting a deployment.
