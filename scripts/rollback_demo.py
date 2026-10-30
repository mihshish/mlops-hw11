"""Actual HTTP A -> publish B -> restart B -> rollback A -> restart A."""
import contextlib
import io
from pathlib import Path
from tests_integration.test_incidents import IncidentRegression
from process_core import write


def main():
    test=IncidentRegression('test_06_loaded_version_http')
    log=io.StringIO(); observations=[]
    try:
        with contextlib.redirect_stdout(log):
            test.setUp()
            def observe(label,expected):
                status,body=test.http('/generate',dict(prompt='version probe',max_new_tokens=32))
                test.assertEqual(status,200); test.assertEqual(body['model_id'],expected)
                test.assertIn(expected,body['answer'])
                observations.append(dict(stage=label,model_id=body['model_id'],answer=body['answer']))
            with test.server():
                test.ready(); observe('initial-A','fixture-A')
                test.assertEqual(test.cli('run').returncode,0)
                observe('published-B-but-A-still-in-memory','fixture-A')
            with test.server():
                test.ready(); observe('restart-loaded-B','fixture-B')
                test.assertEqual(test.cli('run','--manifest','manifest-A.json','--report','report-A.json').returncode,0)
                observe('rollback-pointer-A-but-B-still-in-memory','fixture-B')
            with test.server():
                test.ready(); observe('restart-loaded-A','fixture-A')
    finally:
        test.doCleanups()
        Path('evidence/rollback-http.log').write_text(log.getvalue(),encoding='utf-8')
    write('evidence/rollback-http.json',dict(synthetic=True,observations=observations))
    for row in observations: print(row,flush=True)
    print('ROLLBACK VERIFIED using real TCP servers and clearly labeled STUB ONLY versions')


if __name__=='__main__': main()
