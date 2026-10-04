import argparse, json, math, os, platform, statistics, time, urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--runs',type=int,default=100);args=p.parse_args()
if args.runs<1: p.error('--runs must be positive')
root=Path(__file__).resolve().parents[1]
settings={}
if (root/'.env').exists():
    for line in (root/'.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key,value=line.split('=',1);settings[key.strip()]=value.strip()
url='http://127.0.0.1:'+os.environ.get('LAYA_PORT',settings.get('LAYA_PORT','30765'))
cases=json.loads((Path(__file__).parent.parent/'examples/cases.json').read_text())
def call(case):
    payload={'model':'multilingual','state':case['text'],'max_len':512,'questions':{'category':{'type':'choice','instructions':'Classify this support request.','criteria':{'billing':'Payment, invoice, refund','technical':'Software crashes and application errors','account':'Login, password and account access'}}}}
    req=urllib.request.Request(url+'/v1/systemone',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    t=time.perf_counter()
    with urllib.request.urlopen(req,timeout=60) as r: out=json.load(r)
    return (time.perf_counter()-t)*1000,out
for i in range(5):call(cases[i%len(cases)])
rows=[]
for i in range(args.runs):
    c=cases[i%len(cases)]; ms,out=call(c)
    answer=out.get('answers',{}).get('category',{}).get('choice')
    rows.append({'case':c['id'],'ms':round(ms,3),'expected':c['expected'],'actual':answer,'correct':answer==c['expected'],'usage':out.get('usage')})
    if (i+1)%10==0:print(f'{i+1}/{args.runs}',flush=True)
ts=sorted(r['ms'] for r in rows)
summary={'timestamp':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'host':platform.node(),'threads':os.environ.get('LAYA_THREADS',settings.get('LAYA_THREADS')),'runs':len(rows),'warmups':5,'p50_ms':statistics.median(ts),'p95_ms':ts[math.ceil(.95*len(ts))-1],'correct':sum(r['correct'] for r in rows),'note':'Repeated six-case smoke workload, NOT a general accuracy evaluation. HTTP end-to-end; excludes model load.','rows':rows}
path=(root/'reports')/('benchmark-'+time.strftime('%Y%m%d-%H%M%S')+'.json');path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False,indent=2));print(path)
