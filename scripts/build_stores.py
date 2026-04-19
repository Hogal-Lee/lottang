#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
동행복권 JSON API → 카카오 지오코딩 → stores_clean.geojson 생성

Usage:
  python scripts/build_stores.py --kakao-rest-key KEY
  python scripts/build_stores.py --kakao-rest-key KEY --draws 200 --resume
"""
import os, re, json, time, random, csv, argparse
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

import requests

BASE          = "https://www.dhlottery.co.kr"
EPSD_API      = BASE + "/lt645/selectLtEpsdInfo.do"
WN_SHP_API    = BASE + "/wnprchsplcsrch/selectLtWnShp.do"
KAKAO_GEO     = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KW      = "https://dapi.kakao.com/v2/local/search/keyword.json"
AVG_DAYS_PER_MONTH = 30.4375

SESS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.dhlottery.co.kr/wnprchsplcsrch/home",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}


# ── 세션 (쿠키 유지) ──────────────────────────────────────────────────
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(SESS_HEADERS)
    try:
        s.get(BASE + "/wnprchsplcsrch/home", timeout=15)
        time.sleep(random.uniform(1, 2))
    except Exception:
        pass
    return s


# ── 회차 목록 ─────────────────────────────────────────────────────────
def fetch_episodes(sess: requests.Session) -> List[dict]:
    """반환: [{"ltEpsd": 1219, "ltRflYmd": "20260411"}, ...]"""
    r = sess.get(EPSD_API, params={"_": int(time.time()*1000)}, timeout=15)
    r.raise_for_status()
    return r.json()["data"]["list"]


# ── 판매점 목록 (회차별) ──────────────────────────────────────────────
def fetch_stores(sess: requests.Session, epsd: int, rank: int) -> List[dict]:
    """rank: 1 또는 2"""
    params = {
        "srchWnShpRnk": f"rank{rank}",
        "srchLtEpsd": epsd,
        "srchShpLctn": "",
        "_": int(time.time()*1000),
    }
    r = sess.get(WN_SHP_API, params=params, timeout=15)
    r.raise_for_status()
    data = r.json().get("data", {})
    return data.get("list", [])


def build_address(item: dict) -> str:
    parts = [
        item.get("tm1ShpLctnAddr", ""),
        item.get("tm2ShpLctnAddr", ""),
        item.get("tm3ShpLctnAddr", ""),
    ]
    return " ".join(p for p in parts if p).strip()


# ── 진행상황 CSV ──────────────────────────────────────────────────────
def load_progress(path: str) -> Tuple[List[dict], set]:
    if not os.path.exists(path):
        return [], set()
    rows, done = [], set()
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
            done.add(int(r["draw"]))
    return rows, done


def save_progress(path: str, rows: List[dict]):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["draw", "date", "rank", "name", "address"])
        w.writeheader()
        w.writerows(rows)


# ── 지오코딩 ─────────────────────────────────────────────────────────
def geocode(address: str, name: str, rest_key: str) -> Optional[Tuple[float, float]]:
    headers = {"Authorization": f"KakaoAK {rest_key}"}
    for url, q in [(KAKAO_GEO, address), (KAKAO_KW, f"{name} {address}")]:
        try:
            r = requests.get(url, headers=headers,
                             params={"query": q, "size": 1}, timeout=5)
            if r.ok:
                docs = r.json().get("documents", [])
                if docs:
                    return float(docs[0]["x"]), float(docs[0]["y"])
        except Exception:
            pass
    return None


# ── 점수 계산 ─────────────────────────────────────────────────────────
def compute_score(events: List[Tuple[date, int]], today: date) -> dict:
    score = win1 = win2 = 0.0
    last_date = None
    for d, rank in events:
        w = 0.5 ** ((today - d).days / AVG_DAYS_PER_MONTH / 12.0)
        score += (5 if rank == 1 else 1) * w
        if rank == 1: win1 += 1
        else: win2 += 1
        if last_date is None or d > last_date:
            last_date = d
    return {"score": round(score, 6), "win1": int(win1), "win2": int(win2),
            "last_win_date": last_date.isoformat() if last_date else None}


# ── 메인 ─────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--kakao-rest-key", required=True)
    p.add_argument("--draws", type=int, default=100, help="수집할 최근 회차 수")
    p.add_argument("--resume", action="store_true", help="이전 진행상황 이어받기")
    p.add_argument("--out", default="data/stores_clean.geojson")
    args = p.parse_args()

    repo_root     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path      = os.path.join(repo_root, args.out)
    progress_path = os.path.join(repo_root, "data", "wins_raw.csv")
    today         = date.today()

    print("[1/4] 세션 초기화 및 회차 목록 조회…")
    sess = make_session()
    try:
        episodes = fetch_episodes(sess)
    except Exception as e:
        print(f"    회차 목록 조회 실패: {e}")
        return

    episodes = episodes[:args.draws]
    print(f"    최신 {len(episodes)}회차 수집 예정 "
          f"({episodes[-1]['ltEpsd']}~{episodes[0]['ltEpsd']}회)")

    print("\n[2/4] 당첨 판매점 수집…")
    saved_rows, done_draws = load_progress(progress_path) if args.resume else ([], set())
    all_wins = list(saved_rows)

    for i, ep in enumerate(episodes, 1):
        epsd   = int(ep["ltEpsd"])
        ymd    = ep.get("ltRflYmd", "")
        d_str  = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}" if len(ymd) == 8 else ""

        if epsd in done_draws:
            continue

        new_rows = []
        try:
            for rank in (1, 2):
                stores = fetch_stores(sess, epsd, rank)
                for s in stores:
                    new_rows.append({
                        "draw":    epsd,
                        "date":    d_str,
                        "rank":    rank,
                        "name":    s.get("shpNm", ""),
                        "address": build_address(s),
                    })
            all_wins.extend(new_rows)
            done_draws.add(epsd)
            print(f"  {epsd:4d}회 ({d_str}): 1등 {sum(1 for r in new_rows if int(r['rank'])==1)}개 "
                  f"/ 2등 {sum(1 for r in new_rows if int(r['rank'])==2)}개")
        except Exception as e:
            print(f"  {epsd:4d}회 오류: {e}")

        if i % 20 == 0:
            save_progress(progress_path, all_wins)

        time.sleep(random.uniform(0.5, 1.5))

    save_progress(progress_path, all_wins)
    print(f"\n    총 수집: {len(all_wins)}건")

    if not all_wins:
        print("[ERROR] 수집 데이터 없음.")
        return

    # ── 지오코딩
    print("\n[3/4] 지오코딩…")
    store_map: Dict[str, dict] = {}
    for row in all_wins:
        key = re.sub(r"\s+", "", row["name"]) + "|" + re.sub(r"\s+", "", row["address"])
        if key not in store_map:
            store_map[key] = {"name": row["name"], "address": row["address"],
                              "store_id": f"store-{len(store_map)+1:05d}", "events": []}
        try:
            d = datetime.strptime(row["date"], "%Y-%m-%d").date()
            store_map[key]["events"].append((d, int(row["rank"])))
        except Exception:
            pass

    total = len(store_map)
    print(f"    고유 매장: {total}개")
    features, failed = [], []
    for i, (_, store) in enumerate(store_map.items(), 1):
        coords = geocode(store["address"], store["name"], args.kakao_rest_key)
        if not coords:
            failed.append(store["name"])
            continue
        scores = compute_score(store["events"], today)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": list(coords)},
            "properties": {"store_id": store["store_id"], "name": store["name"],
                           "address": store["address"], **scores},
        })
        if i % 50 == 0 or i == total:
            print(f"  {i}/{total}  성공 {len(features)} / 실패 {len(failed)}")
        time.sleep(0.07)

    # ── 저장
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features},
                  f, ensure_ascii=False, indent=2)

    print(f"\n[4/4] 완료: {out_path}")
    print(f"    매장 {len(features)}개 / 좌표 실패 {len(failed)}개")


if __name__ == "__main__":
    main()
