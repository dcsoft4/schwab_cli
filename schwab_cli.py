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
from schwab_api import (get_my_account_number, get_account_balance, monitor_balance, place_order, get_quotes, get_account_positions,
get_transactions, get_orders, delete_order, delete_working_orders)
from advanced_commands import (exec_advanced_command)

# Status:  Production


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
    elif exec_advanced_command(cmd, parts, schwab_auth):
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
            "\tquote [symbol1,symbol2,...]\n"
            "\tpos [symbol1,symbol2,...]\n"
            "\tposloop [symbol1,symbol2,...]\n"
            # "\t[buylow | sellhigh] [symbol] [num shares] [change<%>] <extreme> <limit>\n"
            # "\t[breakout | oscillate] [symbol] [num shares] [low price] [high price]\n"
            # "\ttrend [symbol] <ref price>\n"
            # "\tport<folio>\n"
            # "\ttrans<actions> [symbol1,symbol2,...] <days ago>\n"
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
