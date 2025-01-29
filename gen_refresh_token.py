import os
from datetime import (datetime, timedelta)
from typing import Mapping
import requests
import base64
import urllib.parse
import json

import dotenv

from schwab_auth import (SchwabAuth)


# Status:  Production


"""
I am grateful for the following directions, upon which this script is based.

Reddit - GetOutOfMyForest
https://www.reddit.com/r/Schwab/comments/1bykadn/comment/l4c3b56/?utm_source=share&utm_medium=web3x&utm_name=web3xcss&utm_term=1&utm_content=share_button

You receive an authorization code in the address line of your browser after putting in an address something like this in your browser:
https://api.schwabapi.com/v1/oauth/authorize?client_id=xyzmy client idxyz&redirect_uri=https://127.0.0.1.

You have 30 seconds to scrape that authorization code, "decode it" and send it back programmatically to the auth server,
along with you base64 encoded ClientId:ClientSecret, in a form like this:
POST https://api.schwabapi.com/v1/oauth/token
    -H 'Authorization: Basic {BASE64_ENCODED_Client_ID:Client_Secret}
    -H 'Content-Type: application/x-www-form-urlencoded'
    -d 'grant_type=authorization_code&code={AUTHORIZATION_CODE_VALUE}&redirect_uri=https:127.0.0.1

Then you will get an access code and refresh code. The access code does not last long (cannot remember the number of
minutes or hrs) but the refresh code lasts for a week. You use that refresh code to renew your access code.
"""

api_root = "https://api.schwabapi.com/v1"

def get_auth_url_for_browser(app_key: str, callback_url: str) -> str:
    url = f"{api_root}/oauth/authorize?client_id={app_key}&response_type=code&redirect_uri={callback_url}"
    return url


def get_decoded_auth_code(redirected_url_from_browser: str) -> str:
    query_params = urllib.parse.urlparse(
        redirected_url_from_browser).query  # e.g. 'code=C0.b2F1dGgyLmJkYy5zY2h3YWIuY29t.95tVviFomWiJBcoFR-AA2S5qmWMUPRr1ptwaag7n1Os%40&session=d181f71b-7a00-4b49-81f4-a359c9986bd3'
    try:
        auth_code = urllib.parse.parse_qs(query_params)['code'][0]  # e.g. 'C0.b2F1dGgyLmJkYy5zY2h3YWIuY29t.95tVviFomWiJBcoFR-AA2S5qmWMUPRr1ptwaag7n1Os@'
    except KeyError:
        auth_code = None
    return auth_code


def get_token_request_headers(app_key: str, app_secret: str) -> Mapping:
    auth = f"{app_key}:{app_secret}"
    auth_bytes = auth.encode()
    auth_base64_bytes = base64.b64encode(auth_bytes)
    auth_base64_string = auth_base64_bytes.decode()
    headers = {
        'Authorization': f"Basic {auth_base64_string}",
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    return headers


def gen_refresh_token(auth_code: str, headers: Mapping, callback_url: str) -> str|None:
    token_url = f'{api_root}/oauth/token'
    data = {
        'grant_type': 'authorization_code',
        'code': auth_code,
        'redirect_uri': callback_url,
    }

    response = requests.post(token_url, headers=headers, data=data)
    if not response.ok:
        return None
    d = json.loads(response.text)
    return d['refresh_token']


def main():
    # Load environment variables from file .\.env containing sensitive info that shouldn't be committed to git
    # See .\.env.sample for sample values (which don't work as-is, substitute them with the values specified in
    # your Schwab account settings, where you set up your application
    dotenv.load_dotenv()
    app_key = os.environ.get("SCHWAB_APP_KEY")              # e.g. "lL5apjgztC82RsFDaoJLeH7FqnHz5rnL"
    app_secret = os.environ.get("SCHWAB_APP_SECRET")        # e.g. "3gWeqCR7qDPeG1FD"
    callback_url = os.environ.get("SCHWAB_CALLBACK_URL")    # e.g. "https://dcsoft.com/dev/schwab"

    headers = get_token_request_headers(app_key, app_secret)

    print("The Schwab API requires an Access token for each web request to get stock quotes, place trade orders, etc.")
    print(
        "To generate an Access token, you need a Refresh token. This script guides you through generating a Refresh token.")
    print()
    if not app_key or not app_secret or not callback_url:
        print("FATAL ERROR:  One or more environment variables are missing, e.g. SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_CALLBACK_URL.")
        print("Please check your .env file (follow the pattern in .env.example) and try again.  Exiting.")
        return

    print("Let's begin...")
    print()
    print("Paste the following url into a browser to login to Schwab.  Accept all prompts:")
    print(f"{get_auth_url_for_browser(app_key, callback_url)}")
    print()
    print(
        f"After you accept all the prompts, the browser is redirected to an url that appears in the browser's address line at the top of the window.")

    decoded_auth_code: str|None = None
    while not decoded_auth_code:
        print()
        redirected_url_from_browser: str = input(
            "You have 30 seconds to copy/paste the redirected url from the browser's address line here: ")
        decoded_auth_code = get_decoded_auth_code(redirected_url_from_browser)  # e.g. 'C0.b2F1dGgyLmJkYy5zY2h3YWIuY29t.95tVviFomWiJBcoFR-AA2S5qmWMUPRr1ptwaag7n1Os@'
        if not decoded_auth_code:
            print("Error:  The url you pasted is not a valid Schwab authorization url (it must contain 'code=').  Please try again.")

    print()
    refresh_token: str | None = gen_refresh_token(decoded_auth_code, headers, callback_url)
    if not refresh_token:
        print("Fatal error:  Something went wrong generating the Refresh token.  Please try again.  Exiting.")
        return

    # Save refresh token to auth.json, for use with SchwabAuth
    now = datetime.now()
    refresh_expiration_days = 7     # word on the street of how many days it lasts
    auth = {
        "refresh_token": refresh_token,
        "refresh_token_issue_time": str(now),
        "refresh_token_expected_expiration_time": str(now + timedelta(days=refresh_expiration_days)),

        # Invalidate Access token so on next use it will be regenerated using the new Refresh token
        "expiration_origin_time": "2000-01-01 00:00:00.000000",     # access token has expired long ago, it will be regenerated
        "expires_in": 0
    }

    with open('auth.json', 'w') as f:
        json.dump(auth, f, indent=4)

    print(f"Your new Refresh token is: {refresh_token}.")
    print("It has been saved to auth.json.  SchwabAuth will now test your Refresh token by using it to generate an Access token.")
    print()
    print("The Access token is placed into the request headers sent to the Schwab API.")
    print("Valid headers are formatted as {'Authorization': 'Bearer <Access token>'},")
    print("    where <Access token> is the Access token generated by SchwabAuth.")
    schwab_auth = SchwabAuth(app_key, app_secret)
    headers = schwab_auth.headers()
    print(f'Headers: {headers}')
    print()
    authorization = headers.get("Authorization")
    if not authorization or authorization.find('Bearer ') < 0:
        print("Fatal error:  The headers don't contain 'Bearer'.  Something went wrong generating the Access token.  Please try again.  Exiting.")
        return
    print("Success!  Your Refresh token is working.")
    print(f"You can now use SchwabAuth to generate Access tokens for the Schwab API, until the Refresh token expires in {refresh_expiration_days} days.")
    print("Then you must re-run this script to generate a new Refresh token.")


if __name__ == "__main__":
    main()
