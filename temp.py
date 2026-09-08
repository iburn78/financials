#%% 
from financials.tools.dc_tools import get_main_financial_reports_db
from financials.collect.gen_financial_records import single_company_data_collect

fr_dv = get_main_financial_reports_db()

code = '450080'
ec = fr_dv.loc[(fr_dv['code']==code) & (fr_dv['fs_div'] == 'CFS')]
ecc = fr_dv.loc[(fr_dv['code']==code) & (fr_dv['fs_div'] == 'OFS')]

# for col in ec.columns:
#     if not ec[col].isna().all():
#         print(col)

# for col in ecc.columns:
#     if not ecc[col].isna().all():
#         print(col)
# print(ec)
# print(ec['2026_1Q'])
# print(ecc['2026_1Q'])

# fr = single_company_data_collect(code)
# print(fr['2026_2Q'])
print(fr_dv.loc[fr_dv['code']==code]['2026_2Q'])