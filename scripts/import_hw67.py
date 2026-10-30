"""Export immutable provenance; reuse artifacts, NEVER train or regenerate eval."""
import argparse
import json
import shutil
from pathlib import Path
import release
from process_core import read,write


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,default=Path('C:/MLOPS/6-7/mlops26-hw6-7/hw67-broken'))
    p.add_argument('--workspace',type=Path,default=Path('.runtime/real'))
    a=p.parse_args(); source=a.source.resolve(); dest=Path('upstream'); dest.mkdir(exist_ok=True)
    for folder in ('evaluation','reports','data/eval'):
        (dest/folder).mkdir(parents=True,exist_ok=True)
    for path in (source/'evaluation').glob('*.py'):
        shutil.copy2(path,dest/'evaluation'/path.name)
    for name in ('params.json','baseline.json'):
        shutil.copy2(source/'evaluation'/name,dest/'evaluation'/name)
    for path in (source/'submission/reports').glob('*.json'):
        shutil.copy2(path,dest/'reports'/path.name)
    for path in (source/'data/eval').glob('*.jsonl'):
        shutil.copy2(path,dest/'data/eval'/path.name)
    write(dest/'checksums.json',{p.relative_to(dest).as_posix():release.file_sha(p)
        for folder in ('evaluation','reports','data/eval') for p in sorted((dest/folder).glob('*')) if p.is_file()})
    a.workspace.mkdir(parents=True,exist_ok=True)
    import mlflow
    from huggingface_hub import snapshot_download
    mlflow.set_tracking_uri('http://127.0.0.1:5006'); client=mlflow.MlflowClient()
    base=read(source/'evaluation/baseline.json')
    base_dir=Path(snapshot_download(base['name'],revision=base['revision'],local_files_only=True))
    candidate=read(source/'submission/reports/candidate-model.json')
    downloads=Path('.runtime/artifacts').resolve(); downloads.mkdir(parents=True,exist_ok=True)
    adapter=Path(client.download_artifacts(candidate['run_id'],'model/artifacts/adapter',str(downloads)))
    cfg=read(source/'evaluation/params.json')
    manifests={}
    for role,folder,kind in [('baseline',base_dir,'base'),('candidate',adapter,'adapter')]:
        files={p.name:release.file_sha(p) for p in sorted(folder.iterdir())
               if p.is_file() and p.suffix in ('.safetensors','.json','.jinja','.txt','.model')}
        token_files={k:v for k,v in files.items() if k.startswith(('tokenizer','special_tokens','vocab','merges','chat_template'))}
        # Chat template is pinned separately and the complete tokenizer file inventory is retained.
        template_file=folder/'chat_template.jinja'
        if template_file.exists(): template=template_file.read_text(encoding='utf-8')
        else: template=read(folder/'tokenizer_config.json')['chat_template']
        runtime=dict(base_revision=base['revision'],tokenizer_sha256=release.sha(release.canonical(token_files)),
                     template_sha256=release.sha(template.encode('utf-8')),device='cpu',dtype='float32',max_input_tokens=2048,
                     generation=dict(system=cfg['system'],do_sample=False,seed=cfg['seed'],
                                     max_new_tokens=cfg['max_new_tokens'],enable_thinking=cfg['enable_thinking']))
        evaluation=read(dest/f'reports/{role}-eval.json')
        model_id=('Qwen3-0.6B@'+base['revision']) if kind=='base' else candidate['run_id']
        manifest=dict(schema_version=1,model_id=model_id,artifact_uri=str(folder.resolve()),
                      model_sha256=release.sha(release.canonical(files)),protocol_sha256=evaluation['protocol_sha256'],
                      golden_sha256=evaluation['golden_sha256'],runtime_sha256=release.sha(release.canonical(runtime)),
                      runtime=runtime,file_hashes=files,kind=kind,base_model=base['name'],
                      base_artifact_uri=str(base_dir.resolve()),evaluation_role=role,synthetic=False,
                      training_run_id=candidate['run_id'] if kind=='adapter' else None)
        release.verify_artifact(manifest)
        manifests[role]=manifest
        write(a.workspace/f'manifest-{role}.json',manifest)
    write(dest/'inventories.json',manifests)
    from provenance import decision
    for role in ('baseline','candidate'):
        report=decision(a.workspace,manifests[role])
        write(a.workspace/f'report-{role}.json',report)
    baseline_report=read(a.workspace/'report-baseline.json')
    release.publish(manifests['baseline'],baseline_report,a.workspace/'accepted.json')
    # Actual preparation input uses the same held-out questions, not weights/tensors.
    shutil.copy2(dest/'data/eval/golden.jsonl',a.workspace/'input.txt')
    write(a.workspace/'config.json',dict(tokenizer_revision=base['revision'],
        template_sha256=manifests['baseline']['runtime']['template_sha256'],max_length=2048,
        code_revision=release.file_sha('process_core.py'),schema='golden-jsonl'))
    print('Imported existing training/evaluation artifacts. Baseline retained; candidate rejected. NO TRAINING.')


if __name__=='__main__': main()
