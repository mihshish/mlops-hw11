"""Local Prefect DAG. No training task: obtains existing HW6+7 artifacts."""
import argparse
import os
from pathlib import Path
os.environ.setdefault('PREFECT_HOME',str(Path('.runtime/prefect-home').resolve()))
os.environ.setdefault('PREFECT_SERVER_ANALYTICS_ENABLED','false')
from prefect import flow, task, get_run_logger
from prefect.context import get_run_context
import process_core as core
import release

STORE=Path('.runtime/prefect-results').resolve()


def preparation_key(context,parameters):
    root=Path(parameters['root'])
    return 'validated-input-'+release.cache_key(root/'input.txt',core.read(root/'config.json'))


@task(persist_result=True,cache_key_fn=preparation_key,result_storage=STORE,retries=0)
def prepare_input(root):
    result=core.prepare(root)
    get_run_logger().info('PREPARED %s rows=%s',result['cache_key'],result['rows'])
    return result


@task(retries=0,persist_result=False)
def obtain_artifact(root,manifest_name):
    return core.obtain(root,manifest_name)


@task(retries=0,persist_result=False)
def evaluate_admission(root,manifest,report_name):
    return core.assess(root,manifest,report_name)


@task(retries=0,persist_result=False)
def publish_accepted(root,manifest,report,prepared,fail_after_pointer):
    return core.publish_event(root,manifest,report,prepared,fail_after_pointer)


@flow(name='hw8910-verified-release',persist_result=False,retries=0,log_prints=True)
def release_flow(root,manifest_name='manifest-B.json',report_name='report-B.json',
                 fail_after_prepare=False,fail_after_pointer=False):
    root=str(Path(root).resolve())
    preparation=prepare_input(root,return_state=True)
    prepared=preparation.result()
    run_id=str(get_run_context().flow_run.id)
    print('FLOW_ID',run_id,'PREPARATION_STATE',preparation.name,flush=True)
    if fail_after_prepare:
        raise RuntimeError('Injected failure AFTER successful preparation')
    manifest=obtain_artifact(root,manifest_name)
    report=evaluate_admission(root,manifest,report_name)
    published=publish_accepted(root,manifest,report,prepared,fail_after_pointer)
    result=dict(flow_run_id=run_id,preparation_state=preparation.name,published=published)
    core.write(Path(root)/'last-flow.json',result)
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--workspace',type=Path,default=Path('.lab'))
    p.add_argument('--manifest',default='manifest-B.json'); p.add_argument('--report',default='report-B.json')
    p.add_argument('--fail-after-prepare',action='store_true'); p.add_argument('--fail-after-pointer',action='store_true')
    a=p.parse_args()
    release_flow(str(a.workspace),a.manifest,a.report,a.fail_after_prepare,a.fail_after_pointer)


if __name__=='__main__': main()
