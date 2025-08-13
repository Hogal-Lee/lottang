# 로땅 자동화: GitHub Actions로 주 1회 스크랩핑 → A3 점수 반영

이 리포는 매주 **일요일 15:00 KST**(06:00 UTC)에 자동으로:
1) 동행복권 판매점(1/2등) **스크랩핑**
2) `data/dhlottery_stores.csv` 누적 갱신
3) `data/wins.csv` 생성(store_id 매칭)
4) `data/stores_clean.a3.geojson` 및 `data/scores_a3_summary.csv` 갱신
5) 변경사항 **commit & push**

## 빠른 시작
1. 이 폴더를 리포지토리에 복사
2. `data/stores_clean.geojson` 추가(기존 매장 데이터)
3. `requirements.txt`와 `.github/workflows/scrape.yml` 확인
4. 수동으로 한 번 실행: **Actions → 이 워크플로 → Run workflow**

## 파일 구조
- `.github/workflows/scrape.yml` : 매주 실행되는 CI
- `scripts/scrape_and_update.py` : 스크레이퍼 & 매칭 & A3 오케스트레이션
- `scripts/compute_a3_scores.py` : A3 계산기
- `data/dhlottery_stores.csv` : 누적 스크랩 결과(회차/날짜/상호/구분/주소/등수)
- `data/wins.csv` : store_id 매칭된 이벤트(없으면 빈 store_id)
- `data/wins_unmatched.csv` : 매칭 실패 목록(수기 매핑용)
- `data/stores_clean.a3.geojson` : A3 반영본
- `data/scores_a3_summary.csv` : 점수 요약
- `docs/scoring.md` : 정책 문서 (A3)

## 자주 묻는 질문
- **왜 Selenium?**  
  페이지가 탭 전환 등 동적 DOM을 쓰기 때문. Actions에서 headless Chrome으로 안정적으로 동작.

- **매칭이 안 되는 레코드가 있어요**  
  `data/wins_unmatched.csv`에서 이름/주소를 정규화해 `stores_clean.geojson`과 일치하도록 보정하거나,
  `scripts/scrape_and_update.py`의 `normalize()` 함수를 강화하세요.

- **언제 실행되나요?**  
  매주 일요일 15:00 KST(= 06:00 UTC). `scrape.yml`의 cron을 바꾸면 시각 조정 가능.

- **Pages 갱신은?**  
  데이터 파일이 업데이트되면 GitHub Pages(정적 빌드)에서 최신 데이터를 불러오게 하세요.  
  정적 사이트는 이 리포의 `data/` 경로의 파일을 fetch하도록 구성하면 실시간 반영됩니다.
