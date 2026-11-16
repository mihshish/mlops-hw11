"""Generate HTML and SVG plots only from retained observations, never invented samples."""
from collections import Counter, defaultdict
from html import escape
import json
import math
from pathlib import Path
from hw11.balance import percentile

ROOT=Path("results")
PLOT=ROOT/"plots"
def obj(name,default):
    p=ROOT/name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
def lines(name):
    p=ROOT/name
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []

def chart(name,title,xlabel,ylabel,series,events=()):
    series={label:[(x,y) for x,y in pts if y is not None and math.isfinite(y)] for label,pts in series.items()}
    series={label:pts for label,pts in series.items() if pts}
    if not series:return ""
    points=[p for pts in series.values() for p in pts]
    x0=min(x for x,y in points);x1=max(x for x,y in points)
    y1=max(y for x,y in points)*1.08 or 1
    fx=lambda x:75+ (x-x0)/(x1-x0 or 1)*700
    fy=lambda y:315-y/y1*235
    pal=["#155eaa","#b33c2c","#268268","#7752a8","#974905","#005f67","#37474f","#a3156e"]
    svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 850 475" role="img">','<rect width="850" height="475" fill="#fff"/>',
         f'<text x="24" y="30" font-size="20">{escape(title)}</text>',
         f'<text x="10" y="62" font-size="12">{escape(ylabel)}</text>',
         f'<text x="370" y="365" font-size="14">{escape(xlabel)}</text>']
    for i in range(6):
        y=y1*i/5;x=x0+(x1-x0)*i/5
        svg.extend([f'<path d="M75 {fy(y)} H775" stroke="#e4e9ef"/>',
                    f'<text x="15" y="{fy(y)+4}" font-size="12">{y:.2f}</text>',
                    f'<text x="{fx(x)-9}" y="337" font-size="11">{x:.1f}</text>'])
    for x,label in events:
        if x0<=x<=x1:
            svg.extend([f'<path d="M{fx(x)} 77 V315" stroke="#9b9faa" stroke-dasharray="3 4"/>',
                        f'<text x="{fx(x)}" y="307" font-size="9" transform="rotate(-90 {fx(x)} 307)">{escape(label)}</text>'])
    for i,(label,pts) in enumerate(series.items()):
        c=pal[i%len(pal)]
        svg.append(f'<polyline points="'+" ".join(f"{fx(x):.2f},{fy(y):.2f}" for x,y in pts)+f'" fill="none" stroke="{c}" stroke-width="2"/>')
        for x,y in pts:
            if len(pts)<55:svg.append(f'<circle cx="{fx(x):.2f}" cy="{fy(y):.2f}" r="2.5" fill="{c}"/>')
        svg.append(f'<text x="{40+i%2*410}" y="{395+i//2*18}" fill="{c}" font-size="12">{escape(label)}</text>')
    svg.append("</svg>")
    PLOT.mkdir(parents=True,exist_ok=True);(PLOT/name).write_text("\n".join(svg),encoding="utf-8")
    return f'<figure><img src="results/plots/{name}" alt="{escape(title)}"><figcaption>{escape(title)}</figcaption></figure>'

def table(headers,rows):
    return '<table><thead><tr>'+''.join(f'<th>{escape(str(x))}</th>' for x in headers)+'</tr></thead><tbody>'+''.join(
        '<tr>'+''.join(f'<td>{escape(str(f"{x:.3f}" if isinstance(x,float) else x if x is not None else "—"))}</td>' for x in row)+'</tr>'
        for row in rows)+'</tbody></table>'

