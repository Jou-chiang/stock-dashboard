import requests, os
r = requests.get('https://api.finmindtrade.com/api/v4/data', params={
    'dataset': 'TaiwanStockInstitutionalInvestorsBuySell',
    'data_id': '2330',
    'start_date': '2026-03-20',
    'token': os.environ.get('FINMIND_TOKEN','')
})
print(r.text[:500])
