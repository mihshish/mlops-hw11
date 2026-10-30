"""Bind a release to original HW6+7 raw answers and unchanged evaluation code."""
from pathlib import Path
from evaluation.contract import fingerprint, read_rows, validate_golden
from evaluation.solution import score, quality_gate
from process_core import read, write
import release

UPSTREAM=Path(__file__).resolve().parent/'upstream'


def verified_evaluation():
    recorded=read(UPSTREAM/'checksums.json')
    for name,digest in recorded.items():
        if release.file_sha(UPSTREAM/name)!=digest: raise ValueError('Upstream file modified: '+name)
    cfg=read(UPSTREAM/'evaluation/params.json')
    rows=read_rows(UPSTREAM/'data/eval/golden.jsonl')
    behavior=read_rows(UPSTREAM/'data/eval/behavioral.jsonl')
    training=read_rows(UPSTREAM/'data/eval/training-index.jsonl')
    proof=validate_golden(rows,training,behavior)
    spec=read(UPSTREAM/'evaluation/baseline.json')
    protocol=dict(config=cfg,golden=rows,behavioral=behavior,training_index=training,
                  evaluation_code={p.name:p.read_text(encoding='utf-8') for p in sorted((UPSTREAM/'evaluation').glob('*.py'))})
    reports={}
    for role in ('baseline','candidate'):
        report=read(UPSTREAM/f'reports/{role}-eval.json')
        outputs=read(UPSTREAM/f'reports/{role}-outputs.json')
        by_id={o['id']:o for o in outputs}
        if len(by_id)!=len(outputs) or set(by_id)!={r['id'] for r in rows+behavior}: raise ValueError('Raw IDs differ')
        computed=score(rows,[by_id[r['id']] for r in rows])
        if any(report[k]!=computed[k] for k in ('overall','slices','per_item')): raise ValueError('Metrics differ from raw outputs')
        if report['behavioral']!=score(behavior,[by_id[r['id']] for r in behavior]): raise ValueError('Behavioral mismatch')
        if (report['outputs_sha256']!=fingerprint(outputs) or report['protocol_sha256']!=fingerprint(protocol)
            or report['golden_sha256']!=fingerprint(rows) or report['baseline_spec_sha256']!=fingerprint(spec)):
            raise ValueError('Upstream protocol/answers changed')
        reports[role]=report
    return cfg,reports,proof


def decision(root,manifest):
    cfg,reports,proof=verified_evaluation()
    inventory=read(UPSTREAM/'inventories.json')
    role=manifest['evaluation_role']
    if role not in ('baseline','candidate'): raise ValueError('Unknown evaluation role')
    anchored=inventory[role]
    for key in ('model_id','kind','model_sha256','runtime_sha256','file_hashes','runtime','protocol_sha256','golden_sha256'):
        if manifest.get(key)!=anchored.get(key): raise ValueError('Unrecognized release inventory: '+key)
    report=reports[role]
    gate_passed=False
    try:
        quality_gate(reports['baseline'],reports['candidate'],cfg['critical_slices'])
        gate_passed=True; reason='Candidate meets unchanged HW6+7 quality gate'
    except ValueError as exc:
        reason=str(exc)
    if role=='candidate':
        passed=gate_passed; policy='candidate_quality_gate'
    else:
        # Assignment explicitly permits continuing the previously fixed baseline.
        # This is NOT a claim that baseline passed all candidate behavioral tests.
        spec=read(UPSTREAM/'evaluation/baseline.json')
        if report['model']!=spec or manifest['base_model']!=spec['name'] or manifest['runtime']['base_revision']!=spec['revision']:
            raise ValueError('Not the previously fixed baseline')
        passed=True; policy='retain_preexisting_baseline_not_candidate_promotion'
    bindings={k:manifest[k] for k in ('model_id','model_sha256','protocol_sha256','golden_sha256','runtime_sha256')}
    source_hashes={name:release.file_sha(UPSTREAM/name) for name in read(UPSTREAM/'checksums.json')}
    result=dict(status='complete',passed=passed,evaluation_run_id=report['evaluation_run_id'],**bindings,
                metrics={k:report['overall'][k] for k in ('accuracy','format_rate')},policy=policy,
                candidate_gate_passed=gate_passed,candidate_gate_reason=reason,source_files_sha256=source_hashes,
                leakage=proof,synthetic=False)
    write(Path(root)/('release-report-'+role+'.json'),result)
    return result


def verify_decision(root,manifest,report):
    current=decision(root,manifest)
    if current!=report: raise ValueError('Release report differs from actual quality decision and source hashes')
    release.validate_release(manifest,current)
