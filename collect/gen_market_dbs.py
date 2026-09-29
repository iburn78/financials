#%%
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime

from concurrent.futures import ThreadPoolExecutor
from functools import partial

from financials.tools.dc_tools import pvi_paths

END_DATE_fdr = (pd.Timestamp.today().normalize()-pd.Timedelta(days=1)).date()

def _fetch(code, START_DATE):
    fdr_data = fdr.DataReader(code, START_DATE, END_DATE_fdr)
    return fdr_data[['Close', 'Volume']]

# this is only available through CACHE from 2026-03-08
def _get_close(date_req = END_DATE_fdr):
    date_req = date_req.strftime('%Y%m%d')
    # Quick Fix (FDR Error): -------------------------
    if date_req == '20260608': date_req = '20260605'
    if date_req == '20260908': date_req = '20260907'
    # ------------------------------------------------
    _prev = fdr.StockListing('KRX', date_req)[['Code', 'Market', 'Stocks']]
    return _prev.loc[_prev['Market'].str.contains('KOSPI|KOSDAQ')]

def initialization(START_DATE, paths, workers=8):
    price_data = {}
    volume_data = {}

    codelist = _get_close()['Code']
    fetch = partial(_fetch, START_DATE=START_DATE)

    # parallel download version: 8 request is usually safe
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = executor.map(fetch, codelist)
        for result in results:
            code, res = result
            price_data[code] = res['Close']
            volume_data[code] = res['Volume']

    pdb = pd.concat(price_data, axis=1)
    vdb = pd.concat(volume_data, axis=1)

    _save_db(pdb, paths[0])
    _save_db(vdb, paths[1])

def _save_db(db, path):
    # float is efficient in NaN handling etc 
    db = db.apply(pd.to_numeric, errors='coerce')

    # remove delisted
    db = db.dropna(axis=1, subset=[db.index[-1]])
    db.to_feather(path)

def _update_DB(DB, snapshot, date, column):
    row = snapshot.set_index('Code')[column]
    DB.loc[date, row.index] = row

    return DB

def gen_market_DB(paths, START_DATE):
    market_dates = fdr.DataReader('005930', START_DATE).index
    market_dates = market_dates[market_dates <= pd.Timestamp(END_DATE_fdr)]
    prev_close = _get_close()

    [price_db_path, volume_db_path, kospi_path, kosdaq_path, kospi200_path] = paths

    try:
        price_db = pd.read_feather(price_db_path)
        volume_db = pd.read_feather(volume_db_path)

        dates_to_update = market_dates[market_dates.get_loc(price_db.index[-1]):]

        last_available_close = _get_close(dates_to_update[0])
        intersection = pd.merge(last_available_close, prev_close, on=['Code', 'Stocks'], how='inner')
        code_list_to_fully_replace = list(set(prev_close['Code']) - set(intersection['Code']))

        new_prices = {}
        new_volumes = {}

        for code in code_list_to_fully_replace:
            try:
                code, res = _fetch(code, START_DATE)
                new_prices[code] = res['Close']
                new_volumes[code] = res['Volume']
            except Exception as e:
                print(f"Error retrieving full data for {code}: {e}")
                continue

        if new_prices:
            price_db = price_db.drop(columns=new_prices.keys(), errors='ignore')
            price_db = pd.concat([price_db, pd.DataFrame(new_prices)], axis=1)

        if new_volumes:
            volume_db = volume_db.drop(columns=new_volumes.keys(), errors='ignore')
            volume_db = pd.concat([volume_db, pd.DataFrame(new_volumes)], axis=1)

        # snapshot update should be done after full replaces above
        for date in dates_to_update:
            date_snapshot = _get_close(date)
            price_db = _update_DB(price_db, date_snapshot, date, 'Close')
            volume_db = _update_DB(volume_db, date_snapshot, date, 'Volume')
    
        _save_db(price_db, price_db_path)
        _save_db(volume_db, volume_db_path)

    except FileNotFoundError:  # Handle if files don't exist
        print('files not found - creating new ones; could take some time')
        initialization(START_DATE=START_DATE, paths=paths)
        return

    # INDEX data collection
    kospi = fdr.DataReader('KS11')
    kosdaq = fdr.DataReader('KQ11')
    kospi200 = fdr.DataReader('KS200')

    kospi.to_feather(kospi_path)
    kosdaq.to_feather(kosdaq_path)
    kospi200.to_feather(kospi200_path)

if __name__ == '__main__': 
    print(f'prices and volumes updates [initiating] {datetime.today().strftime("%Y-%m-%d %H:%M:%S")}')
    START_DATE = '2016-01-01'
    gen_market_DB(pvi_paths, START_DATE)
    print("prices and volumes updates [completed]")
