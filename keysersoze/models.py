import os
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from operator import itemgetter

from peewee import (
    SqliteDatabase,
    Model,
    CharField,
    DateTimeField,
    FloatField,
    CompositeKey,
    ForeignKeyField,
    DateField,
)
from scipy import optimize


LOGGER = logging.getLogger(__name__)
DB_DIR = os.environ.get(
    'KEYSERSOZE_DB_DIR',
    os.path.join(os.environ.get('HOME'), '.keysersoze')
)
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)

DATABASE = SqliteDatabase(os.path.join(DB_DIR, 'db.sqlite3'))


def xnpv(cashflows, rate):
    chron_order = sorted(cashflows, key=itemgetter(0))
    t0 = chron_order[0][0]
    return sum([cf / (1 + rate) ** ((t - t0).days / 365.0) for (t, cf) in chron_order])


def xirr(cashflows, guess=0.1):
    return optimize.newton(lambda r: xnpv(cashflows, r), guess)


class BaseModel(Model):
    class Meta:
        database = DATABASE


class Asset(BaseModel):

    zs_code = CharField(primary_key=True)
    code = CharField(index=True)
    name = CharField(index=True)
    category = CharField(index=True)

    def get_price(self, date=None):
        if self.zs_code == 'CASH' or self.category == 'other':
            return 1.0, date

        price_record = self.history.\
            where(AssetMarketHistory.date <= date).\
            order_by(AssetMarketHistory.date.desc()).\
            first()
        if price_record:
            if self.zs_code.endswith('OF'):
                return price_record.nav, price_record.date
            else:
                return price_record.close_price, price_record.date

        return None, None

    def get_buying_records(self, account=None, date=None):
        search = self.deals.where(Deal.action == 'buy')
        if account:
            search = search.where(Deal.account == account)
        if date:
            time = datetime.combine(date, datetime.max.time())
            search = search.where(Deal.time < time)

        return list(search.order_by(Deal.time))

    def get_buying_price(self, account=None, date=None):
        buying_records = self.get_buying_records(account=account, date=date)
        if buying_records:
            return buying_records[-1].price, buying_records[-1].time.date()

        return None, None


class Deal(BaseModel):

    account = CharField(index=True)
    sub_account = CharField(index=True, null=True)
    asset = ForeignKeyField(Asset, backref='deals')
    time = DateTimeField()
    action = CharField(
        choices=[
            (1, 'transfer_in'),
            (2, 'transfer_out'),
            (3, 'buy'),
            (4, 'sell'),
            (5, 'reinvest'),
            (6, 'bonus'),
            (7, 'spin_off'),
            (8, 'fix_cash'),
        ],
        index=True
    )
    amount = FloatField()
    price = FloatField()
    money = FloatField()
    fee = FloatField()

    class Meta:
        primary_key = CompositeKey('account', 'time', 'asset', 'amount')

    @classmethod
    def get_deals(cls, accounts, date=None, actions=None):
        deals = []
        for account in accounts:
            search = cls.select().where(cls.account == account)
            if date:
                time = datetime.combine(date, datetime.max.time())
                search = search.where(cls.time < time)

            for record in search:
                if not actions or record.action in actions:
                    deals.append(record)

        return deals

    @classmethod
    def get_cash_flow(cls, accounts, date=None):
        cash_flow = defaultdict(float)
        actions = set(['transfer_in', 'transfer_out'])
        for record in cls.get_deals(accounts, date=date, actions=actions):
            if record.action == 'transfer_in':
                cash_flow[record.time.date()] -= record.money
            else:
                cash_flow[record.time.date()] += record.money

        return cash_flow

    @classmethod
    def get_total_invested(cls, account, date=None):
        cash_flow = cls.get_cash_flow([account], date=date)
        return 0 - sum(cash_flow.values())


class AssetMarketHistory(BaseModel):

    date = DateField(index=True)
    open_price = FloatField(null=True)
    close_price = FloatField(null=True)
    pre_close = FloatField(null=True)   # 前一个交易日的收盘价
    change = FloatField(null=True)      # 相比前一日的涨跌额
    pct_change = FloatField(null=True)  # 相比前一日的涨跌幅
    vol = FloatField(null=True)         # 成交量
    amount = FloatField(null=True)      # 成交额
    high_price = FloatField(null=True)
    low_price = FloatField(null=True)
    nav = FloatField(null=True)         # 基金单位净值: Net Asset Value
    auv = FloatField(null=True)         # 基金累计净值: Accumulated Unit Value
    bonus_action = CharField(index=True, null=True)
    bonus_value = FloatField(null=True)
    asset = ForeignKeyField(Asset, backref='history')

    class Meta:
        primary_key = CompositeKey('date', 'asset', 'open_price', 'close_price', 'nav')


