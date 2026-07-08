from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
DATA = ROOT / "data"
LATEST_JSON = DATA / "latest.json"
LATEST_CSV = DATA / "latest.csv"
STATUS_JSON = DATA / "status.json"
CN_TZ = timezone(timedelta(hours=8))

BANKS = [
    ("000001", "平安银行", "1991-04-03"),
    ("600000", "浦发银行", "1999-11-10"),
    ("600015", "华夏银行", "2003-09-12"),
    ("600016", "民生银行", "2000-12-19"),
    ("600036", "招商银行", "2002-04-09"),
    ("601009", "南京银行", "2007-07-19"),
    ("601166", "兴业银行", "2007-02-05"),
    ("601169", "北京银行", "2007-09-19"),
    ("601288", "农业银行", "2010-07-15"),
    ("601328", "交通银行", "2007-05-15"),
    ("601398", "工商银行", "2006-10-27"),
    ("601818", "光大银行", "2010-08-18"),
    ("601939", "建设银行", "2007-09-25"),
    ("601988", "中国银行", "2006-07-05"),
    ("601998", "中信银行", "2007-04-27"),
    ("002142", "宁波银行", "2007-07-19"),
    ("600908", "无锡银行", "2016-09-23"),
    ("600919", "江苏银行", "2016-08-02"),
    ("600926", "杭州银行", "2016-10-27"),
    ("600928", "西安银行", "2019-03-01"),
    ("601077", "渝农商行", "2019-10-29"),
    ("601128", "常熟银行", "2016-09-30"),
    ("601187", "厦门银行", "2020-10-27"),
    ("601229", "上海银行", "2016-11-16"),
    ("601577", "长沙银行", "2018-09-26"),
    ("601658", "邮储银行", "2019-12-10"),
    ("601838", "成都银行", "2018-01-31"),
    ("601860", "紫金银行", "2019-01-03"),
    ("601916", "浙商银行", "2019-11-26"),
    ("601963", "重庆银行", "2021-02-05"),
    ("601997", "贵阳银行", "2016-08-16"),
    ("002807", "江阴银行", "2016-09-02"),
    ("002839", "张家港行", "2017-01-24"),
    ("002936", "郑州银行", "2018-09-19"),
    ("002948", "青岛银行", "2019-01-16"),
    ("002958", "青农商行", "2019-03-26"),
    ("002966", "苏州银行", "2019-08-02"),
    ("603323", "苏农银行", "2016-11-29"),
]


@dataclass
class Quote:
    code: str
    name: str
    price: float | None
    quote_time: str


def now_cn() -> datetime:
    return datetime.now(CN_TZ)


def iso_now() -> str:
    return now_cn().strftime("%Y-%m-%d %H:%M:%S")


def market_prefix(code: str) -> str:
    return "sh" if code.startswith("6") else "sz"


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_status() -> dict[str, Any]:
    if STATUS_JSON.exists():
        return json.loads(STATUS_JSON.read_text(encoding="utf-8"))
    return {}


def save_failure(message: str, errors: list[str] | None = None) -> None:
    previous = read_status()
    write_json(
        STATUS_JSON,
        {
            "ok": False,
            "generated_at": iso_now(),
            "last_success_at": previous.get("last_success_at", ""),
            "error": message,
            "errors": errors or [],
        },
    )


def save_success(row_count: int, errors: list[str]) -> None:
    write_json(
        STATUS_JSON,
        {
            "ok": True,
            "generated_at": iso_now(),
            "last_success_at": iso_now(),
            "error": "",
            "errors": errors,
            "row_count": row_count,
        },
    )


def report_available_date(period: str) -> pd.Timestamp:
    year = int(period[:4])
    mmdd = period[4:]
    if mmdd == "0331":
        return pd.Timestamp(year, 4, 30, tz=CN_TZ)
    if mmdd == "0630":
        return pd.Timestamp(year, 8, 31, tz=CN_TZ)
    if mmdd == "0930":
        return pd.Timestamp(year, 10, 31, tz=CN_TZ)
    if mmdd == "1231":
        return pd.Timestamp(year + 1, 4, 30, tz=CN_TZ)
    return pd.Timestamp.max.tz_localize(CN_TZ)


