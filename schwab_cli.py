import locale
import os
import sys
from datetime import (datetime)

import dotenv

from commands import (show_help, get_command_prompts, get_command_prompt, exec_command)
from schwab_auth import (SchwabAuth)


# Status:  Production


def process_line(line: str, schwab_auth: SchwabAuth) -> str|None:
    """Returns None if line does not contain a single command (valid or not), else returns the name of the command"""
    line = line.strip()
    parts = line.split(' ')
    if len(parts) < 1:
        return None

    # Try executing as an advanced command first
    cmd = parts[0]
    exec_command(cmd, parts, schwab_auth)
    return cmd


def repl(initial_line, schwab_auth: SchwabAuth):
    refresh_token_expiration: datetime = schwab_auth.refresh_token_expected_expiration_time()
    print(f"Refresh token expected expiration:  {refresh_token_expiration}; in {(refresh_token_expiration - datetime.now()).days:.1f} days.")
    if initial_line:
        process_line(initial_line, schwab_auth)

    usage_prompt = ""
    for advanced_prompt in get_command_prompts():
        usage_prompt += f"{advanced_prompt}\n"
    while True:
        prompt = None
        print()
        line = input("Enter a command (leave blank for help) then press Return> ")
        if not line:
            show_help()
        else:
            cmd = process_line(line, schwab_auth)
            '''
            if cmd:
                cmd_prompt = get_command_prompt(cmd)
                if cmd_prompt:
                    prompt = cmd_prompt
            '''
            if prompt:
                print(prompt)


def InitSchwabAuth() -> SchwabAuth|None:
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
        return None

    return SchwabAuth(app_key, app_secret)


def main(schwab_auth: SchwabAuth):
    args = sys.argv[1:]  # all but program name
    initial_line = " ".join(args) if len(args) > 0 else None
    repl(initial_line, schwab_auth)


if __name__ == "__main__":
    schwab_auth = InitSchwabAuth()
    if schwab_auth:
        main(schwab_auth)
