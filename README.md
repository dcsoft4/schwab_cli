# Schwab_CLI

## What it is

Here are several Python scripts to provide CLI access to your Schwab (formerly TD Ameritrade) brokerage account.  The necessary Schwab token management is broken out into re-usable modules you can use in other software.

## Command-line access to your Schwab account

[_schwab_cli.py_]

A command-line playground for Python access to Schwab brokerage accounts.  Includes commands to:

* Get stock quotes
* Place orders to buy/sell (either at market or limit prices)
* Display Account balance, positions, stock trends  
* Advanced functions to enter positions
  * Buy low or sell high -- like a trailing stop, except to enter (instead of exit) a position
  * Breakout of oscillate -- enter a position when price breaks out of, or oscillates within, a low/high range
* Advanced functions to show filled transactions (orders), matching buys to sells when possible
 

![Screenshot](schwab_cli_ss.png)

### Commands

#### Quote

quote [symbol1,symbol2,...]

> To get a quote on Apple, type <br>
> \> quote aapl <br>
> {'symbol': 'AAPL', 'last': 229.499, 'ask': 229.55, 'bid': 229.47}


#### Order

order [b | s | bs | ss | ts] [symbol] [num shares] <limit | offset | 'ask' | 'bid'>

> To buy 100 shares of Apple at the market price: <br>
> \> order b aapl 100 <br>
> <br>
> To buy 100 shares of Apple at $213.50/share: <br>
> \> order b aapl 100 213.50 <br>
> <br>
> To buy 100 shares of Apple at the bidding (highest buying offer) price: <br>
> \> order b aapl 100 bid <br>
> <br>
> To sell 100 shares of Apple at the asking (lowest selling offer) price: <br>
> \> order s aapl 100 ask <br>

`b` is "buy" <br>
`s` is "sell" <br>
`bs` is "buy stop" <br>
`ss` is "sell stop" <br>
`ts` is "trailing stop"

#### Position

pos [symbol1,symbol2,...]<br>
posloop [symbol1,symbol2,...] <-- repeats every 30 seconds

> To see current position on Reddit, type<br>
> \> pos rddt<br>
RDDT: 30 @ 176.566666666667 (201.09); gain/loss: 735.70

#### Trend

trend [symbol] <ref price>

> To get a quote for Nvidia every 30 seconds and compare it to a reference price in units of 0.01%<br>
> \> trend nvda 131.58<br>
11:04:07: Computing trend for NVDA; ref price: 131.588; updates every 30 seconds; press ^C to stop<br>
11:04:07: NVDA: 129.69 (-146.35); Summary: -146.35 <-- Price changed (129.69 - 131.588) * 10K<br> 
11:04:37: NVDA: 129.5402 (-11.56); Summary: -157.91<br>
11:05:07: NVDA: 129.4698 (-5.44); Summary: -163.35<br>


#### Advanced functions

TODO

#### Support Modules
[_commands.py_]<br>
[_orders.py_]<br>
[_transactions.py_]



## Token Access

[_schwab_auth.py_]

Re-usable module used by _schwab_cli.py_ to provide -- and to re-generate as needed -- the Access token required to call the Schwab API.

The current token state is saved in _auth.json_.


## Refresh Token Generation

[_gen_refresh_token.py_]

Standalone CLI utility that generates a Refresh token, which is then used to create Access Tokens.

![Screenshot](gen_refresh_token_ss.png)

The current token state is saved in _auth.json_.


## Schwab Account requirements

Your Schwab account must be made available for API access to these scripts (and any other software you develop).  See https://developer.schwab.com/user-guides/

Specifically, these scripts require the following data specific to your Schwab account.

[_.env.example_]
* SCHWAB_APP_KEY=lL5apjgztC82RsFDaoJLeH7FqnHz5rnL
* SCHWAB_APP_SECRET=3gWeqCR7qDPeG1FD
* SCHWAB_CALLBACK_URL=https://dcsoft.com/dev/schwab

**Create a file named "_.env_"** like the above example, but change the values to the ones specific to your Schwab account.
