import json
import locale
import sys
import time
from datetime import (datetime, timedelta)

import requests
from tzlocal import (get_localzone)

from schwab_api import (get_account_balance, place_order, get_quotes, get_account_positions, get_transactions)
from schwab_auth import (SchwabAuth)
from transactions import (find_transaction_groups, dump_transaction_groups)


NO_EXTREME = -1
NO_LIMIT = -1
EXTREME_EXPIRATION_SECONDS = 60 * 30  # 30 minutes


_advanced_commands = [
    {
        "name": "quote",
        "prompt": "quote [symbol1,symbol2,...]",
        "help": "Get quotes (current prices) for symbols",
        "function": lambda parts, schwab_auth: _do_quote(parts, schwab_auth)
    },
    {
        "name": "order",
        "prompt": "order [b | s | bs | ss | ts] [symbol] [num shares] <limit | offset (for 'ts') | 'ask' | 'bid'>",
        "help": "Place an order to buy/sell/buy stop/sell stop/trailing stop",
        "function": lambda parts, schwab_auth: do_order(parts, schwab_auth),
    },
    {
        "name": "bal",
        "prompt": "bal <repeat delay>",
        "help": "Show account balance, optionally repeating",
        "function": lambda parts, schwab_auth: _do_bal(parts, schwab_auth),
    },
    {
        "name": "pos",
        "prompt": "pos <symbol1,symbol2,...> <repeat delay>",
        "help": "Show positions for specified symbols (if none, show all holdings), optionally repeating",
        "function": lambda parts, schwab_auth: _do_pos(parts, schwab_auth)
    },
    {
        "name": "trend",
        "prompt": "trend [symbol] <ref_price>",
        "help": "Show trend of symbol's price every 30 seconds, displaying current price relative to the reference price",
        "function": lambda parts, schwab_auth: _do_trend(parts, schwab_auth)
    },
    {
        "name": "buylow",
        "prompt": "[buylow | sellhigh] [symbol] [num shares] [change<%>] <extreme> <limit>",
        "help": "Emulate a trailing stop but use for entering a position",
        "function": lambda parts, schwab_auth: _do_buylow(parts, schwab_auth),
    },
    {
        "name": "sellhigh",
        "prompt": "",  # buylow's prompt is used for sellhigh also
        "function": lambda parts, schwab_auth: _do_sellhigh(parts, schwab_auth),
    },
    {
        "name": "breakout",
        "prompt": "[breakout | oscillate] [symbol] [shares] [low] [high] <-- EXPERIMENTAL",
        "help": "Enter position when stock price breaks out of, or oscillates within, low/high range",
        "function": lambda parts, schwab_auth: _do_breakout(parts, schwab_auth)
    },
    {
        "name": "oscillate",
        "prompt": "",  # breakout's prompt is used for oscillate also
        "function": lambda parts, schwab_auth: _do_oscillate(parts, schwab_auth)
    },
    {
        "name": "trans",
        "prompt": "trans [symbol1,symbol2,...] <days ago> <-- EXPERIMENTAL",
        "help": "Show transactions from last <days ago> for specified symbols",
        "function": lambda parts, schwab_auth: _do_trans(parts, schwab_auth)
    },
    {
        "name": "flatten",
        "prompt": "flatten <-- EXPERIMENTAL",
        "help": "Cover all open positions by buying or selling them at the current price, as appropriate",
        "function": lambda parts, schwab_auth: _do_flatten(parts, schwab_auth),
    },
    {
        "name": "code",
        "prompt": "code <filename> <-- EXPERIMENTAL",
        "help": "Execute code from file.  The code has access to all of this program's Python functions.",
        "function": lambda parts, schwab_auth: _do_code(parts, schwab_auth)
    },
    {
        "name": "refport",
        "prompt": "refport <repeat delay> <-- EXPERIMENTAL",
        "help": "Show current value of a (previously hard-coded) reference portfolio, optionally repeating",
        "function": lambda parts, schwab_auth: _do_reference_port(parts, schwab_auth),
    },
    {
        "name": "q",
        "prompt": "q (quit)",
        "help": "Quit the program",
        "function": lambda parts, schwab_auth: sys.exit(0)
    },
]


def show_help():
    for command in _advanced_commands:
        help = command.get('help')
        if help:
            print(f"{command['prompt']}: {command['help']}")

def exec_command(cmd_name: str, parts: list[str], schwab_auth: SchwabAuth):
    cmd: dict = next((command for command in _advanced_commands if command["name"] == cmd_name), None)
    if not cmd:
        print(f"Error:  Invalid command: {cmd_name}")
        return
    cmd["function"](parts, schwab_auth)

