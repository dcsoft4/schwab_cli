import json
import os
import sys
import time
import locale
import requests
from datetime import (datetime, timedelta)
from zoneinfo import (ZoneInfo)
from tzlocal import (get_localzone)
import dotenv

from schwab_auth import (SchwabAuth)
from transactions import (find_transaction_groups, dump_transaction_groups)
from orders import (find_working_orders, WorkingOrder)

# Status:  Production


TRADER_API_ROOT = "https://api.schwabapi.com/trader/v1"
MARKETDATA_API_ROOT = "https://api.schwabapi.com/marketdata/v1"
NO_EXTREME = -1
NO_LIMIT = -1
EXTREME_EXPIRATION_SECONDS = 60 * 30  # 30 minutes

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


def monitor_balance(schwab_auth: SchwabAuth):
    while True:
        account_balance: float = get_account_balance(schwab_auth)
        now = datetime.now()
        print(f'{now.strftime("%X")}: ${account_balance:,}')
        if account_balance < 13560:
            print(f"BELOW $13560; sell if below $13550")
        elif account_balance > 13570:
            print(f"ABOVE $13570; sell if above $13580")

        time.sleep(30)


def place_order(schwab_auth: SchwabAuth, instruction: str, symbol: str, numshares: int,
                limit_or_offset_or_bid_or_ask: float | str | None = None) -> requests.Response:
    """
    instruction is:
        'b' or 'buy' - buy
        's' or 'sell' - sell
        'bs' - buy stop
        'ss' - sell stop
        'ts' - trailing stop

    limit_or_offset_or_bid_or_ask is a float, or can be a string ('bid' or 'ask'), or None
    """

    symbol = symbol.upper()

    delete_working_orders(schwab_auth, symbol)

    if limit_or_offset_or_bid_or_ask == 'bid' or limit_or_offset_or_bid_or_ask == 'ask':
        # get quote of the symbol to use the current bid/ask
        quotes: dict = get_quotes(symbol, schwab_auth)
        q = quotes[symbol]['quote']
        limit_or_offset = q['bidPrice'] if limit_or_offset_or_bid_or_ask == 'bid' else q['askPrice']
    else:
        limit_or_offset = limit_or_offset_or_bid_or_ask
    if limit_or_offset:
        limit_or_offset = float(limit_or_offset)

    order_type = "TRAILING_STOP" if instruction == "ts" else \
        "STOP" if instruction == 'ss' or instruction == 'bs' else \
            "LIMIT" if limit_or_offset else "MARKET"
    is_trailing_stop = order_type == "TRAILING_STOP"
    is_stop = order_type == "STOP"

    # Just use B or S and the server will automatically know if it is short-related
    instruction = instruction.lower()
    if instruction == 'b' or instruction == 'buy' or instruction == 'bs':
        instruction = "BUY"
    elif instruction == 's' or instruction == 'sell' or instruction == 'ss' or instruction == 'ts':
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


