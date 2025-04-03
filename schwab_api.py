import json
import time
from datetime import (datetime, timedelta)
from zoneinfo import (ZoneInfo)

import requests
from tzlocal import (get_localzone)

from orders import (find_working_orders, WorkingOrder)
from schwab_auth import (SchwabAuth)


TRADER_API_ROOT = "https://api.schwabapi.com/trader/v1"
MARKETDATA_API_ROOT = "https://api.schwabapi.com/marketdata/v1"



_my_account_number: str | None = None  # Access with get_my_account_number()

def get_my_account_number(schwab_auth: SchwabAuth) -> str:
    global _my_account_number
    if not _my_account_number:
        resp = requests.get(f'{TRADER_API_ROOT}/accounts/accountNumbers', headers=schwab_auth.headers())
        if not resp.ok:
            return resp.text if resp.text else "Something went wrong"
        j = json.loads(resp.text)
        _my_account_number = j[0]["hashValue"]

    return _my_account_number


def get_account_balance(schwab_auth: SchwabAuth):
    params = {
        'fields': 'positions',
    }
    resp = requests.get(f'{TRADER_API_ROOT}/accounts', params=params, headers=schwab_auth.headers())
    if not resp.ok:
        return resp.text if resp.text else "Something went wrong"
    j = json.loads(resp.text)
    account_balance = j[0]["securitiesAccount"]["currentBalances"]["equity"]
    return account_balance


def place_order(schwab_auth: SchwabAuth, instruction: str, symbol: str, numshares: int,
                limit_or_offset_or_bid_or_ask: float | str | None = None) -> requests.Response:
    """
    instruction is:
        'b' or 'buy' - buy
        's' or 'sell' - sell
        'bs' - buy stop
        'ss' - sell stop
        'bts' - buy trailing stop
        'sts' - sell trailing stop

    limit_or_offset_or_bid_or_ask is:
        a float -- the limit price, unless instruction is 'ts', then it is the offset,
        a string -- 'bid' or 'ask',
        None -- Market order
    """

    symbol = symbol.upper()

    delete_working_orders(schwab_auth, symbol)

    if limit_or_offset_or_bid_or_ask == 'bid' or limit_or_offset_or_bid_or_ask == 'ask':
        # get quote of the symbol to use the current bid/ask
        quotes: dict = get_quotes(symbol, schwab_auth)
        q = quotes[symbol]['quote']
        limit_or_offset = q['bidPrice'] if limit_or_offset_or_bid_or_ask == 'bid' else q['askPrice']
    elif limit_or_offset_or_bid_or_ask:
        limit_or_offset = float(limit_or_offset_or_bid_or_ask)
    else:
        limit_or_offset = None

    order_type = "TRAILING_STOP" if instruction == "bts" or instruction == 'sts' else \
        "STOP" if instruction == 'ss' or instruction == 'bs' else \
            "LIMIT" if limit_or_offset else "MARKET"
    is_trailing_stop = order_type == "TRAILING_STOP"
    is_stop = order_type == "STOP"

    # Just use B or S and the server will automatically know if it is short-related
    instruction = instruction.lower()
    if instruction == 'b' or instruction == 'buy' or instruction == 'bs' or instruction == 'bts':
        instruction = "BUY"
    elif instruction == 's' or instruction == 'sell' or instruction == 'ss' or instruction == 'sts':
        instruction = "SELL"
    else:
        assert False, f'Illegal instruction: {instruction}'

    data = {
        "orderType": order_type,
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "orderLegType": 'EQUITY',
                "instruction": instruction,
                "quantity": numshares,
                "quantityType": 'SHARES',
                "instrument": {
                    "symbol": symbol,
                    "assetType": "EQUITY"
                }
            }
        ]
    }

    if is_trailing_stop:
        data["stopPriceLinkBasis"] = 'LAST'
        data["stopPriceLinkType"] = 'VALUE'
        data["stopPriceOffset"] = limit_or_offset
        data["stopType"] = 'STANDARD'
    elif is_stop:
        data["complexOrderStrategyType"] = "NONE"
        data["stopPrice"] = limit_or_offset
    elif limit_or_offset:
        data["complexOrderStrategyType"] = "NONE"
        data["price"] = limit_or_offset

    data = json.dumps(data)  # Must be a string, since the Content-Type is "application/json"

    headers = schwab_auth.headers()
    headers["Content-Type"] = "application/json"  # necessary????
    resp = requests.post(f'{TRADER_API_ROOT}/accounts/{get_my_account_number(schwab_auth)}/orders', data=data,
                         headers=headers)
    return resp


