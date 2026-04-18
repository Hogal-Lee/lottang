#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
동행복권 당첨 판매점 스크래핑 (Playwright 헤드리스 브라우저)
→ 카카오 지오코딩 → stores_clean.geojson 생성

Usage:
  # 기본 (최근 100회차)
  python scripts/build_stores.py --kakao-rest-key KEY

  # 전체 이어받기 (중단 후 재시작 가능)
  python scripts/build_stores.py --kakao-rest-key KEY --draws 200 --resume

  # 특정 회차 HTML 저장 (선택자 디버그용)
  python scripts/build_stores.py --kakao-rest-key KEY --debug-draw 1220
"""
import os, re, json, time, random, csv, argparse, socket
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

import requests
from lxml import html
from playwright.sync_api import sync_playwright, Page

STORE_URL  = "https://www.dhlottery.co.kr/store.do?method=topStore&pageGubun=L645&drwNo={drwNo}"
LOTTO_API  = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={drwNo}"
MAIN_URL   = "https://www.dhlottery.co.kr/common.do?method=main"
KAKAO_GEO  = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KW   = "https://dapi.kakao.com/v2/local/search/keyword.json"

AVG_DAYS_PER_MONTH = 30.4375
BATCH_SIZE  = 10    # 이 수만큼 요청 후 긴 휴식
BATCH_PAUSE = (40, 70)   # 배치 간 휴식 (초, 랜덤 범위)
REQ_DELAY   = (3.0, 6.5) # 요청 간 딜레이


# ── 연결 확인 ────────────────────────────────────────────────────────
def check_connection() -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(("www.dhlottery.co.kr", 443))
        s.close()
        return True
    except Exception:
        return False


# ── 회차 날짜 (Playwright 페이지에서 직접 추출) ───────────────────────
def extract_draw_date(content: str) -> str:
    """페이지 HTML에서 추첨일 추출 (여러 패턴 시도)"""
    patterns = [
        r'(\d{4})\.\s*(\d{2})\.\s*(\d{2})',  # 2024.03.16
        r'(\d{4})-(\d{2})-(\d{2})',            # 2024-03-16
        r'추첨일[^\d]*(\d{4})[./](\d{2})[./](\d{2})',
    ]
    for pat in patterns:
        m = re.search(pat, content)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


# ── 최신 회차 계산 ────────────────────────────────────────────────────
def get_latest_draw() -> int:
    base = date(2002, 12, 7)
    return 1 + (date.today() - base).days // 7


# ── 스크래핑 (Playwright) ─────────────────────────────────────────────
def scrape_draw(page: Page, drw_no: int) -> Tuple[List[dict], str]:
    url = STORE_URL.format(drwNo=drw_no)
    page.goto(url, timeout=45000, wait_until="networkidle")
    try:
        page.wait_for_selector("table", timeout=10000)
    except Exception:
        pass
    time.sleep(random.uniform(0.5, 1.5))

    content = page.content()
    draw_date = extract_draw_date(content)

    doc = html.fromstring(content)
    rows = []

    # 선택자 우선순위: tbl_data → tbl_list → 모든 table
    tables = (doc.cssselect("table.tbl_data") or
              doc.cssselect("table.tbl_list") or
              doc.cssselect("table"))

    for t in tables:
        head = " ".join(t.xpath(".//caption//text()") + t.xpath(".//th//text()"))
        rank_hint = 1 if "1등" in head else (2 if "2등" in head else 0)
        if rank_hint == 0 and "판매점" not in head and "당첨" not in head:
            continue
        for tr in t.xpath(".//tbody/tr"):
            tds = ["".join(td.xpath(".//text()")).strip() for td in tr.xpath("./td")]
            if len(tds) < 3:
                continue
            rank = rank_hint
            for cell in tds:
                if "1등" in cell: rank = 1
                elif "2등" in cell: rank = 2
            if rank in (1, 2):
                rows.append({"draw": drw_no, "date": draw_date,
                             "rank": rank, "name": tds[0], "address": tds[2]})
    return rows, draw_date


# ── 진행상황 저장/로드 ────────────────────────────────────────────────
def load_progress(path: str) -> Tuple[List[dict], set]:
    if not os.path.exists(path):
        return [], set()
    rows = []
    done = set()
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
            done.add(int(r["draw"]))
    return rows, done


def save_progress(path: str, rows: List[dict]):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["draw","date","rank","name","address"])
        w.writeheader()
        w.writerows(rows)


# ── 지오코딩 ─────────────────────────────────────────────────────────
def geocode(address: str, rest_key: str, name: str = "") -> Optional[Tuple[float, float]]:
    headers = {"Authorization": f"KakaoAK {rest_key}"}
    for url, params in [
        (KAKAO_GEO, {"query": address, "size": 1}),
        (KAKAO_KW,  {"query": f"{name} {address}", "size": 1}),
    ]:
        if not name and url == KAKAO_KW:
            continue
        try:
            r = requests.get(url, headers=headers, params=params, timeout=5)
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
        if last_date is None or d > last_date: last_date = d
    return {"score": round(score, 6), "win1": int(win1), "win2": int(win2),
            "last_win_date": last_date.isoformat() if last_date else None}


# ── 메인 ─────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--kakao-rest-key", required=True)
    p.add_argument("--draws", type=int, default=100, help="수집할 최근 회차 수")
    p.add_argument("--resume", action="store_true", help="이전 진행상황 이어받기")
    p.add_argument("--out", default="data/stores_clean.geojson")
    p.add_argument("--debug-draw", type=int, default=0,
                   help="지정 회차 HTML을 debug_draw.html로 저장 후 종료")
    args = p.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path  = os.path.join(repo_root, args.out)
    progress_path = os.path.join(repo_root, "data", "wins_raw.csv")
    today = date.today()

    # ── 연결 확인
    print("[0] 동행복권 서버 연결 확인…")
    if not check_connection():
        print("    연결 실패 (IP 차단 중). 나중에 다시 시도하세요.")
        return
    print("    연결 OK")

    latest = get_latest_draw()
    start_draw = max(1, latest - args.draws + 1)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="ko-KR",
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        print("[1] 메인 페이지 방문 (세션/쿠키 획득)…")
        page.goto(MAIN_URL, timeout=35000, wait_until="domcontentloaded")
        time.sleep(random.uniform(2, 4))

        # ── 디버그 모드
        if args.debug_draw:
            print(f"[DEBUG] {args.debug_draw}회차 HTML 저장…")
            page.goto(STORE_URL.format(drwNo=args.debug_draw),
                      timeout=40000, wait_until="networkidle")
            try: page.wait_for_selector("table", timeout=10000)
            except Exception: pass
            debug_path = os.path.join(repo_root, "debug_draw.html")
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"    저장됨: {debug_path}")
            browser.close()
            return

        # ── 진행상황 로드
        saved_rows, done_draws = load_progress(progress_path) if args.resume else ([], set())
        all_wins = list(saved_rows)
        pending = [d for d in range(start_draw, latest + 1) if d not in done_draws]
        print(f"[2] 스크래핑: {start_draw}~{latest}회 (미완료 {len(pending)}회차)")

        for i, drw in enumerate(pending, 1):
            try:
                rows, ddate = scrape_draw(page, drw)
                all_wins.extend(rows)
                print(f"  {drw:4d}회 ({ddate or '날짜미확인'}): {len(rows)}개")
                done_draws.add(drw)
                # 10회마다 진행상황 저장
                if i % 10 == 0:
                    save_progress(progress_path, all_wins)
            except Exception as e:
                short = str(e)[:80]
                print(f"  {drw:4d}회 오류: {short}")

            # 배치 완료 후 긴 휴식
            if i % BATCH_SIZE == 0 and i < len(pending):
                pause = random.uniform(*BATCH_PAUSE)
                print(f"  … 배치 휴식 {pause:.0f}초 …")
                time.sleep(pause)
            else:
                time.sleep(random.uniform(*REQ_DELAY))

        browser.close()

    save_progress(progress_path, all_wins)
    print(f"\n    총 수집: {len(all_wins)}건 (wins_raw.csv 저장)")

    if not all_wins:
        print("[ERROR] 수집 데이터 없음. --debug-draw 1220 으로 HTML 구조 확인 권장.")
        return

    # ── 지오코딩
    print("\n[3] 지오코딩…")
    store_map: Dict[str, dict] = {}
    for row in all_wins:
        key = re.sub(r"\s+", "", (row["name"] or "")) + "|" + re.sub(r"\s+", "", (row["address"] or ""))
        if key not in store_map:
            store_map[key] = {"name": row["name"], "address": row["address"],
                              "store_id": f"store-{len(store_map)+1:05d}", "events": []}
        try:
            d = datetime.strptime(str(row["date"]).strip(), "%Y-%m-%d").date()
            store_map[key]["events"].append((d, int(row["rank"])))
        except Exception:
            pass

    total = len(store_map)
    print(f"    고유 매장: {total}개")
    features, failed = [], []
    for i, (_, store) in enumerate(store_map.items(), 1):
        coords = geocode(store["address"], args.kakao_rest_key, store["name"])
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
        if i % 20 == 0 or i == total:
            print(f"  {i}/{total}  성공 {len(features)} / 실패 {len(failed)}")
        time.sleep(0.07)

    # ── 저장
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f,
                  ensure_ascii=False, indent=2)

    print(f"\n[4] 완료: {out_path}")
    print(f"    매장 {len(features)}개 저장 / 좌표 실패 {len(failed)}개")


if __name__ == "__main__":
    main()
