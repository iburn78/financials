import requests, json
import pandas as pd

def test():
    url = 'https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'
    data = {
        'bld': 'dbms/MDC/STAT/standard/MDCSTAT01501',
        'mktId': 'STK',
        'trdDd': '20260910',
        'share': '1',
        'money': '1',
        'csvxls_isNo': 'false',
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd'
    }
    html_text = requests.post(url, headers=headers, data=data)
    print(html_text)
    print(html_text)
    print(html_text)

    # j = json.loads(html_text)
    # print(j)

_krx_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd',
}

def _krx_fullcode():
    # global __KRX_CODES
    # if len(__KRX_CODES) == 0:

    data = {
        'locale': 'ko_KR',
        'mktsel': 'ALL',
        'searchText': '',
        'typeNo': 0,
        'bld': 'dbms/comm/finder/finder_stkisu',
    }
    url = 'http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'
    r = requests.post(url, data, headers=_krx_headers)
    print(r.text)
    __KRX_CODES = pd.DataFrame(r.json()['block1'])
    __KRX_CODES = __KRX_CODES.set_index('short_code')
    print(__KRX_CODES)

    # if code not in __KRX_CODES.index:
    #     return None
    # return __KRX_CODES.loc[code]['full_code']

# _krx_fullcode()

# _krx_stock_price_2years('KR7005930003')
import FinanceDataReader as fdr
from io import StringIO
import re

# print(fdr.DataReader('005930'))

def _naver_data_reader(symbol):
    url = 'https://fchart.stock.naver.com/sise.nhn?timeframe=day&count=6000&requestType=0&symbol='
    r = requests.get(url + symbol)

    data_list = re.findall(r'<item data=\"(.*?)\" />', r.text, re.DOTALL)
    print(data_list)
    if len(data_list) == 0:
        print(f'"{symbol}" invalid symbol or has no data')
        return pd.DataFrame()
    data = '\n'.join(data_list)
    df = pd.read_csv(StringIO(data), delimiter='|', header=None, dtype={0:str})
    df.columns  = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    df['Date'] = pd.to_datetime(df['Date'], format='%Y%m%d')
    df.set_index('Date', inplace=True)
    df.sort_index(inplace=True)
    df['Change'] = df['Close'].pct_change()

    print(df)

_naver_data_reader('005930')
