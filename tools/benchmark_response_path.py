"""Explicit synthetic inference calls vs local routing; never executes devices.

No Astra, no OpenRouter credits, no configuration changes. The actual executor,
transport, transcription and TTS are excluded from decision-time comparisons.
"""
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import comandos_rapidos


def run():
    spec=importlib.util.spec_from_file_location('bench',ROOT/'tools/benchmark_haiku_openrouter.py')
    bench=importlib.util.module_from_spec(spec);spec.loader.exec_module(bench)
    rows=[]
    # Same simulated tool as preceding baseline. No executor is attached.
    key=json.loads((Path.home()/'.config/emily-cloud-oracle/inference-key.json').read_text())['key']
    with httpx.Client(base_url='https://emily-hiucksam.duckdns.org/v1',
        timeout=httpx.Timeout(45,connect=10),headers={'Authorization':'Bearer '+key}) as client:
        for case in bench.CASES:
            body=bench.payload(case,'low');body.pop('provider');body.pop('reasoning')
            body['model']='kr/claude-haiku-4.5';body['reasoning_effort']='low'
            result=bench.measure(client,body)
            row={'case':case[0],**result}
            rows.append(row)
            print(json.dumps({k:row.get(k) for k in ['case','ok','tool_ready_s','first_text_s','total_s'] }),flush=True)
            if not result['ok']: break
    local=[]
    for text in ['abre a calculadora','Emily, abre o Discord!','abra o Spotify no PC']:
        times=[]
        for _ in range(1000):
            start=time.perf_counter();action=comandos_rapidos.parse(text);times.append((time.perf_counter()-start)*1000)
            assert action
        local.append({'text':text,'median_ms':statistics.median(times),'p95_ms':sorted(times)[949]})
    destination=ROOT/'output/response-speed-2026-10-09/measurements.json'
    destination.write_text(json.dumps({'model_low':rows,'pc_direct_routing':local,
        'scope':'Model+transport decision vs local recognition only. Not total action latency; no real actions.'},ensure_ascii=False,indent=2))
    print(destination)


if __name__=='__main__':run()
