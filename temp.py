#%% 
from financials.tools.dc_tools import get_main_financial_reports_db
from financials.collect.gen_financial_records import single_company_data_collect

# fr_dv = get_main_financial_reports_db()

# code = '450080'
# ec = fr_dv.loc[(fr_dv['code']==code) & (fr_dv['fs_div'] == 'CFS')]
# ecc = fr_dv.loc[(fr_dv['code']==code) & (fr_dv['fs_div'] == 'OFS')]

# # for col in ec.columns:
# #     if not ec[col].isna().all():
# #         print(col)

# # for col in ecc.columns:
# #     if not ecc[col].isna().all():
# #         print(col)
# # print(ec)
# # print(ec['2026_1Q'])
# # print(ecc['2026_1Q'])

# # fr = single_company_data_collect(code)
# # print(fr['2026_2Q'])
# print(fr_dv.loc[fr_dv['code']==code]['2026_2Q'])


#%% 
import json
from pathlib import Path
import requests
import pandas as pd
from data.util.load import get_prices

print(get_prices())

CONFIG_DIR = Path(__file__).parent.parent / 'config'
with open(CONFIG_DIR / 'KRX_openapi.json', 'r') as json_file:
    KRX_openapi_key = json.load(json_file)['KRX_openapi']

df_krx = pd.read_feather(Path(__file__).parent / 'collect/data/df_krx.feather')
print(df_krx)
print(df_krx.columns)

def get_date_str():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd'
    }
    url = 'http://data.krx.co.kr/comm/bldAttendant/executeForResourceBundle.cmd?baseName=krx.mdc.i18n.component&key=B128.bld'
    try: 
        r = requests.get(url, headers=headers)
        j = json.loads(r.text)
        return j['result']['output'][0]['max_work_dt']
    except:
        return None

KRX_URL = "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd"

def get_krx_stocks(bas_dd: str) -> list[dict]:
    response = requests.get(
        KRX_URL,
        headers={
            "AUTH_KEY": KRX_openapi_key
        },
        params={"basDd": bas_dd},
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(
            f"KRX API error {response.status_code}: {response.text}"
        )

    return response.json()["OutBlock_1"]

import datetime
import time


for i in range(100):
    print(datetime.datetime.now())
    date_str = get_date_str()
    print(date_str)
    a = get_krx_stocks(date_str)
    a = pd.DataFrame(a)
    print(a)
    # print(a[0].keys())
    # print(len(a))
    # print(a[0])

    time.sleep(20)


