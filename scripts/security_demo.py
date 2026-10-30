"""Additional real file/metadata rejection checks, no model generation."""
import copy
import tempfile
from pathlib import Path
import process_core as core
import release


def main():
    results=[]
    with tempfile.TemporaryDirectory(prefix='hw8910-security-') as tmp:
        root=Path(tmp)/'stand'; core.initialize(root)
        before=release.file_sha(root/'accepted.json')
        report=core.read(root/'report-B.json')
        for label,change in [('NaN',{'metrics':dict(accuracy=float('nan'),format_rate=1.)}),
                             ('truthy_string',{'passed':'true'}),('missing_status',{})]:
            bad=copy.deepcopy(report); bad.update(change)
            if label=='missing_status': del bad['status']
            try: release.publish(core.read(root/'manifest-B.json'),bad,root/'accepted.json')
            except ValueError as exc: results.append(dict(case=label,rejected=True,reason=str(exc)))
            else: raise AssertionError(label+' passed')
            assert release.file_sha(root/'accepted.json')==before
        (root/'model-B.txt').write_text('TAMPERED ARTIFACT',encoding='utf-8')
        try: core.obtain(root,'manifest-B.json')
        except ValueError as exc: results.append(dict(case='actual_file_tampering',rejected=True,reason=str(exc)))
        else: raise AssertionError('Changed real bytes accepted')
        assert release.file_sha(root/'accepted.json')==before
        results.append(dict(case='unchanged_pointer',sha256_before=before,sha256_after=release.file_sha(root/'accepted.json')))
    with tempfile.TemporaryDirectory(prefix='hw8910-real-report-') as tmp:
        root=Path(tmp)
        manifest=core.read('.runtime/real/manifest-candidate.json')
        fake=core.read('.runtime/real/report-candidate.json'); fake['passed']=True
        from provenance import verify_decision
        try: verify_decision(root,manifest,fake)
        except ValueError as exc: results.append(dict(case='manual_true_for_real_candidate',rejected=True,reason=str(exc)))
        else: raise AssertionError('Manual PASS bypassed original quality decision')
    core.write('evidence/security-checks.json',results)
    for result in results: print(result,flush=True)


if __name__=='__main__': main()
