"""Persistent single-writer release state machine; standard library only."""
import argparse
import json
import sqlite3
import uuid
from pathlib import Path
import release

canonical = release.canonical
digest = release.sha


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    release.atomic_bytes(path, canonical(value) + b'\n')


def initialize(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    runtime = dict(base_revision='fixture-only', tokenizer_sha256='a'*64,
                   template_sha256='b'*64, generation=dict(max_new_tokens=32, do_sample=False), dtype='float32')
    for version in ['A', 'B']:
        artifact = root / f'model-{version}.txt'
        artifact.write_text(f'STUB ONLY — version {version}\n', encoding='utf-8')
        files = {artifact.name: release.file_sha(artifact)}
        manifest = dict(schema_version=1, model_id=f'fixture-{version}', artifact_uri=str(artifact),
                        model_sha256=digest(canonical(files)), protocol_sha256='d'*64,
                        golden_sha256='e'*64, runtime_sha256=digest(canonical(runtime)),
                        runtime=runtime, file_hashes=files, synthetic=True)
        report = {k: manifest[k] for k in ['model_id','model_sha256','protocol_sha256','golden_sha256','runtime_sha256']}
        report.update(status='complete', passed=True, evaluation_run_id=f'fixture-eval-{version}',
                      metrics=dict(accuracy=.8, format_rate=1.), synthetic=True)
        write(root/f'manifest-{version}.json', manifest); write(root/f'report-{version}.json', report)
    write(root/'accepted.json', read(root/'manifest-A.json'))
    report = read(root/'report-B.json'); report.update(status='running', passed='false')
    write(root/'report-incomplete.json', report)
    report = read(root/'report-B.json'); report['passed'] = False
    write(root/'report-reject.json', report)
    write(root/'config.json', dict(tokenizer_revision='r1',template_sha256='b'*64,max_length=128,code_revision='prepare-v1'))
    (root/'input.txt').write_text('Первый пример\nВторой пример\n', encoding='utf-8')
    print('Created STUB ONLY workspace', root, flush=True)


def prepare(root):
    root = Path(root); config = read(root/'config.json')
    key = release.cache_key(root/'input.txt', config)
    entry = root/'cache'/f'{key}.json'
    if entry.exists():
        result = read(entry)
        if result['input_sha256'] != release.file_sha(root/'input.txt') or result['config'] != config:
            raise ValueError('Corrupted preparation cache')
        print('CACHE_HIT', key, flush=True)
        return result
    text = (root/'input.txt').read_text(encoding='utf-8')
    if not text.strip() or any(len(line)>10000 for line in text.splitlines()):
        raise ValueError('Invalid preparation input')
    if config.get('schema')=='golden-jsonl':
        seen=set()
        for line in text.splitlines():
            row=json.loads(line)
            if (not isinstance(row.get('input'),str) or not row['input'].strip()
                or row.get('expected') not in row.get('choices',[]) or row.get('id') in seen):
                raise ValueError('Invalid golden row')
            seen.add(row['id'])
    result = dict(input_sha256=release.file_sha(root/'input.txt'), rows=len(text.splitlines()),
                  config=config, cache_key=key)
    write(entry, result)
    print('PREPARED', key, flush=True)
    return result


def database(root):
    db = sqlite3.connect(Path(root)/'release-journal.sqlite')
    db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE IF NOT EXISTS intents (id TEXT PRIMARY KEY, manifest TEXT NOT NULL, event TEXT NOT NULL, committed INTEGER NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, status TEXT NOT NULL, detail TEXT NOT NULL)')
    return db


def export_events(root, db):
    events = [row[0] for row in db.execute('SELECT event FROM intents WHERE committed=1 ORDER BY rowid')]
    release.atomic_bytes(Path(root)/'publications.jsonl', ('\n'.join(events)+ ('\n' if events else '')).encode('utf-8'))


def reconcile(root, db):
    accepted = canonical(read(Path(root)/'accepted.json')).decode()
    db.execute('UPDATE intents SET committed=1 WHERE manifest=? AND committed=0', (accepted,))
    db.commit()
    export_events(root, db)


def obtain(root, manifest_name):
    manifest = read(Path(root)/manifest_name)
    release.verify_artifact(manifest)
    print('ARTIFACT_VERIFIED', manifest['model_id'], '(read existing artifact; NO TRAINING)', flush=True)
    return manifest


def assess(root, manifest, report_name):
    report = read(Path(root)/report_name)
    if not manifest.get('synthetic'):
        from provenance import verify_decision
        verify_decision(root, manifest, report)
    release.validate_release(manifest, report)
    return report


def publish_event(root, manifest, report, prepared, fail_after_pointer=False):
    root = Path(root)
    release.validate_release(manifest, report)
    release.verify_artifact(manifest)
    identity = digest(canonical(dict(manifest=manifest, decision=report)))
    with database(root) as db:
        reconcile(root, db)
        old = db.execute('SELECT committed FROM intents WHERE id=?', (identity,)).fetchone()
        if old and old[0] and canonical(read(root/'accepted.json')) == canonical(manifest):
            print('ALREADY_PUBLISHED', identity, flush=True)
            return dict(release_id=identity, model_id=manifest['model_id'], repeated=True)
        event = dict(release_id=identity, model_id=manifest['model_id'], runtime_sha256=manifest['runtime_sha256'],
                     evaluation_run_id=report['evaluation_run_id'], prepared=prepared['input_sha256'])
        db.execute('INSERT OR IGNORE INTO intents VALUES (?,?,?,0)',
                   (identity, canonical(manifest).decode(), canonical(event).decode()))
        db.commit()
        release.publish(manifest, report, root/'accepted.json')
        if fail_after_pointer:
            raise RuntimeError('Injected crash after pointer, before committed event')
        db.execute('UPDATE intents SET committed=1 WHERE id=?', (identity,)); db.commit()
        export_events(root, db)
    print('PUBLISHED', manifest['model_id'], identity, flush=True)
    return event


def run(root, report_name, fail_after_prepare=False, manifest_name='manifest-B.json', fail_after_pointer=False):
    root = Path(root)
    attempt = uuid.uuid4().hex
    try:
        with database(root) as db:
            reconcile(root, db)
            db.execute('INSERT INTO attempts VALUES (?,?,?)',(attempt,'started','')); db.commit()
        prepared = prepare(root)
        if fail_after_prepare:
            raise RuntimeError('Injected failure after preparation')
        manifest = obtain(root, manifest_name)
        report = assess(root, manifest, report_name)
        result = publish_event(root, manifest, report, prepared, fail_after_pointer)
    except Exception as exc:
        with database(root) as db:
            db.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)',(attempt,'failed',str(exc))); db.commit()
        raise
    else:
        with database(root) as db:
            db.execute('UPDATE attempts SET status=? WHERE id=?',('complete',attempt)); db.commit()
        return result


def main():
    p = argparse.ArgumentParser(); p.add_argument('--workspace',type=Path,default=Path('.lab'))
    sub = p.add_subparsers(dest='command', required=True); sub.add_parser('init')
    r = sub.add_parser('run'); r.add_argument('--report',default='report-B.json')
    r.add_argument('--manifest',default='manifest-B.json')
    r.add_argument('--fail-after-prepare',action='store_true'); r.add_argument('--fail-after-pointer',action='store_true')
    args=p.parse_args()
    if args.command=='init': initialize(args.workspace)
    else: run(args.workspace,args.report,args.fail_after_prepare,args.manifest,args.fail_after_pointer)