def get_command_prompt(cmd_name: str = None) -> str|None:
    cmd: dict = next((command for command in _advanced_commands if command["name"] == cmd_name), None)
    return cmd["prompt"] if cmd else None


def get_command_prompts() -> list[str]:
    prompts = []
    for cmd in _advanced_commands:
        if cmd["prompt"]:
            prompts.append(cmd["prompt"])
    return prompts  # [f"\t{cmd['prompt'].expandtabs()}" for cmd in _advanced_commands if cmd['prompt']]


def _do_quote(parts: list[str], schwab_auth: SchwabAuth):
    symbols: str = ' '.join(parts[1:]).strip()
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
            print(*prices, sep='\n')

def do_order(parts: list[str], schwab_auth: SchwabAuth):
    if len(parts) < 1:
        print(f"Error:  Invalid order --- order start with one of: 'b' (buy), 's' (sell), 'bs' (buy stop), 'ss' (sell stop), 'ts' (trail stop))")
        return

    instruction = parts[1]
    if instruction not in ('b', 's', 'bs', 'ss', 'ts'):
        print(f"Error:  Invalid order --- instruction must be one of 'b', 's', 'bs', 'ss', 'ts'")
        return

    if len(parts) < 3:
        print(f"Error:  Invalid order --- order must contain symbol and number of shares")
        return

    symbol = parts[2]
    shares = int(parts[3])
    limit_price = parts[4] if len(parts) > 4 else None
    resp: requests.Response = place_order(schwab_auth, instruction, symbol, shares, limit_price)
    result: str = resp.text if resp.text else "OK" if resp.ok else "Something went wrong"
    print(result)
    return

def _do_bal(parts: list[str], schwab_auth: SchwabAuth):
    seconds: int = int(parts[1]) if len(parts) > 1 else 0
    while True:
        try:
            account_balance: float = get_account_balance(schwab_auth)
            if not seconds:
                print(f"Account balance: ${account_balance:,}")
                break
            now = datetime.now()
            print(f'{now.strftime("%X")}: ${account_balance:,}')
            time.sleep(seconds)
        except KeyboardInterrupt:
            break

def _do_pos(parts: list[str], schwab_auth: SchwabAuth):
    """
    Args:
        <symbol1,symbol2,...>: List of symbols to show positions for, or empty string to show all positions
        <refresh_interval>: Number of seconds between refresh of positions, or 0 to show only once

        if first part is an int, it is the refresh_interval, else
        it is the symbol list and second part, if present, is the refresh interval
    """
    seconds: int = 0
    symbols_str: str = ""
    if len(parts) > 1:
        if parts[1].isdigit():
            seconds = int(parts[1])
        else:
            symbols_str: str = parts[1].strip().upper()
            if len(parts) > 2:
                seconds = int(parts[2])
    while True:
        try:
            if seconds:
                now = datetime.now()
                print(f"{now.hour:02}:{now.minute:02}:{now.second:02}")
            show_pos(symbols_str, schwab_auth)
            if not seconds:
                break
            time.sleep(seconds)
        except KeyboardInterrupt:
            break

def _do_trend(parts: list[str], schwab_auth: SchwabAuth):
    """Computes the trend of a single symbol compared to a reference price in units of 0.01%"""
    symbol = parts[1]
    ref_price = float(parts[2]) if len(parts) > 2 else None
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

def _do_sellhigh(parts: list[str], schwab_auth: SchwabAuth):
    symbol = parts[1]
    numshares = int(parts[2])
    change_or_percent_change: str = parts[3]  # good default is "0.025%"
    extreme = float(parts[4]) if len(parts) > 4 else NO_EXTREME
    limit = float(parts[5]) if len(parts) > 5 else NO_LIMIT
    try:
        _buylow_sellhigh(schwab_auth, False, symbol, numshares, change_or_percent_change, extreme, limit)
    except Exception as e:
        print(e)

def _do_breakout(parts: list[str], schwab_auth: SchwabAuth):
    try:
        symbol = parts[1]
        numshares = int(parts[2])
        low_target = float(parts[3])
        high_target = float(parts[4])
        enter_position(schwab_auth, symbol, numshares, low_target, high_target, breakout=True)
    except Exception as e:
        print(e)

def _do_oscillate(parts: list[str], schwab_auth: SchwabAuth):
    try:
        symbol = parts[1]
        numshares = int(parts[2])
        low_target = float(parts[3])
        high_target = float(parts[4])
        enter_position(schwab_auth, symbol, numshares, low_target, high_target, breakout=False)
    except Exception as e:
        print(e)

