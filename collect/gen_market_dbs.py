"""Maintain daily KRX price and volume databases from Naver Finance."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
from pathlib import Path

import pandas as pd
import FinanceDataReader as fdr

from financials.tools.dc_tools import fetch_code, fetch_loop, pvi_paths

START_DATE = "2016-01-01"
# Allow a buffer around the exchange's close (configured here as 20:00).
CLOSE_CONFIRMED_AFTER = time(20, 30)
OPENING_BUFFER_END = time(8, 30)
WORKERS = 8



def _read_db(path):
    db = pd.read_feather(path)
    if db.empty or not isinstance(db.index, pd.DatetimeIndex):
        raise ValueError(f"Invalid market database: {path}")
    db.index = pd.to_datetime(db.index).normalize()
    db = db.sort_index()
    if db.index.has_duplicates:
        db = db[~db.index.duplicated(keep="last")]
    return db.apply(pd.to_numeric, errors="coerce")


def _fetch_history(code):
    data = fetch_code(str(code), START_DATE)
    if data is None or data.empty or not {"Close", "Volume"}.issubset(data.columns):
        raise ValueError(f"No usable OHLCV history for {code}")
    data = data[["Close", "Volume"]].copy()
    data.index = pd.to_datetime(data.index).normalize()
    return str(code), data


def _safe_fetch_history(code):
    try:
        return _fetch_history(code)
    except Exception as exc:
        return str(code), exc


def _initialize(snapshot, paths):
    price_parts, volume_parts = {}, {}
    codes = snapshot.index.astype(str).tolist()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for code, result in pool.map(_safe_fetch_history, codes):
            if isinstance(result, Exception):
                print(f"History fetch failed for {code}: {result}")
                continue
            price_parts[code] = result["Close"]
            volume_parts[code] = result["Volume"]
    if not price_parts:
        raise RuntimeError("No security history could be fetched; refusing to save empty databases")
    price_db = pd.concat(price_parts, axis=1).sort_index()
    volume_db = pd.concat(volume_parts, axis=1).sort_index()
    _save_db(price_db, paths[0])
    _save_db(volume_db, paths[1])
    return price_db, volume_db


def _save_db(db, path):
    db = db.sort_index().apply(pd.to_numeric, errors="coerce")
    db.index.name = "Date"
    db.to_feather(path)


def _write_info(path, snapshot, session_date, closed, history_incomplete=()):
    payload = {
        "last_updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "last_session_date": pd.Timestamp(session_date).strftime("%Y-%m-%d"),
        "last_day_closed": bool(closed),
        "outshares": {str(code): int(value) for code, value in snapshot["Stocks"].items()},
        "history_incomplete": sorted(map(str, history_incomplete)),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_valid_pair(paths):
    try:
        price_db, volume_db = _read_db(paths[0]), _read_db(paths[1])
        if not price_db.index.equals(volume_db.index):
            return False
        with open(paths[2], encoding="utf-8") as f:
            info = json.load(f)
        if not isinstance(info.get("outshares"), dict):
            return False
        return price_db, volume_db, info
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def gen_market_DB(paths=pvi_paths, start_date=START_DATE):
    """Refresh today's snapshot, maintain the listed-code set, or rebuild on gaps."""
    now = datetime.now().astimezone()
    snapshot = fetch_loop()
    snapshot.index = snapshot.index.astype(str)
    snapshot = snapshot[~snapshot.index.duplicated(keep="last")]
    snapshot = snapshot.loc[snapshot["Market"].isin(["KOSPI", "KOSDAQ"])]
    if snapshot.empty:
        raise RuntimeError("Naver returned an empty KOSPI/KOSDAQ snapshot")
    snapshot["Close"] = pd.to_numeric(snapshot["Close"], errors="coerce")
    snapshot["Volume"] = pd.to_numeric(snapshot["Volume"], errors="coerce")

    saved = _is_valid_pair(paths)
    if saved is False:
        print("Market databases or metadata are missing/corrupt; rebuilding from Naver history.")
        price_db, volume_db = _initialize(snapshot, paths)
        saved_info = {"history_incomplete": sorted(set(snapshot.index) - set(price_db.columns))}
    else:
        price_db, volume_db, saved_info = saved

    # Use Samsung's Naver daily chart as the exchange-session calendar. If the
    # database missed a session, historical snapshots cannot be recovered from
    # fetch_loop; rebuild all symbols to avoid fabricating stale daily values.
    calendar = fetch_code("005930", start_date)
    if calendar is None or calendar.empty:
        raise RuntimeError("Could not obtain the 005930 trading calendar")
    calendar_days = pd.DatetimeIndex(calendar.index).normalize().unique().sort_values()
    confirmed_today = now.time() >= CLOSE_CONFIRMED_AFTER
    today = pd.Timestamp(now.date())
    today_is_session = today in calendar_days
    if now.time() < OPENING_BUFFER_END:
        prior_days = calendar_days[calendar_days < today]
        session_date = prior_days[-1] if len(prior_days) else calendar_days[-1]
        is_closed = True
    else:
        session_date = today if today_is_session else calendar_days[-1]
        is_closed = confirmed_today

    last_db_day = price_db.index[-1]
    completed_days = calendar_days[calendar_days < today] if not confirmed_today else calendar_days[calendar_days <= today]
    expected_completed_day = completed_days[-1] if len(completed_days) else calendar_days[-1]
    previous_claimed_day = saved_info.get("last_session_date")
    previous_claimed_closed = saved_info.get("last_day_closed")
    if (last_db_day < expected_completed_day and not (not confirmed_today and last_db_day == calendar_days[-1])) or (
        previous_claimed_day and previous_claimed_closed is False and today > pd.Timestamp(previous_claimed_day)
    ):
        print("A completed market session was missed; rebuilding because Naver cannot provide its old snapshot.")
        price_db, volume_db = _initialize(snapshot, paths)
        saved_info["history_incomplete"] = sorted(set(snapshot.index) - set(price_db.columns))

    current_codes = set(snapshot.index)
    previous_codes = set(price_db.columns.astype(str))
    old_shares = saved_info.get("outshares", {})
    changed_share_codes = {
        code for code in current_codes & previous_codes & set(old_shares)
        if int(snapshot.at[code, "Stocks"]) != int(old_shares[code])
    }
    new_codes = current_codes - previous_codes
    full_replace = changed_share_codes | new_codes | set(saved_info.get("history_incomplete", []))
    history_incomplete = set()

    if full_replace:
        replacements = {}
        codes = sorted(full_replace)
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for code, history in pool.map(_safe_fetch_history, codes):
                if isinstance(history, Exception):
                    print(f"Full replacement failed for {code}: {history}")
                    history_incomplete.add(code)
                    continue
                replacements[code] = history
        for code, history in replacements.items():
            price_db = price_db.drop(columns=code, errors="ignore")
            volume_db = volume_db.drop(columns=code, errors="ignore")
            price_db = price_db.join(history["Close"].rename(code), how="outer")
            volume_db = volume_db.join(history["Volume"].rename(code), how="outer")

    # The live snapshot is the only source for today's values. Before opening,
    # Naver still reports the previous close, so keep that value on its session.
    price_db.loc[session_date, snapshot.index] = snapshot["Close"].values
    volume_db.loc[session_date, snapshot.index] = snapshot["Volume"].values

    # Keep only codes currently listed by Naver.
    price_db = price_db.reindex(columns=sorted(current_codes))
    volume_db = volume_db.reindex(columns=sorted(current_codes))
    _save_db(price_db, paths[0])
    _save_db(volume_db, paths[1])
    _write_info(paths[2], snapshot, session_date, is_closed, history_incomplete)
    print(f"Updated {len(current_codes)} securities for {session_date.date()} (closed={is_closed}).")

    # FDR remains the source for index series; only individual-stock prices
    # and volumes use the Naver fetchers.
    for symbol, path in zip(("KS11", "KQ11", "KS200"), paths[3:6]):
        index_data = fdr.DataReader(symbol)
        if index_data is None or index_data.empty:
            raise RuntimeError(f"FDR returned no index data for {symbol}")
        index_data.to_feather(path)


if __name__ == "__main__":
    print(f"Market database update started: {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}")
    gen_market_DB()
    print(f"Market database update completed: {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}")
