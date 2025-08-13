
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, json
from datetime import datetime, date
from collections import defaultdict

AVG_DAYS_PER_MONTH = 30.4375

def parse_args():
    p = argparse.ArgumentParser(description="Compute A3 scores (event-wise half-life).")
    p.add_argument("--geojson", required=True)
    p.add_argument("--events", required=True)  # CSV with store_id,date,rank
    p.add_argument("--out-geojson", default="stores_clean.a3.geojson")
    p.add_argument("--out-summary", default="scores_a3_summary.csv")
    p.add_argument("--today", default=None)
    p.add_argument("--half-life-months", type=float, default=12.0)
    return p.parse_args()

def parse_date(s): return datetime.strptime(s.strip(), "%Y-%m-%d").date()

def read_events_csv(path):
    import csv
    ev = defaultdict(list)
    with open(path,"r",encoding="utf-8") as f:
        reader = csv.DictReader((row for row in f if not row.startswith("#")))
        for i,row in enumerate(reader, start=2):
            sid = row.get("store_id","").strip()
            if not sid: 
                # skip unmatched
                continue
            d = parse_date(row["date"])
            rank = int(row["rank"])
            ev[sid].append((d, rank))
    return ev

def months_elapsed(d1: date, d0: date) -> float:
    return (d1 - d0).days / AVG_DAYS_PER_MONTH

def compute_scores(features, events, today, half_life_months):
    out=[]
    for f in features:
        p=f["properties"]
        sid=p.get("store_id")
        evs=events.get(sid,[])
        score=0.0; win1=0; win2=0; last_date=None; r12_1=0; r12_2=0
        for d,rank in evs:
            months = months_elapsed(today, d)
            weight = 0.5 ** (months / half_life_months)
            base = 5 if rank==1 else 1
            score += base * weight
            if rank==1: win1 +=1
            else: win2 +=1
            if (today - d).days <= 365.25:
                if rank==1: r12_1 +=1
                else: r12_2 +=1
            if (last_date is None) or (d > last_date): last_date = d
        p["win1"]=win1; p["win2"]=win2; p["score"]=round(score,6)
        p["last_win_date"]= last_date.isoformat() if last_date else None
        p["recent12m_win1"]=r12_1; p["recent12m_win2"]=r12_2
        out.append({"store_id":sid,"win1":win1,"win2":win2,"a3_score":round(score,6),
                    "last_win_date": last_date.isoformat() if last_date else "",
                    "recent12m_win1":r12_1,"recent12m_win2":r12_2})
    return out

def main():
    args=parse_args()
    today = parse_date(args.today) if args.today else date.today()
    with open(args.geojson,"r",encoding="utf-8") as f: gj=json.load(f)
    feats=gj.get("features",[])
    ev=read_events_csv(args.events)
    summary=compute_scores(feats, ev, today, args.half_life_months)
    with open(args.out_geojson,"w",encoding="utf-8") as f: json.dump(gj,f,ensure_ascii=False)
    import csv
    with open(args.out_summary,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=list(summary[0].keys()) if summary else ["store_id","win1","win2","a3_score","last_win_date","recent12m_win1","recent12m_win2"])
        w.writeheader(); [w.writerow(r) for r in summary]
    print(f"[A3] Wrote: {args.out_geojson}, {args.out_summary}")

if __name__=="__main__":
    main()