def buylow_sellhigh(schwab_auth, islow: bool, symbol: str, numshares: int, change_or_percent_change: str,
                    known_extreme: float, limit: float) -> None:
    """
    :param schwab_auth:
    :param islow: True if buying low, False if selling high
    :param symbol: Symbol to buy or sell
    :param numshares: Number of shares to buy or sell
    :param change_or_percent_change: Target amount of change, or the target percentage change if ending with '%'
    :param known_extreme: Use value of known extreme instead of retrieving current quote
    :param limit: Set Stop limit after buying or selling:  -1 means do not set a limit; 0 sets default limit; > 0 sets specified limit
    :return:
    """

    def mock_quoter(mock_symbol: str):
        """Return the next test quote each time.  Throws StopIteration when no more quotes."""
        test_quotes = [
            (0, 78.22),
            (78.22, 78.23),
            (78.23, 78.24),
            (78.23, 78.23),
            (78.23, 78.25),
            (78.25, 78.26),
            (78.26, 78.26),
            (78.26, 78.2),
        ]
        test_quotes_down = [
            (0, 78.22),
            (78.22, 78.23),
            (78.23, 78.23),
            (78.23, 78.22),
            (78.23, 78.22),
            (78.23, 78.22),
            (78.22, 78.22),
            (78.22, 78.22),
        ]

        for quote in test_quotes_down:
            yield {
                mock_symbol: {
                    'quote': {
                        'extremePrice': quote[0],

                        'lastPrice': quote[1],
                        'askPrice': quote[1],
                        'bidPrice': quote[1],
                    }
                }
            }

    symbol = symbol.upper()
    hold_extreme = known_extreme if known_extreme != NO_EXTREME else None
    extreme = hold_extreme if hold_extreme else sys.float_info.max if islow else 0
    time_extreme = datetime.now() if hold_extreme else None
    target_change: float | None = None if change_or_percent_change.endswith('%') else float(change_or_percent_change)
    print_count = 1
    mock: bool = False  # set to True if using mock_quoter

    if islow:
        print(f'Buying low {symbol} {numshares} (limit={limit})')
    else:
        print(f'Selling high {symbol} {numshares} (limit={limit})')

    if mock:
        mock_quoter = mock_quoter(symbol)

    while True:
        # Get current price
        if mock:
            try:
                quotes: dict = next(mock_quoter)
            except StopIteration:
                break
        else:
            quotes: dict|None = get_quotes(symbol, schwab_auth)

        if not quotes:
            print("Error getting quote, retrying...")
            time.sleep(2)
            continue

        q = quotes[symbol]['quote']
        last = q['lastPrice']
        ask = q['askPrice']
        bid = q['bidPrice']

        # experimental!!!! -- TOS shows last, do all calculations with last
        # ask = last
        # bid = last

        # Init target_change now that we have a quote and can calculate from desired percentage
        if not target_change:
            target_change_percent: float = float(change_or_percent_change[:-1])
            target_change = last * target_change_percent

        # Update extremes if current price exceeds
        now = datetime.now()
        if hold_extreme:
            if islow:
                if ask >= hold_extreme:  # current price validates hold_extreme (it isn't a one-off)
                    extreme = hold_extreme
                    time_extreme = now
                else:
                    hold_extreme = extreme  # reset to previously validated extreme
            else:
                if bid >= hold_extreme:  # current price validates hold_extreme (it isn't a one-off)
                    extreme = hold_extreme
                    time_extreme = now
                else:
                    hold_extreme = extreme  # reset to previously validated extreme
        if islow:
            if not hold_extreme or ask < hold_extreme:
                hold_extreme = ask
        else:
            if not hold_extreme or bid > hold_extreme:
                hold_extreme = bid

        # Exercise limit
        if limit > 0:
            if islow:
                # buy if price goes above limit
                is_limit_hit = last > limit
                instruction = 'b'
            else:
                # sell if price goes below limit
                is_limit_hit = last < limit
                instruction = 's'
            if is_limit_hit:
                line = f'{instruction} {symbol} {numshares}'
                print(line)
                # process_line(line, schwab_auth)
                resp: requests.Response = place_order(schwab_auth, instruction, symbol, numshares)
                print(resp.text if resp.text else "OK" if resp.ok else "Error placing buy order")
            return

        if mock:
            assert not extreme or q['extremePrice'] == extreme

        # Compute if target price is hit
        target = extreme + target_change if islow else extreme - target_change
        now = datetime.now()
        if islow:
            print(
                f'{print_count}: {now.hour:02}:{now.minute:02}:{now.second:02}: {symbol}; Hold extreme: {hold_extreme:.2f}; Extreme ASK: {extreme:.2f}; Ask: {ask}; '
                f'Target: {target} ({target_change:.2f})')
        else:
            print(
                f'{print_count}: {now.hour:02}:{now.minute:02}:{now.second:02}: {symbol}; Hold extreme: {hold_extreme:.2f}; Extreme BID: {extreme:.2f}; Bid: {bid}; '
                f'Target: {target} ({target_change:.2f})')
        is_target_hit = (ask > target) if islow else (bid < target)

        # Place order if target price is hit
        if is_target_hit:
            try:
                print('Target hit')
                if islow:
                    # Buy the stock
                    # line = f'b {symbol} {numshares} {bid}'
                    line = f'b {symbol} {numshares}'
                    print(line)
                    resp: requests.Response = place_order(schwab_auth, 'b', symbol, numshares, None)
                    print(resp.text if resp.text else "OK" if resp.ok else "Error placing buy order")
                    if resp.ok and not resp.text:
                        # Stock has been bought, set Stop
                        limit = bid - target_change if limit == 0 else limit
                        if limit > 0:  # is specified
                            limit = round(limit, 2)
                            line = f'ss {symbol} {numshares} {limit}'

                            time.sleep(5)
                            print(line)

                            resp: requests.Response = place_order(schwab_auth, 'ss', symbol, numshares, limit)
                            print(resp.text if resp.text else "OK" if resp.ok else "Error placing sell stop order")
                else:
                    # Sell the stock
                    # line = f's {symbol} {numshares} {bid}'
                    line = f's {symbol} {numshares}'
                    print(line)
                    resp: requests.Response = place_order(schwab_auth, 's', symbol, numshares, None)
                    print(resp.text if resp.text else "OK" if resp.ok else "Error placing sell order")
                    if resp.ok and not resp.text:
                        # Stock has been sold, set Stop
                        limit = bid + target_change if limit == 0 else limit
                        if limit > 0:  # is specified
                            limit = round(limit, 2)
                            line = f'bs {symbol} {numshares} {limit}'

                            time.sleep(5)
                            print(line)

                            resp: requests.Response = place_order(schwab_auth, 'bs', symbol, numshares, limit)
                            print(resp.text if resp.text else "OK" if resp.ok else "Error placing buy stop order")
            except Exception as e:
                print(e)
            return

        # Expire hold_extreme, as it has decayed and is no longer valid
        if time_extreme and (now - time_extreme) > timedelta(seconds=EXTREME_EXPIRATION_SECONDS):
            time_extreme = hold_extreme = None
            extreme = sys.float_info.max if islow else 0

        print_count += 1
        time.sleep(1)