def latest_profit_growth(financial: pd.DataFrame, as_of: datetime) -> tuple[float | None, str]:
    row = financial[financial["指标"].astype(str).eq("归母净利润")]
    if row.empty:
        return None, ""
    values = pd.to_numeric(row.iloc[0].drop(labels=["选项", "指标"], errors="ignore"), errors="coerce")
    rows: list[tuple[pd.Timestamp, str, float]] = []
    for period, value in values.items():
        period = str(period)
        if not period.isdigit() or len(period) != 8 or pd.isna(value):
            continue
        previous_period = str(int(period[:4]) - 1) + period[4:]
        previous_value = values.get(previous_period, math.nan)
        if pd.notna(previous_value) and previous_value != 0:
            rows.append((report_available_date(period), period, float(value / previous_value - 1)))
    visible = [item for item in rows if item[0].to_pydatetime() <= as_of]
    if not visible:
        return None, ""
    _, period, growth = sorted(visible, key=lambda item: (item[0], item[1]))[-1]
    return growth, period


def normalize_dividend(dividend: pd.DataFrame) -> pd.DataFrame:
    df = dividend.copy()
    df["除权日"] = pd.to_datetime(df["除权日"], errors="coerce")
    df["派息比例"] = pd.to_numeric(df["派息比例"], errors="coerce")
    df["dps"] = df["派息比例"] / 10.0
    df["report_year"] = pd.to_numeric(
        df["报告时间"].astype(str).str.extract(r"(\d{4})")[0],
        errors="coerce",
    )
    return df[pd.notna(df["除权日"]) & (df["dps"] > 0)].copy()


def annual_dividend_for_year(dividend: pd.DataFrame, year: int) -> float:
    return float(dividend.loc[dividend["report_year"].eq(year), "dps"].sum())


def has_interim_dividend(dividend: pd.DataFrame) -> bool:
    return bool(dividend["分红类型"].astype(str).str.contains("中期", na=False, regex=False).any())


def ttm_dividend(dividend: pd.DataFrame, as_of: pd.Timestamp) -> float:
    start = as_of - pd.Timedelta(days=365)
    window = dividend[(dividend["除权日"] <= as_of) & (dividend["除权日"] > start)]
    return float(window["dps"].sum())


def dividend_for_percentile(dividend: pd.DataFrame, date: pd.Timestamp, use_ttm: bool) -> float:
    if date.year <= 2025:
        return annual_dividend_for_year(dividend, date.year)
    if use_ttm:
        return ttm_dividend(dividend, date)
    return annual_dividend_for_year(dividend, 2025)


def dividend_yield_percentile(
    history: pd.DataFrame,
    dividend: pd.DataFrame,
    current_yield: float | None,
    as_of: pd.Timestamp,
    use_ttm: bool,
) -> float | None:
    if current_yield is None:
        return None
    hist = history.copy()
    hist["date"] = pd.to_datetime(hist["date"], errors="coerce")
    hist["close"] = pd.to_numeric(hist["close"], errors="coerce")
    hist = hist[(hist["date"] >= as_of - pd.Timedelta(days=365 * 5)) & (hist["date"] <= as_of)]
    yields: list[float] = []
    for _, row in hist.iterrows():
        close = row["close"]
        date = row["date"]
        if pd.isna(close) or close <= 0 or pd.isna(date):
            continue
        dps = dividend_for_percentile(dividend, date, use_ttm)
        if dps > 0:
            yields.append(float(dps / close))
    if not yields:
        return None
    return sum(1 for item in yields if item <= current_yield) / len(yields)