class AccountHistory(BaseModel):

    account = CharField(index=True)  # 账户
    date = DateField(index=True)     # 日期
    amount = FloatField()            # 总投入
    money = FloatField()             # 总金额
    nav = FloatField()               # 净值
    cash = FloatField()              # 现金金额
    position = FloatField()          # 仓位(1 - cash / money)

    class Meta:
        primary_key = CompositeKey('account', 'date')

    @classmethod
    def all_acounts(cls):
        return set([record.account for record in cls.select(cls.account).distinct()])

    @classmethod
    def get_summary(cls, accounts=None, date=None):
        date = date or datetime.now().date()
        if date >= datetime.now().date():
            date -= timedelta(days=1)

        accounts = accounts or cls.all_acounts()
        records = []
        for account in accounts:
            search = cls.select().where(cls.account == account)
            search = search.where(cls.date <= date)
            search = search.order_by(cls.date.desc())
            record = search.first()
            if record is None:
                LOGGER.info('no history record for account %s at %s', account, date)
                continue

            cash_flow = Deal.get_cash_flow([account], date)
            cash_flow[date] += record.money
            annualized_return = xirr(sorted(cash_flow.items(), key=itemgetter(0)))
            records.append({
                'account': record.account,
                'date': record.date,
                'amount': round(record.amount, 2),
                'money': round(record.money, 2),
                'return': round(record.money - record.amount, 2),
                'return_rate': round(record.nav - 1, 4),
                'cash': round(record.cash, 2),
                'position': round(record.position, 4),
                'annualized_return': round(annualized_return, 4),
            })

        if records:
            total_invested = sum([item['amount'] for item in records])
            total_cash = sum([item['cash'] for item in records])
            total_money = sum([item['money'] for item in records])
            cash_flow = Deal.get_cash_flow(accounts, date)
            cash_flow[date] += total_money
            annualized_return = xirr(sorted(cash_flow.items(), key=itemgetter(0)))
            records.append({
                'account': '总计',
                'date': max(records, key=itemgetter('date'))['date'],
                'amount': round(total_invested, 2),
                'money': round(total_money, 2),
                'return': round(total_money - total_invested, 2),
                'return_rate': round(total_money / total_invested - 1, 4),
                'cash': round(total_cash, 2),
                'position': round(1 - total_cash / total_money, 4),
                'annualized_return': round(annualized_return, 4)
            })

        return records


class AccountAssetsHistory(BaseModel):

    account = CharField(index=True)
    date = DateField(index=True)
    asset = ForeignKeyField(Asset, backref='assets_history')
    amount = FloatField()            # 持有份额
    cost = FloatField(null=True)     # 投入

    class Meta:
        primary_key = CompositeKey('account', 'date', 'asset')

    @classmethod
    def get_account_assets(cls, account, date=None):
        search = cls.select().where(cls.account == account)
        if date:
            search = search.where(cls.date <= date)

        search = search.order_by(cls.date.desc())
        if not search.exists():
            return []

        date = search.first().date
        search = cls.select().where(cls.account == account).where(cls.date == date)
        return list(search)

    @classmethod
    def get_assets(cls, accounts, date=None):
        asset2amount, asset2cost = defaultdict(float), defaultdict(float)
        for account in accounts:
            for record in cls.get_account_assets(account, date=date):
                asset2amount[record.asset] += record.amount
                if record.asset.zs_code != 'CASH':
                    asset2cost[record.asset] += record.cost

        results = {}
        for asset, amount in asset2amount.items():
            amount = amount if abs(amount) > 0.001 else 0
            cost = asset2cost[asset] if abs(asset2cost[asset]) > 0.001 else 0
            results[asset] = {
                'code': asset.zs_code,
                'name': asset.name,
                'amount': amount,
                'money': None,
                'cost': cost,
                'avg_cost': None,
                'price': None,
                'price_date': None,
                'return': None,
                'return_rate': None
            }
            price, price_date = asset.get_price(date)

            if price is None:
                LOGGER.warning('no price found for asset %s at %s', asset, date)
                results[asset].update({
                    'money': asset2cost[asset],
                })
                continue

            results[asset].update({
                'price': price,
                'price_date': price_date
            })
            if asset.zs_code == 'CASH':
                results[asset].update({
                    'money': amount,
                    'cost': None,
                    'price_date': None,
                })
                continue

            results[asset]['money'] = round(amount * price, 2)
            results[asset]['return'] = results[asset]['money'] - cost
            if cost > 0:
                results[asset]['return_rate'] = round(results[asset]['return'] / cost, 4)
            if amount > 0:
                results[asset]['avg_cost'] = round(cost / amount, 4)

        return list(results.values())