def trend(readings: dict, symbol: str, chunk_secs: int) -> float:
    reading_chunks: list = []
    for dt, reading in readings.items():
        if reading["symbol"]:
            pass
    return 0.0


def compute_trend(schwab_auth, symbol: str, ref_price: float | None) -> float:
    """Computes the trend of a single symbol"""

    symbol = symbol.upper()
    accum: float = 0.0  # negative if falling, positive if rising, 0 if even
    start_time = datetime.now()
    if ref_price:
        print(
            f"{start_time.hour:02}:{start_time.minute:02}:{start_time.second:02}: Computing trend for {symbol}; ref price: {ref_price}; updates every 30 seconds; press ^C to stop")
    else:
        print(
            f"{start_time.hour:02}:{start_time.minute:02}:{start_time.second:02}: Computing trend for {symbol}; updates every 30 seconds; press ^C to stop")
    while True:
        now = datetime.now()
        try:
            quotes: dict|None = get_quotes(symbol, schwab_auth)
            if not quotes:
                print("Error getting quote, will keep trying")
            else:
                reading: float = float(quotes[symbol]['quote']['lastPrice'])
                if ref_price:
                    diff: float = ((reading - ref_price) / reading) * 10000
                    accum += diff
                    print(
                        f"{now.hour:02}:{now.minute:02}:{now.second:02}: {symbol}: {reading} ({diff:.2f}); Summary: {accum:.2f}")
                else:
                    print(f"{now.hour:02}:{now.minute:02}:{now.second:02}: {symbol}: {reading}")

                # Setup next loop
                ref_price = reading
            time.sleep(30)
        except KeyboardInterrupt:
            break
    print(f"{now.hour:02}:{now.minute:02}:{now.second:02}:  {symbol} Final summary: {accum:.2f}")
    return accum


