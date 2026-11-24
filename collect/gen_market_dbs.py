"""Maintain daily KRX price and volume databases"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
from pathlib import Path

import pandas as pd
import FinanceDataReader as fdr

from financials.tools.dc_tools import fetch_code, fetch_loop, pvi_paths

START_DATE = "2016-01-01"
# Snapshot rows are assigned to the date of the run. Only the 20:30 run is
# treated as confirmation that the session has closed.
CLOSE_CONFIRMED_AFTER = time(20, 30)
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


def _write_info(
    path,
    snapshot,
    session_date,
    closed,
    history_incomplete=(),
    previous_session_date=None,
    previous_session_closed=None,
):
    payload = {
        "last_updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "last_session_date": pd.Timestamp(session_date).strftime("%Y-%m-%d"),
        "last_session_closed": bool(closed),
        "last_session_status": "closed" if closed else "open",
        "previous_session_date": (
            pd.Timestamp(previous_session_date).strftime("%Y-%m-%d")
            if previous_session_date is not None else None
        ),
        "previous_session_closed": (
            bool(previous_session_closed) if previous_session_closed is not None else None
        ),
        "previous_session_status": (
            ("closed" if previous_session_closed else "unconfirmed")
            if previous_session_closed is not None else None
        ),
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
    """Refresh today's session, check the prior close, and recover missed closes."""
    now = datetime.now().astimezone()

    saved = _is_valid_pair(paths)
    if saved is not False:
        price_db, volume_db, saved_info = saved
    else:
        price_db = volume_db = None
        saved_info = {}

    # 005930's daily dates provide the trading-session calendar.
    calendar = fetch_code("005930", start_date)
    if calendar is None or calendar.empty:
        raise RuntimeError("Could not obtain the 005930 trading calendar")
    calendar_days = pd.DatetimeIndex(calendar.index).normalize().unique().sort_values()
    today = pd.Timestamp(now.date())
    prior_days = calendar_days[calendar_days < today]
    if len(prior_days) == 0:
        raise RuntimeError(f"No prior market session found before {today.date()}")
    prior_session_date = prior_days[-1]
    today_is_session = today in calendar_days
    # A close is trusted only when both metadata and the database identify the
    # immediately prior exchange session. Older metadata is read for migration.
    if saved is False:
        needs_rebuild = True
    else:
        stored_session_date = saved_info.get("last_session_date")
        stored_closed = saved_info.get(
            "last_session_closed", saved_info.get("last_day_closed")
        )
        db_has_prior_session = price_db.index[-1] >= prior_session_date
        if stored_session_date:
            stored_session_date = pd.Timestamp(stored_session_date).normalize()
        if stored_session_date == today:
            prior_close_confirmed = (
                pd.Timestamp(saved_info.get("previous_session_date")).normalize()
                == prior_session_date
                and saved_info.get("previous_session_closed") is True
            ) if saved_info.get("previous_session_date") else False
        else:
            prior_close_confirmed = (
                stored_session_date == prior_session_date and stored_closed is True
            )
        needs_rebuild = not db_has_prior_session or not prior_close_confirmed

    if saved is False:
        print("Market databases or metadata are missing/corrupt; rebuilding...")
    elif needs_rebuild:
        print(
            f"Recovery required: prior session {prior_session_date.date()} is not "
            "confirmed closed in metadata/database; rebuilding..."
        )

    snapshot = None
    if saved is False or needs_rebuild:
        snapshot = fetch_loop()
        snapshot.index = snapshot.index.astype(str)
        snapshot = snapshot[~snapshot.index.duplicated(keep="last")]
        snapshot = snapshot.loc[snapshot["Market"].isin(["KOSPI", "KOSDAQ"])]
        if snapshot.empty:
            raise RuntimeError("Returned an empty KOSPI/KOSDAQ snapshot")
        snapshot["Close"] = pd.to_numeric(snapshot["Close"], errors="coerce")
        snapshot["Volume"] = pd.to_numeric(snapshot["Volume"], errors="coerce")
        price_db, volume_db = _initialize(snapshot, paths)
        saved_info["history_incomplete"] = sorted(set(snapshot.index) - set(price_db.columns))

        if not today_is_session:
            # On a non-session day, keep the rebuild's prior-session history
            # and do not label a stale quote as today's trading snapshot.
            _write_info(
                paths[2], snapshot, prior_session_date, True,
                saved_info["history_incomplete"],
            )
            print(
                f"PV rebuild complete: session={prior_session_date.date()} "
                "status=closed; no live snapshot row applied."
            )
            _refresh_indices(paths)
            return

    if not today_is_session:
        print(
            f"PV update skipped: {today.date()} is not a 005930 market session; "
            f"prior_session={prior_session_date.date()} remains unchanged."
        )
        return

    if snapshot is None:
        snapshot = fetch_loop()
        snapshot.index = snapshot.index.astype(str)
        snapshot = snapshot[~snapshot.index.duplicated(keep="last")]
        snapshot = snapshot.loc[snapshot["Market"].isin(["KOSPI", "KOSDAQ"])]
        if snapshot.empty:
            raise RuntimeError("Returned an empty KOSPI/KOSDAQ snapshot")
        snapshot["Close"] = pd.to_numeric(snapshot["Close"], errors="coerce")
        snapshot["Volume"] = pd.to_numeric(snapshot["Volume"], errors="coerce")

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

    session_closed = now.time() >= CLOSE_CONFIRMED_AFTER
    price_db.loc[today, snapshot.index] = snapshot["Close"].values
    volume_db.loc[today, snapshot.index] = snapshot["Volume"].values

    # Keep only codes currently listed.
    price_db = price_db.reindex(columns=sorted(current_codes))
    volume_db = volume_db.reindex(columns=sorted(current_codes))
    _save_db(price_db, paths[0])
    _save_db(volume_db, paths[1])
    if saved_info.get("last_session_date") == today.strftime("%Y-%m-%d"):
        previous_session_date = saved_info.get("previous_session_date")
        previous_session_closed = saved_info.get("previous_session_closed")
    elif needs_rebuild or saved is False:
        previous_session_date = prior_session_date
        previous_session_closed = True
    else:
        previous_session_date = saved_info.get("last_session_date")
        previous_session_closed = saved_info.get(
            "last_session_closed", saved_info.get("last_day_closed")
        )
    _write_info(
        paths[2], snapshot, today, session_closed, history_incomplete,
        previous_session_date, previous_session_closed,
    )
    status = "closed" if session_closed else "open"
    previous_status = "closed" if previous_session_closed is True else "unconfirmed"
    print(
        f"PV updated: session={today.date()} status={status}; "
        f"previous_session={previous_session_date or 'unknown'} "
        f"status={previous_status}; securities={len(current_codes)}."
    )

    _refresh_indices(paths)


def _refresh_indices(paths):
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
