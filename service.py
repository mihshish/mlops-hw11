"""Compatible service CLI. Stub and real models share the same FastAPI contract."""
import argparse
from pathlib import Path


def main():
    import uvicorn
    from api import create_app
    p=argparse.ArgumentParser()
    p.add_argument('--workspace',type=Path,default=Path('.lab'))
    p.add_argument('--port',type=int,default=8091)
    p.add_argument('--warmup-seconds',type=float,default=5)
    p.add_argument('--backend',choices=['stub','real'],default='stub')
    p.add_argument('--no-debug',action='store_true')
    args=p.parse_args()
    app=create_app(args.workspace,args.warmup_seconds,args.backend,debug=not args.no_debug)
    uvicorn.run(app,host='127.0.0.1',port=args.port,workers=1,log_level='warning')


if __name__=='__main__': main()