def fetch_realtime_quotes(codes: list[str]) -> dict[str, Quote]:
    if os.getenv("USE_CACHED_QUOTES") == "1":
        return fetch_cached_quotes(codes)

    quotes: dict[str, Quote] = {}
    for i in range(0, len(codes), 60):
        batch = codes[i : i + 60]
        query = ",".join(f"{market_prefix(code)}{code}" for code in batch)
        response = requests.get(
            f"https://qt.gtimg.cn/q={query}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        response.raise_for_status()
        response.encoding = "gbk"
        for part in response.text.split(";"):
            if "~" not in part:
                continue
            fields = part.split('"')[1].split("~")
            if len(fields) < 31:
                continue
            code = fields[2]
            price = float(fields[3]) if fields[3] else None
            quotes[code] = Quote(code=code, name=fields[1], price=price, quote_time=fields[30])
    missing = sorted(set(codes) - set(quotes))
    if missing:
        raise RuntimeError(f"实时行情缺失：{', '.join(missing)}")
    return quotes


def fetch_cached_quotes(codes: list[str]) -> dict[str, Quote]:
    quotes: dict[str, Quote] = {}
    for code in codes:
        history = read_csv(CACHE / f"hist_{code}_raw.csv")
        history["date"] = pd.to_datetime(history["date"], errors="coerce")
        history["close"] = pd.to_numeric(history["close"], errors="coerce")
        latest = history.dropna(subset=["date", "close"]).sort_values("date").iloc[-1]
        name = next((item[1] for item in BANKS if item[0] == code), code)
        quotes[code] = Quote(
            code=code,
            name=name,
            price=float(latest["close"]),
            quote_time=f"cached:{latest['date'].date()}",
        )
    return quotes


def load_universe(as_of: datetime) -> list[tuple[str, str, str]]:
    cutoff = pd.Timestamp(as_of.date()) - pd.DateOffset(years=5)
    return [(code, name, listing) for code, name, listing in BANKS if pd.Timestamp(listing) <= cutoff]


def build_rows(as_of: datetime) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    universe = load_universe(as_of)
    codes = [code for code, _, _ in universe]
    quotes = fetch_realtime_quotes(codes)
    as_of_ts = pd.Timestamp(as_of.replace(tzinfo=None))
    rows: list[dict[str, Any]] = []

    for code, name, listing_date in universe:
        row_error = ""
        try:
            financial = read_csv(CACHE / f"financial_{code}.csv")
            dividend = normalize_dividend(read_csv(CACHE / f"dividend_{code}.csv"))
            history = read_csv(CACHE / f"hist_{code}_raw.csv")
            quote = quotes[code]
            price = quote.price
            uses_ttm = has_interim_dividend(dividend)
            annual_dps = annual_dividend_for_year(dividend, min(as_of.year, 2025))
            ttm_dps = ttm_dividend(dividend, as_of_ts) if uses_ttm else None
            dividend_dps = ttm_dps if uses_ttm else annual_dps
            current_yield = dividend_dps / price if price and dividend_dps and dividend_dps > 0 else None
            percentile = dividend_yield_percentile(history, dividend, current_yield, as_of_ts, uses_ttm)
            growth, period = latest_profit_growth(financial, as_of)
        except Exception as exc:
            price = None
            ttm_dps = None
            annual_dps = None
            uses_ttm = False
            current_yield = None
            percentile = None
            growth = None
            period = ""
            row_error = f"{code} {name}: {exc}"
            errors.append(row_error)

        rows.append(
            {
                "code": code,
                "name": name,
                "listing_date": listing_date,
                "price": price,
                "dividend_yield": current_yield,
                "dividend_yield_percentile": percentile,
                "profit_growth": growth,
                "profit_period": period,
                "annual_dividend": annual_dps,
                "ttm_dividend": ttm_dps,
                "uses_ttm_dividend": uses_ttm,
                "updated_at": iso_now(),
                "error": row_error,
            }
        )

    rows.sort(
        key=lambda item: (
            item["dividend_yield_percentile"] is not None,
            item["dividend_yield_percentile"] or -1,
        ),
        reverse=True,
    )
    for index, row in enumerate(rows, 1):
        row["rank"] = index
    return rows, errors


def write_latest(rows: list[dict[str, Any]], errors: list[str]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": iso_now(),
        "source": "GitHub Actions / Tencent quote / cached financial and dividend data",
        "dividend_policy": "Current yield uses 2026 TTM available dividends; percentile history uses annual dividend for 2025 and before.",
        "rows": rows,
    }
    write_json(LATEST_JSON, payload)

    fieldnames = [
        "rank",
        "code",
        "name",
        "listing_date",
        "price",
        "dividend_yield",
        "dividend_yield_percentile",
        "profit_growth",
        "profit_period",
        "annual_dividend",
        "ttm_dividend",
        "uses_ttm_dividend",
        "updated_at",
        "error",
    ]
    with LATEST_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    save_success(len(rows), errors)


def main() -> None:
    try:
        rows, errors = build_rows(now_cn())
        write_latest(rows, errors)
        print(f"Generated {len(rows)} rows with {len(errors)} row errors.")
    except Exception as exc:
        save_failure(f"刷新失败：{exc}")
        print(f"Refresh failed: {exc}")


if __name__ == "__main__":
    main()