def get_quotes(symbols: str, schwab_auth: SchwabAuth) -> dict | None:
    params = {
        'symbols': symbols,
        'fields': 'quote,reference'
    }

    resp = requests.get(f'{MARKETDATA_API_ROOT}/quotes', params=params, headers=schwab_auth.headers())
    quotes: dict = json.loads(resp.text) if resp.ok else None
    return quotes


def get_account_positions(schwab_auth: SchwabAuth) -> requests.Response:
    params = {
        'fields': 'positions',
    }
    resp: requests.Response = requests.get(f'{TRADER_API_ROOT}/accounts', params=params, headers=schwab_auth.headers())
    return resp


def get_transactions(schwab_auth: SchwabAuth, symbol: str, start_date: datetime, end_date: datetime) -> list | None:
    """Return JSON string of transactions"""
    params = {
        'startDate': start_date.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%S.000Z'), # e.g. '2024-10-03T00:00:00.000Z'
        'endDate': end_date.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%S.000Z'),     # e.g. '2024-10-03T00:23:59.000Z'
        'symbol': symbol,
        'types': 'TRADE'
    }

    resp = requests.get(f"{TRADER_API_ROOT}/accounts/{get_my_account_number(schwab_auth)}/transactions", params=params,
                        headers=schwab_auth.headers())
    transactions: list = json.loads(resp.text) if resp.ok else None
    return transactions


def get_orders(schwab_auth: SchwabAuth, start_date: datetime = None, end_date: datetime = None) -> list | None:
    """Return JSON string of orders"""

    start_date = start_date if start_date else datetime.now(get_localzone()).replace(hour=0, minute=0, second=0)
    end_date = end_date if end_date else datetime.now(get_localzone()).replace(hour=23, minute=59, second=59)
    params = {
        'fromEnteredTime': start_date.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%S.000Z'), # e.g. '2024-10-03T00:00:00.000Z'
        'toEnteredTime': end_date.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%S.000Z'),     # e.g. '2024-10-03T00:23:59.000Z'
    }

    resp = requests.get(f"{TRADER_API_ROOT}/accounts/{get_my_account_number(schwab_auth)}/orders", params=params,
                        headers=schwab_auth.headers())
    orders: list = json.loads(resp.text) if resp.ok else None
    return orders


def delete_order(schwab_auth: SchwabAuth, order_id: str) -> requests.Response:
    return requests.delete(f"{TRADER_API_ROOT}/accounts/{get_my_account_number(schwab_auth)}/orders/{order_id}", headers=schwab_auth.headers())


def delete_working_orders(schwab_auth: SchwabAuth, symbol: str):
    """ Delete working orders for specified symbol that were placed within the past year.  This can be slow. """
    end_date: datetime = datetime.now(get_localzone())
    start_date = end_date - timedelta(days=365)
    working_orders: list[WorkingOrder] = find_working_orders(get_orders(schwab_auth, start_date, end_date), symbol)
    for order in working_orders:
        resp: requests.Response = delete_order(schwab_auth, order.order_id)
        print(
            f"Deleting working order {order.order_id}:  {order.instruction} {order.symbol} {order.shares}... {"OK" if resp.ok else resp.text}")

def show_working_orders(schwab_auth: SchwabAuth):
    """ Show working orders that were placed within the past year.  This can be slow. """
    end_date: datetime = datetime.now(get_localzone())
    start_date = end_date - timedelta(days=365)
    working_orders: list[WorkingOrder] = find_working_orders(get_orders(schwab_auth, start_date, end_date))
    print("Working orders:")
    for order in working_orders:
        print(f"  {order.order_id}:  {order.instruction} {order.symbol} {order.shares} @{order.price} {order.orderType}")
