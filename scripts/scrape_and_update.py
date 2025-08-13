
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrape_and_update.py
- 매주 실행: 동행복권 1/2등 배출점 스크래핑 → wins.csv 갱신 → A3 점수 재계산 → GeoJSON/리포트 갱신
- 의존:
  - scripts/compute_a3_scores.py (A3 점수 계산)
  - data/stores_clean.geojson (기존 매장 좌표/ID 참조)
출력:
  - data/dhlottery_stores.csv (원시 수집 누적)
  - data/wins.csv (store_id 매칭된 이벤트)
  - data/stores_clean.a3.geojson (A3 반영본)
  - data/scores_a3_summary.csv
"""

import os, sys, time, csv, re, math, json
from dataclasses import dataclass, asdict
from typing import List, Tuple, Optional, Dict, Set
from datetime import datetime, date, timedelta

import requests
import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

BASE_URL = "https://www.dhlottery.co.kr/store.do?method=topStore&pageGubun=L645"
LOTTO_JSON = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={drwNo}"

@dataclass
class StoreRow:
    draw: int
    draw_date: str
    rank: int           # 1 or 2
    name: str
    choice_type: str
    address: str

def build_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,2000")
    options.add_argument("--lang=ko-KR")
    # GitHub Actions에 설치된 chrome 바이너리 경로 자동 인식
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def get_draw_date(drw_no: int) -> Optional[str]:
    try:
        r = requests.get(LOTTO_JSON.format(drwNo=drw_no), timeout=10)
        if r.ok:
            j = r.json()
            d = j.get("drwNoDate")
            if d:
                return d  # 'YYYY-MM-DD'
    except Exception:
        pass
    return None

def click_tab_if_exists(driver, labels: List[str]) -> bool:
    try:
        elements = driver.find_elements(By.XPATH, "//*[self::a or self::button or self::li or self::span]")
        for el in elements:
            t = el.text.strip()
            for lab in labels:
                if lab in t:
                    driver.execute_script("arguments[0].click();", el)
                    time.sleep(0.4)
                    return True
    except Exception:
        pass
    return False

def collect_rows_on_current_view(driver, rank_num: int) -> List[Tuple[str,str,str]]:
    rows: List[Tuple[str,str,str]] = []
    # 테이블 기반
    try:
        trs = driver.find_elements(By.CSS_SELECTOR, "table.tbl_data tbody tr")
        for tr in trs:
            tds = tr.find_elements(By.CSS_SELECTOR, "td")
            if len(tds) >= 3:
                name = tds[0].text.strip()
                choice = tds[1].text.strip()
                addr = tds[2].text.strip()
                rows.append((name, choice, addr))
    except Exception:
        pass
    # 카드형
    if not rows:
        try:
            lis = driver.find_elements(By.CSS_SELECTOR, "ul.list_map li")
            for li in lis:
                txt = li.text.strip().splitlines()
                txt = [t.strip() for t in txt if t.strip()]
                name = txt[0] if txt else ""
                choice = ""
                addr = ""
                for t in txt:
                    if any(k in t for k in ("자동","반자동","수동")):
                        choice = t; break
                cand = [t for t in txt if any(k in t for k in ("구 ","동","로","길"))]
                if cand:
                    addr = cand[-1]
                rows.append((name, choice, addr))
        except Exception:
            pass
    # dedup
    ded = set()
    final = []
    for n,c,a in rows:
        key=(n,c,a)
        if key in ded: continue
        ded.add(key)
        final.append((n,c,a))
    return final

def scrape_one_draw(driver, drw_no:int, delay:float=0.6) -> List[StoreRow]:
    url = f"{BASE_URL}&drwNo={drw_no}"
    driver.get(url)
    time.sleep(delay)
    date_str = get_draw_date(drw_no) or ""
    out: List[StoreRow] = []
    # 1등
    _ = click_tab_if_exists(driver, ["1등","1 등","1st"])
    for n,c,a in collect_rows_on_current_view(driver, 1):
        out.append(StoreRow(drw_no, date_str, 1, n, c, a))
    # 2등
    _ = click_tab_if_exists(driver, ["2등","2 등","2nd"])
    for n,c,a in collect_rows_on_current_view(driver, 2):
        out.append(StoreRow(drw_no, date_str, 2, n, c, a))
    return out

def estimate_latest_draw(base_draw:int, base_date:date, today:date) -> int:
    # 주1회 규칙으로 최신 회차 추정
    diff_days = (today - base_date).days
    inc = diff_days // 7
    est = base_draw + inc
    # JSON으로 전진 탐색(있으면 +1 계속)
    cur = est
    while True:
        nxt = cur + 1
        if get_draw_date(nxt):
            cur = nxt
        else:
            break
    return cur

def normalize(s:str)->str:
    s = (s or "").strip()
    s = re.sub(r"\s+", "", s)  # 공백 제거
    s = s.replace("편의점","")  # 과한 수식어 제거 예시
    return s

def build_store_index(geojson_path:str)->Dict[str,str]:
    with open(geojson_path,"r",encoding="utf-8") as f:
        gj=json.load(f)
    idx={}
    for ft in gj.get("features",[]):
        p=ft.get("properties",{})
        key = normalize(p.get("name","")) + "|" + normalize(p.get("address",""))
        idx[key]=p.get("store_id")
    return idx

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--base-draw", type=int, required=True)
    parser.add_argument("--base-date", type=str, required=True)  # YYYY-MM-DD
    args = parser.parse_args()

    repo = args.repo_root
    data_dir = os.path.join(repo, "data")
    os.makedirs(data_dir, exist_ok=True)

    base_draw = args.base_draw
    base_date = datetime.strptime(args.base_date, "%Y-%m-%d").date()
    today = date.today()

    # 1) 최신 회차 추정
    latest = estimate_latest_draw(base_draw, base_date, today)
    print(f"[INFO] 최신 회차 추정: {latest} (기준 {base_draw}@{base_date})")

    # 2) 기존 CSV 로드
    stores_csv = os.path.join(data_dir, "dhlottery_stores.csv")
    if os.path.exists(stores_csv):
        df = pd.read_csv(stores_csv)
    else:
        df = pd.DataFrame(columns=["draw","draw_date","rank","name","choice_type","address"])

    have_draws = set(df["draw"].unique().tolist()) if not df.empty else set()
    start_draw = min(have_draws) if have_draws else latest
    # 누락 회차 모두 수집
    to_fetch = [d for d in range(min(have_draws|{latest}), latest+1) if d not in have_draws] if have_draws else [latest]
    print(f"[INFO] 새로 수집할 회차: {to_fetch}")

    if to_fetch:
        driver = build_driver()
        try:
            rows_all: List[StoreRow] = []
            for drw in to_fetch:
                print(f"[SCRAPE] {drw}")
                rows = scrape_one_draw(driver, drw)
                rows_all.extend(rows)
            if rows_all:
                df_new = pd.DataFrame([asdict(r) for r in rows_all])
                df = pd.concat([df, df_new], ignore_index=True)
        finally:
            driver.quit()

        # 저장
        df.sort_values(["draw","rank","name"], inplace=True)
        df.to_csv(stores_csv, index=False, encoding="utf-8")
        print(f"[SAVE] {stores_csv} ({len(df)} rows)")

    # 3) store_id 매칭 → wins.csv 생성/갱신
    geojson_path = os.path.join(data_dir, "stores_clean.geojson")
    wins_csv = os.path.join(data_dir, "wins.csv")
    unmatched_csv = os.path.join(data_dir, "wins_unmatched.csv")

    if os.path.exists(geojson_path):
        idx = build_store_index(geojson_path)
        wins_rows = []
        unmatched = []
        for _, r in df.iterrows():
            key = normalize(str(r["name"])) + "|" + normalize(str(r["address"]))
            store_id = idx.get(key)
            row = {
                "store_id": store_id or "",
                "date": r["draw_date"],
                "rank": int(r["rank"]),
                "draw_no": int(r["draw"]),
                "name": r["name"],
                "address": r["address"]
            }
            if store_id:
                wins_rows.append(row)
            else:
                unmatched.append(row)
        pd.DataFrame(wins_rows).to_csv(wins_csv, index=False, encoding="utf-8")
        pd.DataFrame(unmatched).to_csv(unmatched_csv, index=False, encoding="utf-8")
        print(f"[SAVE] {wins_csv}, {unmatched_csv}")

        # 4) A3 점수 재계산
        os.system(f'python scripts/compute_a3_scores.py --geojson "{geojson_path}" --events "{wins_csv}" --out-geojson "{os.path.join(data_dir,"stores_clean.a3.geojson")}" --out-summary "{os.path.join(data_dir,"scores_a3_summary.csv")}" --today {today.isoformat()}')
    else:
        print(f"[WARN] {geojson_path} 없음. wins.csv만 생성합니다. 이후 GeoJSON 추가 후 재실행하세요.")

if __name__ == "__main__":
    main()
