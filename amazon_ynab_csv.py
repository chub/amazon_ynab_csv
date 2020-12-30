import csv
import hashlib
import re
import sys
from dataclasses import dataclass
from typing import Dict, List

ITEM_COLUMNS = ['Order Date', 'Order ID', 'Title', 'Category', 'ASIN/ISBN', 'UNSPSC Code',
                'Website', 'Release Date', 'Condition', 'Seller', 'Seller Credentials',
                'List Price Per Unit', 'Purchase Price Per Unit', 'Quantity',
                'Payment Instrument Type', 'Purchase Order Number', 'PO Line Number',
                'Ordering Customer Email', 'Shipment Date', 'Shipping Address Name',
                'Shipping Address Street 1', 'Shipping Address Street 2', 'Shipping Address City',
                'Shipping Address State', 'Shipping Address Zip', 'Order Status',
                'Carrier Name & Tracking Number', 'Item Subtotal', 'Item Subtotal Tax',
                'Item Total', 'Tax Exemption Applied', 'Tax Exemption Type', 'Exemption Opt-Out',
                'Buyer Name', 'Currency', 'Group Name']
ORDER_COLUMNS = ['Order Date', 'Order ID', 'Payment Instrument Type', 'Website',
                 'Purchase Order Number', 'Ordering Customer Email', 'Shipment Date',
                 'Shipping Address Name', 'Shipping Address Street 1', 'Shipping Address Street 2',
                 'Shipping Address City', 'Shipping Address State', 'Shipping Address Zip',
                 'Order Status', 'Carrier Name & Tracking Number', 'Subtotal', 'Shipping Charge',
                 'Tax Before Promotions', 'Total Promotions', 'Tax Charged', 'Total Charged',
                 'Buyer Name', 'Group Name']
REFUND_COLUMNS = ['Order ID', 'Order Date', 'Title', 'Category', 'ASIN/ISBN', 'Website',
                  'Purchase Order Number', 'Refund Date', 'Refund Condition', 'Refund Amount',
                  'Refund Tax Amount', 'Tax Exemption Applied', 'Refund Reason', 'Quantity',
                  'Seller', 'Seller Credentials', 'Buyer Name', 'Group Name']


def extract_from_csv(filename):
    data = []
    column_names = None
    with open(filename) as csv_file:
        reader = csv.reader(csv_file)
        for row in reader:
            if column_names is None:
                column_names = row
            else:
                data.append({column_names[i]: row[i] for i in range(0, len(row))})

    return data


@dataclass
class ItemDetail:
    name: str
    total: float
    seller: str


class YnabCsv(object):
    def __init__(self, items, orders, refunds=None):
        self.items = items
        self.orders = orders
        self.refunds = refunds
        self.order_items: Dict[str, List[ItemDetail]] = {}
        self.gift_card_funding_order_ids: List[str] = []
        self.preprocess()

    @staticmethod
    def is_self_purchase(shipping_address_name):
        hash = hashlib.md5(shipping_address_name[-4:].encode('utf-8')).hexdigest()
        return hash == "0223e6d5710dbd37c5b6df77355bda00"

    @staticmethod
    def get_simple_name(title):
        """
        Trim product name until first non-alphanumerical character.
        """
        for group in re.split("[^a-zA-Z0-9'& ]", title):
            rv = group.strip()
            if len(rv) > 0:
                return rv

        return ""

    def record_item(self, order_id, name, total, seller):
        if order_id not in self.order_items:
            self.order_items[order_id] = []
        self.order_items[order_id].append(ItemDetail(name, total, seller))

    def preprocess(self):
        for item in self.items:
            order_id = item['Order ID']
            if item['Category'] == "ABIS_GIFT_CARD":
                self.gift_card_funding_order_ids.append(order_id)
            else:
                name = self.get_simple_name(item['Title'])
                self.record_item(order_id, name, item['Item Total'], item['Seller'])

    def is_whole_foods_order(self, order_id):
        if order_id not in self.order_items:
            return False

        total_items = len(self.order_items[order_id])
        return len(list(filter(lambda x: x.seller == 'Whole Foods Market',
                               self.order_items[order_id]))) == total_items

    def print_csv(self):
        print(",".join(["Date", "Payee", "Memo", "Amount", "Invoice URL"]))
        self.print_orders()
        self.print_refunds()

    def print_orders(self):
        for order in self.orders:
            payee = "Amazon.com"
            total_charged = order['Total Charged']
            if total_charged == "":
                continue

            order_id = order['Order ID']
            if order_id in self.gift_card_funding_order_ids:
                memo = f"Order #{order_id}: Prime Reload"
                amount = total_charged
            else:
                ship_to = order['Shipping Address Name']
                if order_id in self.order_items:
                    if self.is_whole_foods_order(order_id):
                        items = None
                        payee = "Whole Foods Market"
                    else:
                        # Find the individual item?
                        items = list(filter(lambda item_detail: item_detail.total == total_charged,
                                            self.order_items[order_id]))
                        if len(items) == 1:
                            items = items[0].name
                        else:
                            # List all items
                            items = "; ".join([f"{item.name} ({item.total})" for item in
                                               self.order_items[order_id]])
                else:
                    items = "Unknown Items"

                if not self.is_self_purchase(ship_to):
                    memo = f"{ship_to} - Order #{order_id}"
                else:
                    memo = f"Order #{order_id}"
                if items is not None:
                    memo += f": {items}"
                amount = f"-{total_charged}"

            print(",".join([
                order['Order Date'],
                payee,
                memo,
                amount,
                f"https://www.amazon.com/gp/css/summary/print.html?orderID={order_id}"
            ]))

    @staticmethod
    def get_decimal_amount(amt):
        if amt.startswith("$"):
            return float(amt[1:])
        else:
            return float(amt)

    def print_refunds(self):
        if self.refunds is None:
            return

        for refund in self.refunds:
            order_id = refund['Order ID']
            refund_date = refund['Refund Date']

            refund_amount = self.get_decimal_amount(refund['Refund Amount'])
            refund_tax_amount = self.get_decimal_amount(refund['Refund Tax Amount'])

            total_refunded = refund_amount + refund_tax_amount
            name = self.get_simple_name(refund['Title'])
            print(",".join([
                refund_date,
                "Amazon.com",
                f"Order #{order_id}: Returned {name}",
                f"${total_refunded:.2f}",
                f"https://www.amazon.com/gp/css/summary/print.html?orderID={order_id}"
            ]))


if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise Exception("Need two arguments: items.csv and orders.csv")
    items = extract_from_csv(sys.argv[1])
    orders = extract_from_csv(sys.argv[2])
    refunds = None
    if len(sys.argv) > 3:
        refunds = extract_from_csv(sys.argv[3])
    ynab_csv = YnabCsv(items, orders, refunds=refunds)
    ynab_csv.print_csv()
