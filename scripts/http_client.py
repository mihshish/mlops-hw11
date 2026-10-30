"""Real HTTP smoke/invalid-request evidence and honest small CPU benchmark."""
import argparse
import concurrent.futures
import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from process_core import read,write


def request(url,path,payload=None,timeout=180):
    data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8')
    req=urllib.request.Request(url+path,data=data,headers={'Content-Type':'application/json'})
    start=time.perf_counter()
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r: status,body=r.status,r.read()
    except urllib.error.HTTPError as e: status,body=e.code,e.read()
    return status,json.loads(body),time.perf_counter()-start


def main():
    p=argparse.ArgumentParser(); p.add_argument('command',choices=['status','smoke','invalid','benchmark'])
    p.add_argument('--url',default='http://127.0.0.1:8091'); p.add_argument('--n',type=int,default=4,choices=[4,8])
    p.add_argument('--output',default=None)
    a=p.parse_args(); Path('evidence').mkdir(exist_ok=True)
    if a.command=='status':
        for path in ['/health','/ready']:
            status,body,_=request(a.url,path); print(path,status,json.dumps(body,ensure_ascii=False),flush=True)
        return
    if a.command=='invalid':
        _,before,_=request(a.url,'/debug')
        outcomes=[]
        for payload in [{'prompt':''},{'prompt':'test','max_new_tokens':0},{'prompt':'test','max_new_tokens':100000},
                        {'prompt':'test','max_new_tokens':'32'}]:
            status,body,_=request(a.url,'/generate',payload)
            assert 400<=status<500,(status,body)
            outcomes.append(dict(input=payload,status=status,response=body))
        _,after,_=request(a.url,'/debug')
        assert before['calls']==after['calls']
        result=dict(calls_before=before['calls'],calls_after=after['calls'],attempts=outcomes)
        write('evidence/real-invalid.json',result)
        print('HTTP 422: invalid requests rejected; backend calls unchanged',before['calls'],after['calls'])
        return
    rows=[json.loads(s) for s in Path('upstream/data/eval/golden.jsonl').read_text(encoding='utf-8').splitlines() if s]
    accepted=read('.runtime/real/accepted.json')
    if a.command=='smoke':
        row=rows[0]
        status,body,elapsed=request(a.url,'/generate',dict(prompt=row['input'],max_new_tokens=32))
        assert status==200,(status,body)
        assert body['model_id']==accepted['model_id'] and body['runtime_sha256']==accepted['runtime_sha256']
        saved={o['id']:o for o in read('upstream/reports/baseline-outputs.json')}[row['id']]
        assert json.loads(body['answer'])==json.loads(saved['raw']), 'API and original baseline response disagree'
        result=dict(status=status,golden_id=row['id'],input=row['input'],response=body,
                    client_seconds=elapsed,matches_saved_baseline=True)
        write(a.output or 'evidence/real-smoke.json',result)
        print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
        return
    records=[]; summaries=[]
    output=Path('evidence/benchmark.jsonl')
    with output.open('w',encoding='utf-8',newline='\n') as stream:
        for concurrency in [1,2]:
            batch_start=time.perf_counter()
            def one(item):
                index,row=item; start=time.perf_counter()
                record=dict(id=row['id'],request_index=index,concurrency=concurrency,max_new_tokens=32,
                            status=None,error=None,model_id=None,output_tokens=None,generation_seconds=None,queue_seconds=None)
                try:
                    status,body,elapsed=request(a.url,'/generate',dict(prompt=row['input'],max_new_tokens=32))
                    record.update(status=status,client_seconds=elapsed,response=body)
                    if status!=200: record['error']=json.dumps(body,ensure_ascii=False)
                    else:
                        for key in ('model_id','runtime_sha256','output_tokens','generation_seconds','queue_seconds','request_id'):
                            record[key]=body[key]
                        if body['model_id']!=accepted['model_id']: record['error']='Unexpected model ID'
                except Exception as exc:
                    record.update(error=f'{type(exc).__name__}: {exc}',client_seconds=time.perf_counter()-start)
                return record
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                for record in pool.map(one,enumerate(rows[:a.n])):
                    records.append(record); stream.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n'); stream.flush()
                    print('REQUEST',record['id'],'c=',concurrency,'status=',record['status'],'seconds=',round(record['client_seconds'],3),flush=True)
            wall=time.perf_counter()-batch_start
            group=[r for r in records if r['concurrency']==concurrency]
            ok=[r for r in group if r['status']==200 and r['error'] is None]
            errors=[r for r in group if r not in ok]
            average=lambda xs:sum(xs)/len(xs) if xs else None
            summaries.append(dict(concurrency=concurrency,n=len(group),successes=len(ok),errors=len(errors),
                batch_seconds=wall,successful_requests_per_second=len(ok)/wall,
                success_mean_client_seconds=average([r['client_seconds'] for r in ok]),
                success_max_client_seconds=max([r['client_seconds'] for r in ok],default=None),
                error_mean_client_seconds=average([r['client_seconds'] for r in errors]),
                error_max_client_seconds=max([r['client_seconds'] for r in errors],default=None),
                mean_generation_seconds=average([r['generation_seconds'] for r in ok]),
                mean_queue_seconds=average([r['queue_seconds'] for r in ok]),
                actual_output_tokens=sum(r['output_tokens'] for r in ok)))
    with Path('evidence/benchmark.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(summaries[0])); writer.writeheader(); writer.writerows(summaries)
    write('evidence/benchmark-summary.json',dict(cpu_reduced_set=a.n==4,requests_each_mode=a.n,
        same_ids_both_modes=[r['id'] for r in rows[:a.n]],max_new_tokens=32,summary=summaries))
    print(json.dumps(summaries,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__': main()