def show_pos(symbols_str: str, schwab_auth: SchwabAuth):
    quotes: dict = {}
    if symbols_str:
        quotes = get_quotes(symbols_str, schwab_auth)
        if not quotes:
            print("Error getting quotes")
            return

    resp: requests.Response = get_account_positions(schwab_auth)
    if not resp.ok:
        print(f"Error getting positions")
        return

    account_positions = json.loads(resp.text)
    positions: list = account_positions[0]["securitiesAccount"]["positions"]
    total_gain_loss: float = 0.0
    symbols: list[str] = symbols_str.split(',') if symbols_str else []
    printed: bool = False
    for p in positions:
        symbol = p["instrument"]["symbol"]
        quantity: int = int(p["longQuantity"]) - int(p["shortQuantity"])
        average_price: float = float(p["averageLongPrice"]) if "averageLongPrice" in p else float(
            p["averageShortPrice"])
        if symbols:  # specific stocks specified
            if symbol in symbols:
                # Try to show quote for specified stock
                quote = quotes.get(symbol)
                if quote:
                    last_price: float = quote["quote"]["lastPrice"]
                    gain_loss = float(quantity * (last_price - average_price))
                    total_gain_loss += gain_loss
                    print(f"{symbol}: {quantity} @ {average_price} ({last_price}); gain/loss: {gain_loss:.2f}")
                else:
                    print(f"{symbol}:  Unable to retrieve quote (is symbol misspelled?)")
                    printed = True
        else:  # no specific stocks specified ==> show all stocks which have positions
            # Show position only
            print(f"{symbol}: {quantity} @ {average_price}")
            printed = True
    if abs(total_gain_loss) > 0.0:
        print("----")
        print(f"Total gain/loss: {total_gain_loss:,.2f}")
        print()
    elif not printed:
        print(f"No open positions")
        print()


def enter_position(schwab_auth, symbol: str, numshares: int, low_target: float, high_target: float, breakout: bool):
    symbol = symbol.upper()
    start_time = datetime.now()
    print(
        f"{start_time.hour:02}:{start_time.minute:02}:{start_time.second:02}: Waiting to enter position for {symbol} {numshares}")
    print_count = 1
    target_hit: bool = False
    while not target_hit:
        now = datetime.now()
        quotes: dict|None = get_quotes(symbol, schwab_auth)
        if not quotes:
            print("Error getting quote, retrying...")
        else:
            last: float = quotes[symbol]["quote"]["lastPrice"]
            target_hit = last < low_target or last > high_target
            print(
                f'{print_count}: {now.hour:02}:{now.minute:02}:{now.second:02}: {low_target} <= {symbol} {last:.2f} <= {high_target}')
            if target_hit:
                # execute order
                if breakout:
                    instruction = 'b' if last > high_target else 's'
                else:  # oscillate
                    instruction = 's' if last > high_target else 'b'

                print(
                    f'{"Breakout" if breakout else "Oscillate"} target met; placing order with instruction: {instruction}...')
                resp: requests.Response = place_order(schwab_auth, instruction, symbol, numshares)
                print(
                    resp.text if resp.text else "OK" if resp.ok else f"Error placing order with instruction: {instruction}")
            print_count += 1
        time.sleep(1)


def enter_breakout(schwab_auth, symbol: str, numshares: int, low_target: float, high_target: float):
    enter_position(schwab_auth, symbol, numshares, low_target, high_target, True)


def enter_oscillate(schwab_auth, symbol: str, numshares: int, low_target: float, high_target: float):
    enter_position(schwab_auth, symbol, numshares, low_target, high_target, False)


def wait_then(schwab_auth, symbol: str, conditional_code: str, action_cmd: str, print_code: str):
    while True:
        q: dict|None = get_quotes(f'{symbol}', schwab_auth)[f'{symbol}']['quote']
        if not q:
            print("Error getting quote, retrying...")
        else:
            last = q['lastPrice']
            bid = q['bidPrice']
            ask = q['askPrice']
            exec(print_code, globals(), {'last': last, 'bid': bid, 'ask': ask})
            if eval(conditional_code):
                process_line(action_cmd, schwab_auth)
                break
        time.sleep(1)


def dump_transactions(schwab_auth: SchwabAuth, symbols: list[str], days_ago: int):
    """
    Show transactions for specified symbols occurring with specified day.
    Show transactions formed into groups denoted when position was entered and exited.
    :param schwab_auth:
    :param symbols:
    :param days_ago:
    """
    start_date = datetime.now(get_localzone()).replace(hour=0, minute=0, second=0) - timedelta(days=days_ago)
    end_date = start_date.replace(hour=23, minute=59, second=59)
    print(f"{"/".join(symbols)}:  {start_date.strftime('%a %m/%d/%y')} - {end_date.strftime('%a %m/%d/%y')}")
    print("")

    total_profit: float = 0.00
    for symbol in symbols:
        symbol_profit: float
        print(f"{symbol}")
        symbol_profit =  dump_transaction_groups(find_transaction_groups(get_transactions(schwab_auth, symbol, start_date, end_date)))
        print(f"  {symbol} profit: {locale.currency(symbol_profit, grouping=True)}")
        total_profit += symbol_profit
    print(f"Total profit: {locale.currency(total_profit, grouping=True)}")


