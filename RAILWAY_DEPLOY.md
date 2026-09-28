# Railway 배포 안내 — VCU 상품 수집 모니터 v2.1

## 권장 방식: GitHub + Railway PostgreSQL

1. 이 폴더의 파일을 GitHub 저장소 루트에 업로드합니다.
2. Railway에서 `New Project` → `Deploy from GitHub repo` → 해당 저장소를 선택합니다.
3. 같은 Railway 프로젝트에서 `+ New` → `Database` → `PostgreSQL`을 추가합니다.
4. 웹 서비스의 `Variables`에 아래 값을 추가합니다.

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
APP_ENV=railway
TARGET_SITE=https://vibecodinguniv.cafe24.com/
CRAWL_INTERVAL_MINUTES=30
REQUEST_DELAY_SECONDS=0.08
REQUEST_TIMEOUT_SECONDS=20
MAX_CATEGORY_PAGES=20
MAX_PRODUCTS=500
MAX_CONCURRENT_REQUESTS=6
INACTIVE_AFTER_MISSES=3
ENABLE_MANUAL_REFRESH=true
AUTO_CRAWL_ON_STARTUP=true
SCHEDULER_ENABLED=true
```

5. 배포가 끝나면 웹 서비스 `Settings` → `Networking` → `Generate Domain`을 눌러 공개 주소를 만듭니다.
6. 생성된 주소의 `/health`가 아래처럼 응답하는지 확인합니다.

```json
{"ok":true,"service":"vcu-product-monitor","version":"2.1.0"}
```

7. 메인 주소로 접속해 `수집 중` → 상품 카드 증가 → `완료` 순서로 변하는지 확인합니다.

## 빠른 과제용 방식: SQLite + Railway Volume

PostgreSQL 없이 배포하려면 웹 서비스에 Railway Volume을 붙이면 됩니다.
권장 Mount Path는 `/data`입니다. `DATABASE_URL`은 설정하지 마세요.
앱이 Railway가 제공하는 `RAILWAY_VOLUME_MOUNT_PATH`를 감지해 `/data/vcu_products.db`를 사용합니다.

Volume 없이도 앱은 실행되지만, SQLite 파일은 재배포/인스턴스 교체 시 보존을 보장할 수 없으므로 과제 제출용 최종 상태에는 PostgreSQL 또는 Volume을 권장합니다.

## Railway에서 확인할 로그

정상 시작 시 다음과 비슷한 로그가 보입니다.

```text
VCU monitor starting env=railway target=https://vibecodinguniv.cafe24.com/ db=postgresql scheduler=True auto_crawl=True
```

배포는 성공했는데 상품이 0개라면 `/api/status`의 `last_error`와 Railway Deploy Logs를 먼저 확인합니다.

## 중요

- 웹 서비스는 **1개 프로세스/1개 worker**로 운영합니다. 여러 worker를 켜면 각 worker가 스케줄러를 시작해 중복 크롤링할 수 있습니다.
- `MAX_CONCURRENT_REQUESTS`는 기본 6입니다. 대상 사이트에 부담을 주지 않도록 과도하게 올리지 마세요.
- Railway에서 대상 Cafe24 사이트가 데이터센터 IP를 제한하는 경우 웹 화면은 배포되어도 크롤링이 실패할 수 있습니다. 이 경우 `/api/status` 오류 메시지로 구분합니다.
