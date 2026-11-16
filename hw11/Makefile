HW11_PY ?= uv run --no-project --python 3.12 python
HW11_LOCAL ?= uv run --no-project --python 3.12 --with-requirements lab11/requirements.txt python
.PHONY: hw11-up hw11-status hw11-smoke hw11-grafana hw11-check hw11-a hw11-b hw11-c hw11-verify hw11-collect hw11-report hw11-audit hw11-down
hw11-up:
	$(HW11_PY) -m hw11.stand up
hw11-status:
	$(HW11_PY) -m hw11.stand status
hw11-smoke:
	$(HW11_PY) -m hw11.stand smoke
hw11-grafana:
	$(HW11_PY) -m hw11.stand grafana
hw11-check:
	$(HW11_LOCAL) -m unittest discover -s lab11 -v
hw11-a:
	$(HW11_PY) -m hw11.rollout
hw11-b:
	$(HW11_PY) -m hw11.balance
hw11-c:
	$(HW11_PY) -m hw11.hpa
hw11-verify:
	$(HW11_PY) -m hw11.verify
hw11-collect:
	$(HW11_PY) -m hw11.collect
hw11-report:
	$(HW11_PY) -m hw11.findings
	$(HW11_PY) -m hw11.report
hw11-audit:
	$(HW11_PY) -m hw11.audit
hw11-down:
	$(HW11_PY) -m hw11.stand down --confirm