def process_line(line: str, schwab_auth: SchwabAuth):
    line = line.strip()
    parts = line.split(' ')
    if len(parts) < 1:
        return

    cmd = parts[0]
    if cmd == "bal":
        if len(parts) > 1:
            bal_cmd = parts[1]
            if bal_cmd == "mon":
                monitor_balance(schwab_auth)
            else:
                print(f"Invalid bal parameter: {bal_cmd}")
        else:
            account_balance: float = get_account_balance(schwab_auth)
            print(f"Account balance: ${account_balance:,}")
        return
    elif cmd.startswith("port"):
        resp: requests.Response = get_account_positions(schwab_auth)
        if resp.ok:
            account_positions = json.loads(resp.text)
            positions: list = account_positions[0]["securitiesAccount"]["positions"]
            daily_profits_by_position: list = [{"symbol": p["instrument"]["symbol"], "quantity": p["longQuantity"],
                                             "todayPct": p["currentDayProfitLossPercentage"],
                                             "today": p.get("pl_day")} for p in positions if
                                            p["longQuantity"] >= 1]
            print(*daily_profits_by_position, sep='\n')  # Source:  https://stackoverflow.com/questions/1523660/how-to-print-a-list-in-python-nicely
        else:
            result: str = resp.text if resp.text else "OK" if resp.ok else "Something went wrong"
            print(result)
        return
    elif cmd == "quote":
        symbols: str = line[len(cmd) + 1:].strip()
        if symbols:
            quotes: dict|None = get_quotes(symbols, schwab_auth)
            if not quotes:
                print("Error getting quotes")
            else:
                prices: list = []
                for symbol, q in quotes.items():
                    quote = q.get("quote")
                    if quote:
                        prices.append({"symbol": symbol, "last": quote["lastPrice"], "ask": quote["askPrice"],
                                       "bid": quote["bidPrice"]})
                print(*prices,
                      sep='\n')  # Source:  https://stackoverflow.com/questions/1523660/how-to-print-a-list-in-python-nicely
        return
    elif cmd == "buylow":
        symbol = parts[1]
        numshares = int(parts[2])
        change_or_percent_change: str = parts[3]  # good default is "0.025%"
        extreme = float(parts[4]) if len(parts) > 4 else NO_EXTREME
        limit = float(parts[5]) if len(parts) > 5 else NO_LIMIT
        try:
            buylow_sellhigh(schwab_auth, True, symbol, numshares, change_or_percent_change, extreme, limit)
        except Exception as e:
            print(e)
        return
    elif cmd == "sellhigh":
        symbol = parts[1]
        numshares = int(parts[2])
        change_or_percent_change: str = parts[3]  # good default is "0.025%"
        extreme = float(parts[4]) if len(parts) > 4 else NO_EXTREME
        limit = float(parts[5]) if len(parts) > 5 else NO_LIMIT
        try:
            buylow_sellhigh(schwab_auth, False, symbol, numshares, change_or_percent_change, extreme, limit)
        except Exception as e:
            print(e)
        return
    elif cmd == "breakout":
        symbol = parts[1]
        numshares = int(parts[2])
        low_target = float(parts[3])
        high_target = float(parts[4])
        try:
            enter_breakout(schwab_auth, symbol, numshares, low_target, high_target)
        except Exception as e:
            print(e)
        return
    elif cmd == "oscillate":
        symbol = parts[1]
        numshares = int(parts[2])
        low_target = float(parts[3])
        high_target = float(parts[4])
        try:
            enter_oscillate(schwab_auth, symbol, numshares, low_target, high_target)
        except Exception as e:
            print(e)
        return
    elif cmd == "trend":
        symbol = parts[1]
        ref_price = float(parts[2]) if len(parts) > 2 else None
        compute_trend(schwab_auth, symbol, ref_price)
        return
    elif cmd == "code":
        filename: str = line[len(cmd) + 1:].strip()
        try:
            with open(filename, 'rt') as f:
                code_str: str = f.read()
                print(f"Executing code:  {code_str}")
                exec(code_str, globals(), {})
        except FileNotFoundError:
            print(f"Error: The file '{filename}' was not found.")
        except IOError:
            print(f"Error: There was an issue reading the file '{filename}'.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        return
    elif cmd == "pos":
        symbols_str: str = line[len(cmd) + 1:].strip().upper()
        show_pos(symbols_str, schwab_auth)
        return
    elif cmd == "posloop":
        symbols_str: str = line[len(cmd) + 1:].strip().upper()
        while True:
            try:
                now = datetime.now()
                print(f"{now.hour:02}:{now.minute:02}:{now.second:02}")
                show_pos(symbols_str, schwab_auth)
                time.sleep(30)
            except KeyboardInterrupt:
                break
        return
    elif cmd.startswith("trans"):
        symbols: list[str] = parts[1].strip().upper().split(',')
        days_ago: int = int(parts[2]) if len(parts) > 2 else 0
        dump_transactions(schwab_auth, symbols, days_ago)
    elif cmd == "q":
        sys.exit(0)
    else:
        # Place order instruction
        if len(parts) < 3:
            print(f"Enter at least 3 parts in line:  {line}")
            return
        instruction = parts[0]
        symbol = parts[1]
        shares = int(parts[2])
        limit_price = parts[3] if len(parts) > 3 else None
        resp: requests.Response = place_order(schwab_auth, instruction, symbol, shares, limit_price)
        result: str = resp.text if resp.text else "OK" if resp.ok else "Something went wrong"
        print(result)
        return


def repl(initial_line, schwab_auth: SchwabAuth):
    refresh_token_expiration: datetime = schwab_auth.refresh_token_expected_expiration_time()
    print(f"Refresh token expected expiration:  {refresh_token_expiration}; in {(refresh_token_expiration - datetime.now()).days} days.")
    if initial_line:
        process_line(initial_line, schwab_auth)

    while True:
        print()
        print("Enter a command (or 'q' to quit):")
        line = input(
            "\t[b<uy> | s<ell> | bs | ss | ts] [symbol] [num shares] <limit | offset | 'ask' | 'bid'>\n"
            "\t[buylow | sellhigh] [symbol] [num shares] [change<%>] <extreme> <limit>\n"
            "\t[breakout | oscillate] [symbol] [num shares] [low price] [high price]\n"
            "\tquote [symbol1,symbol2,...]\n"
            "\ttrend [symbol] <ref price>\n"
            "\tpos [symbol1,symbol2,...]\n"
            "\tposloop [symbol1,symbol2,...]\n"
            "\tport<folio>\n"
            "\ttrans<actions> [symbol1,symbol2,...] <days ago>\n"
            "> ")
        process_line(line, schwab_auth)


def main(schwab_auth: SchwabAuth):
    args = sys.argv[1:]  # all but program name
    initial_line = " ".join(args) if len(args) > 0 else None
    repl(initial_line, schwab_auth)


if __name__ == "__main__":
    # Set the locale for currency formatting
    locale.setlocale(locale.LC_ALL, "en_US")

    # Load environment variables from file .\.env containing sensitive info that shouldn't be committed to git
    # See .\.env.sample for sample values (which don't work as-is, substitute them with the values specified in
    # your Schwab account settings, where you set up your application
    dotenv.load_dotenv()

    # Data required to generate a Schwab API refresh token, which is then used to generate an Access token used in Schwab web requests
    app_key = os.environ.get("SCHWAB_APP_KEY")              # e.g. "lL5apjgztC82RsFDaoJLeH7FqnHz5rnL"
    app_secret = os.environ.get("SCHWAB_APP_SECRET")        # e.g. "3gWeqCR7qDPeG1FD"
    if not app_key or not app_secret:
        print("FATAL ERROR:  One or more environment variables are missing, e.g. SCHWAB_APP_KEY, SCHWAB_APP_SECRET.")
        print("Please check your .env file (follow the pattern in .env.example) and try again.  Exiting.")
    else:
        schwab_auth = SchwabAuth(app_key, app_secret)
        main(schwab_auth)
