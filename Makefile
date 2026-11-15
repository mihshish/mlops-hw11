export PYTHONUTF8 := 1
export PYTHONIOENCODING := utf-8
.PHONY: install check check-red ci-negative process-demo flow-demo import-hw67 serve status smoke invalid bench release-baseline reject-candidate
install:
	uv sync --frozen --extra inference
check:
	uv run python -m scripts.check --save
check-red:
	uv run python -m scripts.red_green
ci-negative:
	uv run python -m scripts.ci_negative
process-demo:
	uv run python -m scripts.experiments
flow-demo:
	uv run python -m scripts.experiments --prefect
import-hw67:
	uv run --extra inference python -m scripts.import_hw67
serve:
	uv run --extra inference python service.py --workspace .runtime/real --backend real --warmup-seconds 0 --port 8091
status:
	uv run python -m scripts.http_client status
smoke:
	uv run python -m scripts.http_client smoke
invalid:
	uv run python -m scripts.http_client invalid
bench:
	uv run python -m scripts.http_client benchmark --n 4
release-baseline:
	uv run python pipeline.py --workspace .runtime/real --manifest manifest-baseline.json --report report-baseline.json
reject-candidate:
	uv run python pipeline.py --workspace .runtime/real --manifest manifest-candidate.json --report report-candidate.json

.PHONY: real-flow-demo rollback-demo flow-proof rollback-proof bench-proof
real-flow-demo:
	uv run python -m scripts.real_flow_demo
rollback-demo:
	uv run python -m scripts.rollback_demo
flow-proof:
	uv run python -m scripts.proof flow
rollback-proof:
	uv run python -m scripts.proof rollback
bench-proof:
	uv run python -m scripts.proof benchmark

.PHONY: restore-baseline
restore-baseline:
	uv run --extra inference python -m scripts.restore_baseline

.PHONY: package
package:
	uv run python -m scripts.package

include hw11/Makefile
