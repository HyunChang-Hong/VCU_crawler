# VCU 상품 수집 모니터 v2

강의 과제용 Cafe24 상품 크롤링 + 자동 최신화 + 로컬 대시보드 + Railway 배포 프로젝트입니다.

## 실행
1. Python 3.11+ 설치
2. 압축 해제
3. Windows에서 `run_local.bat` 더블클릭
4. 브라우저에서 `http://127.0.0.1:8000`

첫 실행 시 대상 쇼핑몰을 자동 수집합니다. 수집 중에도 DB가 상품 단위로 갱신되어 화면에서 진행률과 누적 상품 수를 확인할 수 있습니다.

## v2 주요 기능
- 강의 예시와 유사한 상품 수집 모니터 대시보드
- 수집 상품 / 품절 / 판매 종료 / 평균 판매가 / 24시간 변경 / 마지막 결과 카드
- 검색 / 카테고리 / 정렬 / 판매상태 / 가격 범위 필터
- 4열 상품 카드 + 최근 변경 내역 패널
- CSV 내려받기
- 수집 진행률, 현재 처리 상품, 신규/변경 건수 표시
- 30분 주기 자동수집 + 수동 수집
- 상품 변경 이력 저장
- 3회 연속 누락 시 판매 종료 처리
- Railway 배포 설정

## 속도 개선
v1은 상품 상세를 한 개씩 순차 처리했습니다. v2는 기본 6개 병렬 요청으로 상세페이지를 수집하고, 완료된 상품부터 즉시 DB에 반영합니다.

환경변수로 조정 가능:
- `MAX_CONCURRENT_REQUESTS=6`
- `REQUEST_DELAY_SECONDS=0.08`
- `CRAWL_INTERVAL_MINUTES=30`
- `MAX_PRODUCTS=500`

대상 서버에 부담을 주지 않도록 동시 요청 수를 과도하게 높이지 마세요.

## Railway
GitHub 저장소에 업로드한 뒤 Railway에서 Repository 배포를 선택합니다. `Procfile`과 `railway.json`이 포함되어 있습니다.
PostgreSQL을 연결하면 Railway의 `DATABASE_URL`을 자동 사용합니다.

## v2.1 Railway 배포 보강
- `.python-version`으로 Python 3.11.9 고정
- Railway `PORT` 자동 사용
- `/health` Healthcheck 제공
- Railway PostgreSQL `DATABASE_URL` 지원
- Railway Volume 자동 감지 및 SQLite 영구 저장 경로 지원
- `AUTO_CRAWL_ON_STARTUP` / `SCHEDULER_ENABLED` 환경변수 추가
- 배포 시작 시 target/db/scheduler 상태를 로그에 출력

배포 순서는 `RAILWAY_DEPLOY.md`를 그대로 따라가면 됩니다.
