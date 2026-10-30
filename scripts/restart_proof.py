"""Record real backend identity on each side of an explicit controlled restart."""
import argparse
import psutil
from scripts.http_client import request
from process_core import read,write
import release


def main():
    p=argparse.ArgumentParser(); p.add_argument('phase',choices=['before','after']); a=p.parse_args()
    status,body,_=request('http://127.0.0.1:8091','/ready'); assert status==200
    listeners=[c for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN' and c.laddr.port==8091]
    assert len(listeners)==1
    proc=psutil.Process(listeners[0].pid)
    assert proc.cwd()==str(__import__('pathlib').Path.cwd()) and 'service.py' in proc.cmdline()
    result=dict(process_id=proc.pid,process_started=proc.create_time(),ready=body,
                accepted_sha256=release.file_sha('.runtime/real/accepted.json'),rss_mb=proc.memory_info().rss/1024**2)
    if a.phase=='before': write('evidence/real-restart-before.json',result)
    else:
        before=read('evidence/real-restart-before.json')
        assert result['process_started']!=before['process_started']
        assert result['ready']==before['ready'] and result['accepted_sha256']==before['accepted_sha256']
        smoke=read('evidence/real-restart-smoke.json'); assert smoke['matches_saved_baseline']
        write('evidence/real-restart.json',dict(before=before,after=result,
            same_accepted_manifest=True,same_loaded_identity=True,real_smoke_after_restart=True))
    print(result,flush=True)


if __name__=='__main__': main()