def _do_trans(parts: list[str], schwab_auth: SchwabAuth):
    """"
    Show transactions for specified symbols occurring with specified day.
    Show transactions formed into groups denoted when position was entered and exited.
    """
    symbols: list[str] = parts[1].strip().upper().split(',')
    days_ago: int = int(parts[2]) if len(parts) > 2 else 0
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

#####

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

def show_pos(symbols_str: str, schwab_auth: SchwabAuth):
    resp: requests.Response = get_account_positions(schwab_auth)
    if not resp.ok:
        print(f"Error getting positions")
        return
    account_positions = json.loads(resp.text)
    positions: list = account_positions[0]["securitiesAccount"]["positions"]

    if not symbols_str:  # fill with all account positions
        symbols_str = ','.join([p["instrument"]["symbol"] for p in positions])

    quotes: dict = {}
    if symbols_str:
        quotes = get_quotes(symbols_str, schwab_auth)
        if not quotes:
            print("Error getting quotes")
            return

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
                    printed = True
                else:
                    print(f"{symbol}:  Unable to retrieve quote (is symbol misspelled?)")
                    printed = True
        else:  # no specific stocks specified ==> show all stocks which have positions
            # Show position only
            print(f"{symbol}: {quantity} @ {average_price}")
            printed = True
    if len(symbols) > 1 and abs(total_gain_loss) > 0.0:
        print("----")
        print(f"Total gain/loss: {total_gain_loss:,.2f}")
        print()
    elif not printed:
        print(f"No open positions")
        print()


#####

def _do_flatten(parts: list[str], schwab_auth: SchwabAuth):
    resp: requests.Response = get_account_positions(schwab_auth)
    if not resp.ok:
        print(f"Error getting positions")
        return

    account_positions = json.loads(resp.text)
    positions: list = account_positions[0]["securitiesAccount"]["positions"]
    for p in positions:
        symbol = p["instrument"]["symbol"]
        quantity: int = int(p["longQuantity"]) - int(p["shortQuantity"])
        instruction = 's' if quantity > 0 else 'b'
        quantity = abs(quantity)
        resp: requests.Response = place_order(schwab_auth, instruction, symbol, quantity)
        if not resp.ok:
            print(f"Error disposing of {symbol}: {quantity} shares: instruction is {instruction}")

def _do_code(parts: list[str], schwab_auth: SchwabAuth):
    filename: str = ' '.join(parts[1:]).strip()
    try:
        with open(filename, 'rt') as f:
            code_str: str = f.read()
            print(f"Executing code: {code_str}")
            exec(code_str, globals(), {})
    except FileNotFoundError:
        print(f"Error: The file '{filename}' was not found.")
    except IOError:
        print(f"Error: There was an issue reading the file '{filename}'.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

def _do_reference_port(parts: list[str], schwab_auth: SchwabAuth):
    flattened_portfolio = {
        "ANET": (5, 91.85),
        "RDDT": (10, 160.20),
        "NVDA": (2, 121.80),
        "IBIT": (10, 47.56),
    }

    '''
    flattened_portfolio_full = {
        "TJX": (1, 124.14),
        "RDDT": (10, 200.172),
        "NVDA": (5, 138.44),
        "IBIT": (10, 55.74),
        "NFLX": (2, 1059.065),
        "AAPL": (10, 244.15),
        "TTD": (15, 80.76),
    }
    '''

    symbols = ",".join(flattened_portfolio.keys())
    seconds: int = int(parts[1]) if len(parts) > 1 else 0
    while True:
        try:
            quotes = get_quotes(symbols, schwab_auth)
            if not quotes:
                print("Error getting quotes")
                return
            total_net = 0.0
            total_flattened_net = 0.0
            if seconds:
                now = datetime.now()
                print(f"{now.hour:02}:{now.minute:02}:{now.second:02}")
            for symbol, value in flattened_portfolio.items():
                price = quotes[symbol]["quote"]["lastPrice"]
                quantity = value[0]
                flattened_price = value[1]
                net = quantity * price
                flattened_net = quantity * flattened_price
                total_net += net
                total_flattened_net += flattened_net
                print(f"{symbol}: {quantity} @ {flattened_price:,.2f} (Current: {price:,.2f}) = {(flattened_net - net):,.2f}")
            print("----")
            print(f"Net value of equities: {total_flattened_net:,.2f} (Current: {total_net:,.2f}) = {(total_flattened_net - total_net):,.2f}")
            print()
            if not seconds:
                break
            time.sleep(seconds)
        except KeyboardInterrupt:
            break
