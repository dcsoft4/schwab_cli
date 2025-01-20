from datetime import datetime
from tzlocal import get_localzone
from dataclasses import dataclass
import locale


# Functionality surrounding Schwab transactions
# Status:  Beta


@dataclass
class Transaction:
    trade_date_local: datetime
    trade_date_formatted: str = ""
    position_id: str = ""
    symbol: str = None
    shares: int = 0
    price: float = 0.0
    opening_or_closing: str = None

    def __init__(self, transaction, transfer_item: object):
        trade_date_utc: datetime = datetime.strptime(transaction["tradeDate"], "%Y-%m-%dT%H:%M:%S%z")
        self.trade_date_local = trade_date_utc.astimezone(get_localzone())
        self.trade_date_formatted = f"{self.trade_date_local.strftime("%a %H:%M:%S")} ({self.trade_date_local.month}/{self.trade_date_local.day})"
        self.position_id = transaction.get("positionId")
        assert not self.symbol or self.symbol == transfer_item["instrument"]["symbol"]
        self.symbol = transfer_item["instrument"]["symbol"]
        self.shares += transfer_item["amount"]
        self.price += transfer_item["price"]
        assert transfer_item["positionEffect"] == "CLOSING" or transfer_item["positionEffect"] == "OPENING"
        assert self.opening_or_closing is None or self.opening_or_closing == transfer_item["positionEffect"]
        self.opening_or_closing = transfer_item["positionEffect"]

    def __str__(self):
        return f"{self.trade_date_formatted} {self.symbol}: {self.opening_or_closing}: {self.shares} shares @ {self.price} [{self.position_id}]"

    def is_opening(self) -> bool:
        return self.opening_or_closing == "OPENING"

TransactionGroup = list[Transaction]
TransactionGroups = list[TransactionGroup]


def find_transaction_groups(raw_transactions: list|None) -> TransactionGroups|None:
    """ Dump transactions """

    if not raw_transactions:
        return None

    # Sort all transactions
    all_transactions: list[Transaction] = []
    for raw_transaction in raw_transactions:
        for transfer_item in raw_transaction["transferItems"]:
            all_transactions.append(Transaction(raw_transaction, transfer_item))
    all_transactions = sorted(all_transactions, key=lambda trans: (trans.trade_date_local, trans.opening_or_closing))

    group: TransactionGroup = []
    groups: TransactionGroups = []
    in_group: bool = False
    finding_opening_transaction: bool = True
    num_unmatched_shares: int = 0
    for transaction in all_transactions:
        # print(str(transaction))
        # Skip initial OPENING transactions as they are still active, no profit/loss can be calculated for them
        if not in_group and transaction.is_opening():
            # Found initial group OPENING transaction
            in_group = True
            group = []
        if in_group:
            group.append(transaction)
            num_unmatched_shares = num_unmatched_shares - transaction.shares if finding_opening_transaction else num_unmatched_shares + transaction.shares
            # print(f"  Num unmatched shares:  {num_unmatched_shares}")
            if num_unmatched_shares == 0:
                # Sort group by transaction.trade_date_formatted, then by transaction.opening_or_closing
                group = sorted(group, key=lambda trans: (trans.trade_date_local, trans.opening_or_closing))
                groups.append(group)
                # print(f"  Group {len(groups)} completed")
                in_group = False
        else:
            print(f"  Active (ungrouped) transaction:  {str(transaction)}")

    return groups


def dump_transaction_groups(groups: TransactionGroups|None) -> float:
    """ Dump transaction groups and return total profit of all groups combined """

    total_profit: float = 0.0
    group_number: int = 1

    if not groups:
        return total_profit

    for group in groups:
        print(f"  Group {group_number}")
        group_profit: float = 0.0
        for transaction in group:
            print(f"    {str(transaction)}")
            group_profit -= transaction.shares * transaction.price
        total_profit += group_profit
        group_number += 1
        print(f"    Group profit:  {locale.currency(group_profit, grouping=True)}")
    return total_profit
