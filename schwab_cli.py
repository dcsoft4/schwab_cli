import locale
import os
import sys
import time
from datetime import (datetime)

import dotenv
import requests

from advanced_commands import (get_advanced_prompts, exec_advanced_command)
from schwab_api import (place_order, get_quotes)
from schwab_auth import (SchwabAuth)


# Status:  Production

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



def process_line(line: str, schwab_auth: SchwabAuth):
    line = line.strip()
    parts = line.split(' ')
    if len(parts) < 1:
        return

    cmd = parts[0]

    # Try executing as an advanced command first
    if exec_advanced_command(cmd, parts, schwab_auth):
        return

    # If not an advanced command, treat as order instruction
    if len(parts) < 3:
        print(f"Enter at least 3 parts in line: {line}")
        return

    # TODO:  make a command -- must hardcode "b", "s", instructions, not accepting shortcuts like "buy" and "sell"
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
        print("Enter a command (or 'q' to quit):\n")
        prompt = "[b<uy> | s<ell> | bs | ss | ts] [symbol] [num shares] <limit | offset | 'ask' | 'bid'>\n"     # TODO make a command
        for advanced_prompt in get_advanced_prompts():
            prompt += f"{advanced_prompt}\n"
        # prompt += "> "
        line = input(prompt)
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
