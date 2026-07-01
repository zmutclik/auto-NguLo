import requests, time, os
from dotenv import load_dotenv

load_dotenv()

API_KEY  = os.getenv('OTPINSTAN_API_KEY')
BASE_URL = 'https://otpinstan.com/api/reseller'
HEADERS  = {'X-Api-Key': API_KEY, 'Content-Type': 'application/json'}

def api(endpoint, method='GET', data=None):
    url = f'{BASE_URL}/{endpoint}'
    try:
        if method == 'GET':
            resp = requests.get(url, headers=HEADERS)
        else:
            resp = requests.post(url, headers=HEADERS, json=data)
        resp.raise_for_status()
        if not resp.text.strip():
            print(f'[WARN] Empty response from {endpoint}')
            return {}
        return resp.json()
    except requests.exceptions.HTTPError as e:
        print(f'[HTTP ERROR] {e} | Body: {resp.text[:200]}')
        return {}
    except requests.exceptions.JSONDecodeError:
        print(f'[JSON ERROR] Non-JSON response from {endpoint}: {resp.text[:200]}')
        return {}

bal = api('balance.php')
if bal.get('balance') is not None:
    print(f"Saldo: Rp {bal['balance']:,}")
else:
    print(f"Gagal ambil saldo: {bal}")

# order = api('s1/order.php', 'POST', {'platform_id': 21, 'country_id': 7})
# if not order.get('success'):
#     print(f"Gagal: {order.get('message')}")
#     exit()

# print(f"Nomor: {order['phone']} | Order: {order['order_id']}")

# for i in range(240):
#     time.sleep(5)
#     check = api(f"s1/check.php?order_id={order['order_id']}")
#     if check.get('otp'):
#         print(f"OTP: {check['otp']}")
#         exit()

# time.sleep(35)
print(api('s1/cancel.php', 'POST', {'order_id': 'S5-550204352'}))


bal = api('balance.php')
if bal.get('balance') is not None:
    print(f"Saldo: Rp {bal['balance']:,}")
else:
    print(f"Gagal ambil saldo: {bal}")