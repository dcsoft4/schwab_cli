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
from schwab_api import (get_my_account_number, get_account_balance, monitor_balance, place_order, get_quotes, get_account_positions,
get_transactions, get_orders, delete_order, delete_working_orders)
from transactions import (find_transaction_groups, dump_transaction_groups)
from orders import (find_working_orders, WorkingOrder)

# Status:  Experimental



NO_EXTREME = -1
NO_LIMIT = -1
EXTREME_EXPIRATION_SECONDS = 60 * 30  # 30 minutes



_advanced_commands = [
    {
        "name": "buylow",
        "function": lambda parts, schwab_auth: _do_buylow(parts, schwab_auth),
    }
]


def exec_advanced_command(name: str, parts: list[str], schwab_auth: SchwabAuth) -> bool:
    cmd: dict = next((command for command in _advanced_commands if command["name"] == name), None)
    if not cmd:
        return False
    cmd["function"](parts, schwab_auth)
    return True


def _do_buylow(parts: list[str], schwab_auth: SchwabAuth):
    symbol = parts[1]
    numshares = int(parts[2])
    change_or_percent_change: str = parts[3]  # good default is "0.025%"
    extreme = float(parts[4]) if len(parts) > 4 else NO_EXTREME
    limit = float(parts[5]) if len(parts) > 5 else NO_LIMIT
    try:
        _buylow_sellhigh(schwab_auth, True, symbol, numshares, change_or_percent_change, extreme, limit)
    except Exception as e:
        print(e)

def _buylow_sellhigh(schwab_auth, islow: bool, symbol: str, numshares: int, change_or_percent_change: str,
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
