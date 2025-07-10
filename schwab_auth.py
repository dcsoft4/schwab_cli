import base64
import json
import os
from datetime import (datetime, timedelta)
from typing import (Mapping)

import dotenv
import requests
from dateutil import parser



api_root = "https://api.schwabapi.com/v1"


class SchwabAccessTokenException(Exception):
    """
    This exception is thrown when an Access token could not be generated.
    """
    def __init__(self, message):
        super().__init__(message)


class SchwabAuth:
    def __init__(self, app_key: str, app_secret: str):
        self.app_key: str = app_key
        self.app_secret: str = app_secret
        self.auth: dict = self._load_auth()

    def _load_auth(self) -> dict:
        # Load auth.json
        try:
            with open('auth.json', 'r') as f:
                auth = json.load(f)
                return auth
        except FileNotFoundError:
            print("FATAL ERROR:  auth.json is not found.  Run gen_refresh_token.py to generate it.")
            exit(1)

    def _get_token_request_headers(self) -> Mapping[str, str]:
        auth = self.app_key + ':' + self.app_secret
        auth_bytes = auth.encode('utf-8')
        auth_base64_bytes = base64.b64encode(auth_bytes)
        auth_base64_string = auth_base64_bytes.decode('utf-8')
        headers = {
            'Authorization': f"Basic {auth_base64_string}",
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        return headers

    def _is_access_token_expired(self) -> bool:
        if not self.auth:
            return True  # don't have an access token, so say it is expired so another is generated

        expiration_origin_time = parser.parse(self.auth['expiration_origin_time'])

        # Server defines when token expires (in seconds); subtract 30 seconds to request new token a bit before actual expiration
        access_token_expiration = expiration_origin_time + timedelta(seconds=int(self.auth['expires_in']) - 30)
        return datetime.now() > access_token_expiration

    def _update_access_token(self):
        # Request a new access token
        print('Refreshing access token...')
        token_url = f'{api_root}/oauth/token'
        headers = self._get_token_request_headers()
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.auth['refresh_token'],
        }
        response = requests.post(token_url, headers=headers, data=data, timeout=60)
        if not response.ok:
            message = 'Fatal error:  Try running gen_refresh_token.py to update Refresh token.  Full error:'
            message += response.text
            raise SchwabAccessTokenException(message)

        # Merge the new auth with the old auth.json, preserving any of our app-specific fields, e.g. expiration_origin_time
        new_auth = json.loads(response.text)
        self.auth.update(new_auth)

        # Source: https://stackoverflow.com/a/13356706
        self.auth['expiration_origin_time'] = str(datetime.now())
        with open('auth.json', 'w') as f:
            json.dump(self.auth, f, indent=4)

        return self.auth['access_token']

    def _get_schwab_authorization(self) -> str:
        '''
        Returns e.g. "Bearer <Access token>"
        '''

        if self._is_access_token_expired():
            self._update_access_token()

        # Use refresh token to request new access token
        token_type = self.auth['token_type']
        access_token = self.auth['access_token']
        return f"{token_type} {access_token}"

    def headers(self) -> dict:
        # Refresh access token if necessary
        authorization: str = self._get_schwab_authorization()
        return {
            'Authorization': authorization
        }

    def refresh_token_expected_expiration_time(self) -> datetime:
        return datetime.strptime(self.auth['refresh_token_expected_expiration_time'],"%Y-%m-%d %H:%M:%S.%f")


if __name__ == "__main__":
    # Load environment variables from file .\.env containing sensitive info that shouldn't be committed to git
    # See .\.env.sample for sample values (which don't work as-is, substitute them with the values specified in
    # your Schwab account settings, where you set up your application
    dotenv.load_dotenv()

    # Data required to generate a Schwab API refresh token, which is then used to generate an Access token used in Schwab web requests
    app_key = os.environ["SCHWAB_APP_KEY"]          # e.g. "lL5apjgztC82RsFDaoJLeH7FqnHz5rnL"
    app_secret = os.environ["SCHWAB_APP_SECRET"]    # e.g. "3gWeqCR7qDPeG1FD"

    # Test good state of Schwab Auth
    schwab_auth = SchwabAuth(app_key, app_secret)
    refresh_token_expiration: datetime = schwab_auth.refresh_token_expected_expiration_time()
    print(f"Refresh token expected expiration:  {refresh_token_expiration}; in {(refresh_token_expiration - datetime.now()).days} days.")
    headers = schwab_auth.headers()
    print(f'Headers: {headers}')
    print()
    if headers["Authorization"].find('Bearer ') < 0:
        print("Fatal error:  The headers don't contain 'Bearer'.  Something went wrong generating the Access token.  Please try again.  Exiting.")
    else:
        print("Success!  Your Refresh token is working. You can now use SchwabAuth to generate Access tokens for the Schwab API.")
