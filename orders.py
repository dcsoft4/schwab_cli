from datetime import datetime
from tzlocal import get_localzone
from dataclasses import dataclass

# Functionality surrounding Schwab orders
# Status:  Beta


@dataclass
class Order:
    trade_date_local: datetime

    def __init__(self, order = None):
        if order:
            trade_date_utc: datetime = datetime.strptime(order["tradeDate"], "%Y-%m-%dT%H:%M:%S%z")
            self.trade_date_local = trade_date_utc.astimezone(get_localzone())

    def format_trade_date(self) -> str:
        return self.trade_date_local.strftime("%a %H:%M:%S")


@dataclass
class WorkingOrder:
    symbol: str
    instruction: str
    shares: float
    price: float
    orderType: str
    order_id: str

    def __init__(self, symbol: str, instruction: str, shares: float, price: float, orderType: str,  order_id: str):
        self.symbol = symbol
        self.shares = shares
        self.instruction = instruction
        self.price = price
        self.orderType = orderType
        self.order_id = order_id


def get_order_symbol(order) -> str:
    """ Returns symbol of order """
    symbol = None
    if order.get("orderStrategyType") == "OCO":
       order = order["childOrderStrategies"][0]
    legs = order["orderLegCollection"]
    activities = order.get("orderActivityCollection")
    if not activities:  # e.g. REJECTED order has no activities, use first leg
        symbol = legs[0]["instrument"]["symbol"]
    else:
        for activity in activities:
            if activity["activityType"] == "EXECUTION":
                for execution_leg in activity["executionLegs"]:
                    leg_id = execution_leg["legId"]
                    for leg in legs:
                        if leg["legId"] == leg_id:
                            symbol = leg["instrument"]["symbol"]
    return symbol


def get_filled_order_info(order) -> (int, float):
    """ Returns number of shares (positive if buy or negative if sell) and price of filled order """
    shares = None
    price = None
    if order.get("orderStrategyType") == "OCO":
       order = order["childOrderStrategies"][0]
    legs = order["orderLegCollection"]
    activities = order.get("orderActivityCollection")
    for activity in activities:
        for execution_leg in activity["executionLegs"]:
            leg_id = execution_leg["legId"]
            for leg in legs:
                if leg["legId"] == leg_id:
                    pass  # abcd

    if not shares or not price:
        assert False
    return (shares, price)


def find_working_orders(orders: list, target_symbol: str|None = None) -> list[WorkingOrder]:
    """ Return orders with WORKING status from `orders` """
    working_orders: list[WorkingOrder] = []
    for order in orders:
        status: str = order["status"]
        if status == "WORKING" or status == "PENDING_ACTIVATION":  # TODO:  Handle all possible order states!!!!
            symbol: str = get_order_symbol(order)
            if not target_symbol or symbol == target_symbol:
                order_id: str = order["orderId"]
                if order.get("orderStrategyType") == "OCO":        # TODO: process both parts of OCO order
                    order = order["childOrderStrategies"][0]
                legs = order["orderLegCollection"]
                for leg in legs:
                    instruction: str = leg["instruction"]   # e.g. "SELL"
                    shares: float = leg["quantity"]
                    price: float = order["price"]
                    orderType: str = order["orderType"]
                    working_orders.append(WorkingOrder(symbol, instruction, shares, price, orderType, order_id))
        elif status == "FILLED":
            pass
            '''
            # Find shares, price, direction
            date_utc = datetime.strptime(order["closeTime"], "%Y-%m-%dT%H:%M:%S%z")
            date_local = date_utc.astimezone(local_tz)
            date_formatted = date_local.strftime("%a %H:%M:%S")
            # print(f"{symbol}: {date_formatted}:  {status}:  {status_description if status_description else ''} [{order_id}]")
            '''
    return working_orders


def find_oco_orders(orders: list):
    """ Return orders with WORKING status from `orders` """
    assert False   # TODO:  OCO orders need to access childOrderStrategies for the order details of each part of the OCO
    oco_orders: list[WorkingOrder] = []
    for order in orders:
        strategy: str = order["orderStrategyType"]
        if strategy == "OCO":
            status: str = order["status"]
            print(f"{status}")
            symbol: str = get_order_symbol(order)
            order_id: str = order["orderId"]
            legs = order["orderLegCollection"]
            for leg in legs:
                instruction: str = leg["instruction"]   # e.g. "SELL"
                shares: float = leg["quantity"]