def main():
    a=obj("a-summary.json",{}); traces=[r for r in lines("a-timeline.jsonl") if "pods" in r]
    balance=obj("balance-summary.json",[])
    c=[r for r in lines("c-timeline.jsonl") if "pods" in r]
    ctraffic=lines("c-requests.jsonl")
    check=obj("checks.json",[]); env=obj("environment-initial.json",{})
    before=obj("preflight.json",{})
    findings=obj("measured-findings.json",{})
    footprint=obj("container-disk.json",{})
    changes=obj("stand-network-smoke.json",[])
    install_fix=obj("hpa-install-fix.json",{})
    if traces:
        t0=traces[0]["time"]
        ga=chart("a-ready.svg","A · Ready, EndpointSlice и rollout", "с от начала", "реплики",
            {"Pod Ready":[(r["time"]-t0,sum(p["ready"] for p in r["pods"])) for r in traces],
             "EndpointSlice ready":[(r["time"]-t0,sum(bool(e.get("ready")) for e in r["endpoints"])) for r in traces],
             "B Ready":[(r["time"]-t0,sum(p["ready"] and p["version"]=="B" for p in r["pods"])) for r in traces]},
            [(r["time"]-t0,r["phase"]) for r in obj("a-events.json",[])])
    else:ga=""
    rows=[]; series=defaultdict(list)
    for phase in balance:
        outcomes=phase["outcomes"]
        rows.append((phase["run"],phase["n"],phase["sent"],phase["completed"],outcomes.get("rejected",0),
            outcomes.get("aborted",0),outcomes.get("timeout",0),outcomes.get("http_error",0)+outcomes.get("transport_error",0),
            (100*(phase["sent"]-phase["completed"])/phase["sent"]) if phase["sent"] else None,
            phase["ttfc_p50"],phase["ttfc_p95"],phase["full_p50"],phase["full_p95"],phase["send_lag_p95"],
            ", ".join(f"{p[-5:]}={v['n']}" for p,v in phase["by_pod"].items())))
        series[f'{phase["pattern"]}/{phase["policy"]}'].append((phase["repeat"],phase["ttfc_p95"]))
    gb=chart("b-policies.svg","B · клиентский p95 TTFC: три прогона каждой комбинации","номер повтора","секунды",dict(series))
    selected=next((r for r in balance if r["pattern"]=="skew" and r["policy"]=="sticky"),None)
    gq=""
    if selected:
        raw=[r for r in lines(selected["run"]+".jsonl") if r["outcome"]=="completed"]
        buckets=defaultdict(list)
        for r in raw:buckets[(r["pod"],int((r["sent_wall"]-selected["start_unix"])/10)*10)].append(r)
        pairs=defaultdict(list)
        for (pod,t),v in sorted(buckets.items()):
            pairs[pod+" TTFC p95"].append((t,percentile([x["ttfc_seconds"] for x in v],.95)))
            pairs[pod+" queue p95"].append((t,percentile([x["queue_seconds"] for x in v],.95)))
        gq=chart("b-pods.svg","B · перекос 80%, ClientIP — интервалы по 10 с","секунды с начала нагрузки","секунды",dict(pairs))
    gc=""
    if c:
        t0=c[0]["time"]; cp=Counter(int((r["planned_wall"]-t0)//5)*5 for r in ctraffic)
        gc=chart("c-hpa.svg","C · CPU HPA, плановая нагрузка и готовые Pod","секунды с начала","Pod / запланированных запросов в секунду",
           {"Созданные Pod":[(r["time"]-t0,len(r["pods"])) for r in c],
            "Ready Pod":[(r["time"]-t0,sum(p["ready"] for p in r["pods"])) for r in c],
            "Плановая нагрузка (запр/с)":[(r["time"]-t0,cp[int((r["time"]-t0)//5)*5]/5) for r in c]})
    state_rows=[]
    for row in c:
        for event in row.get("alerts",[]):
            key=(event["name"],event["state"])
            if key not in {v[:2] for v in state_rows}:state_rows.append((*key,row["phase"],row["time"]))
    summary=obj("prom-v-client.json",[])
    metrics=table(("Прогон","Мера","Клиент n","Prom n","Клиент p95, с","Prom p95, с"),
      [(result["run"],measure,d["client_count"],d["prom_count"],d["client_p95"],d["prom_p95"])
       for result in summary for measure,d in result["results"].items()]) if summary else "<p>Одинаковое окно пока не измерено.</p>"
    hpa_counts=[len(r["pods"]) for r in c if r["phase"].startswith("balanced_cpu")]
    hpa_cycle=bool(hpa_counts and hpa_counts[0]==2 and 3 in hpa_counts and hpa_counts[-1]==2)
    alert_states={(r[0],r[1]) for r in state_rows}
    alerts_ok=all((n,s) in alert_states for n in ("HighTTFC","HighRejectionRate") for s in ("pending","firing"))
    completed=a and len(balance)==12 and hpa_cycle and alerts_ok and len(check)==5 and len(summary)==12
    status=("Основные опыты подтверждены сохранёнными данными" if completed else
        "Незавершённая сдача: нет полного комплекта фактических опытов Kubernetes")
    a_text=(table(("Результат A","Значение"),[(k,v) for k,v in a.items() if k!="long_stream"]) if a else
          "<p>Проверено только на localhost, без Kubernetes: сломанная проба открывает холодный backend, исправленная возвращает 503 до прогрева, несовместимый SHA не допускает Ready. Rollout, EndpointSlice, откат и SIGKILL не засчитаны без журналов.</p>")
    if a:
        stream=a["long_stream"]
        a_text+=(f'<p>Контрольный поток: {stream["chunks"]} частей за {stream["total_seconds"]:.2f} с, '
                 f'версия {escape(stream["version"])}. Запрос начался до выката и закончился после его начала. '
                 '<a href="results/a-requests.jsonl">Все попытки</a> · '
                 '<a href="results/a-timeline.jsonl">Ready и EndpointSlice</a>.</p>')
    b_text=(table(("Прогон","План","Отпр.","200+done","4xx","Оборв.","Тайм-аут","Др. ошибки","Неуспех, %","TTFC p50","TTFC p95","Full p50","Full p95","Отстав. p95, с","Распред."),rows)
      if rows else "<p>Нагрузочные замеры отсутствуют. Тесты проверили расписание 25/25/25/25 и 80/6,7/6,7/6,7, но это не доказательство распределения по Pod.</p>")
    group_rows=[]
    for name,v in findings.get("balance",{}).get("grouped",{}).items():
        group_rows.append((name,v["repeats"],v["median_p95_ttfc"],v["median_p95_queue"],
          v["median_loss_fraction"],v["median_hottest_share"],v["median_hit_fraction"],v["total_hot_with_capacity_samples"]))
    by_policy=(table(("Политика / профиль","Повторы","Медиана p95 TTFC, с","Медиана p95 очереди, с","Доля неуспеха","Доля самого горячего Pod","Доля hit","Сэмплы: ожидание при свободных слотах"),group_rows)
               if group_rows else "")
    groups=findings.get("balance",{}).get("grouped",{})
    b_decision=""
    if all(g in groups and groups[g]["repeats"]==3 for g in ("skew/sticky","skew/balanced")):
        s=groups["skew/sticky"];b=groups["skew/balanced"]
        if b["median_loss_fraction"] < s["median_loss_fraction"] and b["median_p95_ttfc"] < s["median_p95_ttfc"]:
            b_decision=(f'<p><strong>Для перекоса 80% выбираем Service без ClientIP.</strong> Медиана p95 TTFC '
                        f'{s["median_p95_ttfc"]:.3f} → {b["median_p95_ttfc"]:.3f} с; медианная доля неуспеха '
                        f'{100*s["median_loss_fraction"]:.1f}% → {100*b["median_loss_fraction"]:.1f}%. '
                        f'Доля cache hit {100*s["median_hit_fraction"]:.1f}% → {100*b["median_hit_fraction"]:.1f}%. '
                        'Это результат коротких префиксов, помещающихся в оба LRU, а не обещание для GPU-сервиса.</p>')
        else:
            b_decision='<p>У этого набора нет одновременного выигрыша по p95 и отказам; нужен явный SLO и дополнительная проверка.</p>'
    c_details=[]
    c_transitions=[]
    for phase,v in findings.get("hpa",{}).items():
        for name,pod in v["new_pods"].items():
            c_details.append((phase,name,pod["created_seconds"],pod["ready_seconds"],
                              v["observed_return_after_last_planned_seconds"],str(v["ponames_and_counts"])))
        c_transitions.extend((phase,t["name"],t["before"],t["after"],t["seconds"]) for t in v["transitions"])
    c_text=(table(("Фаза","Новый Pod","Создан, с","Ready, с","Возврат через с после последнего планового","Запросы по Pod"),c_details)
            if c_details else "")
    if c_transitions:c_text+=table(("Фаза","Алерт","Из","В","Секунды от начала нагрузки"),c_transitions)
    sticky=findings.get("hpa",{}).get("sticky_cpu",{})
    if sticky:
        for name,pod in sticky["new_pods"].items():
            if pod["ready_seconds"] is None:
                continue
            n=sticky["ponames_and_counts"].get(name,0)
            c_text+=(f'<p>При ClientIP третий Pod создан через {pod["created_seconds"]:.1f} с и впервые '
                     f'наблюдался Ready через {pod["ready_seconds"]:.1f} с от начала нагрузки. '
                     f'От четырёх уже привязанных IP он получил {n} запросов. Порог считает среднее CPU '
                     'по репликам, тогда как ClientIP продолжает направлять запросы по старым привязкам.</p>')
    if install_fix:
        c_text+=(f'<p>При первом включении HPA Helm удалил поле replicas и Deployment кратко '
                 f'упал до {install_fix["original_install_min"]}. Этот участок сохранён, а чистый цикл 2→3→2 '
                 'виден на фазе ClientIP. Чарт теперь при включении HPA сохраняет живое значение replicas '
                 'и ждёт две Ready-реплики с CPU-метриками перед опытом. Отдельно повторно проверили само '
                 f'включение без нагрузки: минимум {install_fix["fixed_install_min"]}, имена Pod не изменились. '
                 '<a href="results/hpa-install-fix.json">Трасса контрольной проверки</a>.</p>')
    out=f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>ДЗ 11 · Kubernetes</title>
<style>body{{background:#f5f7fb;color:#17263b;font:16px/1.58 system-ui;margin:0}}main{{max-width:1160px;margin:auto;padding:35px}}
h1,h2{{line-height:1.2}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:7px;border-bottom:1px solid #d6e0ed;text-align:left}}
figure{{margin:20px 0}}img{{width:100%;max-width:850px}}a{{color:#175899}}.notice{{background:#fcebcf;padding:12px}}code{{overflow-wrap:anywhere}}</style></head>
<body><main><h1>ДЗ 11. Kubernetes под нагрузкой</h1><p class="notice"><strong>{status}</strong></p>
<h2>Стенд и инфраструктура</h2>
<p>Продолжение API из ДЗ 8–10. В образе только FastAPI/Uvicorn и CPU-имитатор, без весов, обучения и MLflow. Режим <code>backend_mode=simulated</code>. Два Pod, CPU request 100m / limit 500m, память 64/160 MiB. На Pod: 2 active, 4 waiting, LRU на 4 префикса; искусственная цена hit/miss 0,06/0,36 с, интервал частей 0,13 с.</p>
<p>Исходное состояние: Docker {escape(str(env.get("docker_engine","—")))}, около {env.get("initial_host_free_bytes",0)/2**30:.2f} GiB свободно, лимит Docker {env.get("docker_visible_memory_bytes",0)/2**30:.2f} GiB. kind действительно создал Ready control-plane. При импорте Grafana свободное место упало до {env.get("host_free_at_failure_bytes",0)/2**20:.0f} MiB; containerd вернул I/O error, BuildKit — EOF. Это блокировка первого запуска, не оценка размера стенда. Фактическое использование после успешного развёртывания собирает <code>hw11.collect</code>.</p>
<p>Повторный запуск: {before.get("free_bytes",0)/2**30:.2f} GiB свободно до развёртывания. На WSL2 отсутствовала поддержка iptables recent: сначала прямой Pod отвечал, оба Service — нет. Неудачные попытки и ошибка kube-proxy сохранены в <a href="results/diagnostics/iptables/">diagnostics/iptables</a>. Решение — отдельный IPv4 kind с прокси nftables, не изменение маршрутизации в самом API. Подтверждённых успешных smoke через Service: {sum(r.get("outcome")=="completed" for r in changes)} / 2.</p>
<p>Размер внутри узла по du: <code>{escape(footprint.get("node_used","не замерен"))}</code>. Это данные о занятом месте внутри контейнера kind, не оценка роста всей VHDX. Лимиты томов/время хранения заданы в чарте.</p>
<p>ConfigMap A/B неизменяемы; процесс сверяет SHA-256 содержимого и версию, а отвечает по фактически загруженной версии. Все ответы, включая фрагменты, содержат request ID, Pod и версию. request/session ID в логах, а не в метках Prometheus. Команды запуска и удаления — <a href="README-HW11.md">README-HW11</a>.</p>
<h2>A · Прогрев, rolling update, откат</h2>
<p>Гипотеза: проверка живого HTTP вместо прогретого backend преждевременно добавляет Pod в EndpointSlice. <code>make hw11-a</code> меняет только режим проб под одинаковой нагрузкой. Исправление: порог startup покрывает 20 с, readiness проверяет прогрев, liveness — процесс. Для rollout 1 surge / 0 unavailable, preStop 4 с, Uvicorn 35 с, grace 45 с; отдельный опыт форсированной остановки не обязан быть без потерь.</p>
{a_text}{ga}
<h2>B · Привязка и горячая реплика</h2>
<p>Гипотеза: ClientIP объединяет запросы одного клиента в одном Pod, даже если в другом есть место. <code>make hw11-b</code>: 4 клиента, 800 запланированных запросов за 120 с на прогон; четыре комбинации по три раза. Одинаковый payload и расписание для сравниваемых вариантов, отдельное TCP-соединение на запрос. Изначально префиксы каждого прогона холодные. Исправление для сравнения — убрать ClientIP, иначе сохранить локальность только как предпочтение. Если перекоса нет, проверяем IP и фактическую раскладку четырёх клиентов, а не удаляем неудобный прогон.</p>
{b_text}{by_policy}{b_decision}{gq}{gb}
<p>Свободная ёмкость в таблице — одновременно waiting &gt; 0 у самого загруженного Pod и running &lt; 2 у другого на одном 5-секундном сэмпле. Нулевой результат у отдельного повтора сохранён: это не доказательство отсутствия кратких всплесков между сэмплами. Сохраняем ClientIP только при проверенной выгоде локальности и контроле очереди.</p>
<h2>C · HPA и алерты</h2>
<p><code>make hw11-c</code>: resource metrics API, CPU HPA 2–3 по 65% requests, scale-down stabilization 45 с. Под нагрузкой работает CPU-цикл, а не только sleep. Среднее может скрыть горячий Pod, а новая реплика не перебивает существующую ClientIP-привязку. В правилах HighTTFC: p95 &gt; 0,8 с при ≥8 успешных за 30 с; HighRejectionRate: &gt;12% при ≥15 исходах; удержание 15 с. Отдельно нужны наблюдения pending, firing и возврата в норму.</p>
{table(("Алерт","Состояние","Фаза","UTC epoch"),state_rows) if state_rows else "<p>Реальный цикл 2→3→2 и переходы алертов пока не подтверждены.</p>"}
{c_text}{gc}
<h2>Перцентили и данные</h2>
<p>TTFC — монотонный интервал send→первый содержательный chunk, full — send→done; inter-chunk измеряется только между частями. Отсутствующий done — незавершённый поток даже при HTTP 200. Никаких TTFT, TPOT или tokens/s для имитатора. Клиентский p50/p95 интерполируется на отсортированных успешных запросах, численность и ошибки указываются отдельно. PromQL сохраняет le при агрегации по Pod, использует дельту накопленных bucket в известном окне и сравнивает n, а не предполагает одинаковый выбор. Гистограмма приближает перцентиль внутри bucket; клиент включает сеть.</p>
{metrics}
<h2>Проверки и ревью PR</h2>
<p>Локальные тесты HTTP-учёта и FastAPI — предварительная проверка, не замена живым Kubernetes-проверкам. Результаты <code>make hw11-verify</code>: {len(check)}/5 записано. Сценарии: прогрев/EndpointSlice, фактическая версия после отката, та же версия и полный диалог на заменившем Pod, изоляция сессий, отдельный учёт 4xx и оборванных ответов.</p>
<p><strong>Постоянную привязку не принимаю.</strong> При равных прочих затратах выбираю свободный B: ожидание префикса в A 3 с, пересчёт в B 0,8 с, ориентир выигрыша 2,2 с до одинакового decode. Это предварительный выбор: нужны возраст и ошибка оценки очереди, длина префикса, измеренная цена cache miss, остаток текущих генераций, запас KV-памяти, p95 и бюджет запроса. Допускаю запрос только в Ready-реплику с той же моделью и в ограниченную очередь; при превышении бюджета возвращаю 429 с ограниченным повтором клиента. Историю передаю с запросом либо храню за Pod; потеря A требует пересчёта, не потери диалога. Уже открытый поток не мигрирует: даём завершиться при drain, при аварии явно отмечаем обрыв; повтор отдельной попыткой с тем же прикладным идентификатором, не склеиваем частичные ответы.</p>
<p>Первичный кейс: <a href="https://cloud.google.com/blog/products/containers-kubernetes/how-gke-inference-gateway-improved-latency-for-vertex-ai">Google Cloud / Vertex AI: GKE Inference Gateway</a>. В этом кейсе команда повышала приоритет очереди относительно кеша, чтобы обходить горячие узлы. Это подтверждает идею совместного учёта очереди и локальности, но не переносит их ускорение на наш имитатор. Файл лекции 11 не предоставлен; принадлежность кейса к ней не подтверждена.</p>
<p><a href="https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/">Kubernetes probes</a> · <a href="https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/">HPA</a> · <a href="https://prometheus.io/docs/practices/histograms/">Prometheus histogram</a></p>
</main></body></html>"""
    Path("report.html").write_text(out,encoding="utf-8",newline="\n")
    print(status,flush=True)
if __name__=="__main__":main()
