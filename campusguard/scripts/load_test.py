"""Synthetic authorized scan load only. Run against a disposable deployment."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
import statistics
import time
from uuid import uuid4
import requests
from clients.settings import base_url


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--requests',type=int,default=100)
    parser.add_argument('--concurrency',type=int,default=8)
    parser.add_argument('--confirm-disposable-target',action='store_true')
    parser.add_argument('--output',default='load-results.json')
    args=parser.parse_args()
    if not args.confirm_disposable_target or not 1 <= args.requests <= 100000 or not 1 <= args.concurrency <= 64:
        raise SystemExit('Confirm a disposable deployment and use bounded request/concurrency values')
    url=base_url()
    headers={'x-terminal-uuid':os.environ['TERMINAL_UUID'],'x-api-token':os.environ['TERMINAL_API_TOKEN']}
    def send(_):
        payload={'event_id':str(uuid4()),'occurred_at':datetime.now(timezone.utc).isoformat(),
                 'direction':os.environ.get('TERMINAL_DIRECTION','IN'),'embedding':[0.0]*128}
        start=time.perf_counter()
        try:
            response=requests.post(url+'/api/v1/gate/verify-face',headers=headers,json=payload,timeout=(5,30),allow_redirects=False)
            return time.perf_counter()-start,response.status_code
        except requests.RequestException:
            return time.perf_counter()-start,0
    start=time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results=list(executor.map(send,range(args.requests)))
    elapsed=time.perf_counter()-start
    durations=sorted(t for t,_ in results)
    statuses={str(code):sum(s==code for _,s in results) for code in sorted({s for _,s in results})}
    report={'type':'synthetic embeddings; no camera/accuracy validation','requests':args.requests,'concurrency':args.concurrency,
            'elapsed_seconds':elapsed,'requests_per_second':args.requests/elapsed,'p50_seconds':statistics.median(durations),
            'p95_seconds':durations[min(len(durations)-1,int(len(durations)*.95))],'statuses':statuses}
    from pathlib import Path
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if any(s!=200 for _,s in results):
        raise SystemExit(1)


if __name__=='__main__': main()
