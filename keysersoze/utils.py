import re
import logging
from operator import itemgetter
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd
from .models import (
    Deal,
    Asset,
    AssetMarketHistory,
    AccountHistory,
    AccountAssetsHistory,
)


LOGGER = logging.getLogger(__name__)


def get_asset_category(asset_code):
    """根据证券代码判断场内资产类型"""
    if not re.match(r'^[0-9]{6}$', asset_code):
        return None

    # FIXME:
    # 1. 沪市指数以 000 开头，与深市 A 股有冲突
    # 2. 沪市债券有 15/16 开头的，与深市基金有冲突

    # 沪市 A 股: 60
    # 沪市 B 股: 900
    # 沪市科创板: 688
    # 深市 A 股: 000/001
    # 深市中小板: 002/003
    # 深市 B 股: 20
    # 深市创业板: 30
    if re.match(r'^(?:60|900|68|00[0123]|[23]0)', asset_code):
        return 'stock'

    # 沪市国债: 009/010/019/020
    # 沪市可转债: 100, 110, 112, 113
    # 深市国债: 100, 101
    # 深市可转债: 12
    if re.match(r'^(?:009|01[09]|020|10[01]|11[0123]|12)', asset_code):
        return 'bond'

    # 沪市基金: 500, 510
    # 深市基金: 15, 16, 18
    if re.match(r'^(?:1[568]|5[012])', asset_code):
        return 'fund'

    return 'unknown'


def get_code_suffix(asset_code):
    """根据证券代码判断场内资产的后缀"""
    if not get_asset_category(asset_code):
        return None

    if re.match(r'^(?:60|900|68|5[012])', asset_code):
        return 'SH'

    if re.match(r'^(?:00[0123]|[23]0|1[568])', asset_code):
        return 'SZ'

    # TODO: 债券的判断
    return 'unknown'


def update_account_assets_history(account, verbse=False):
    deals = defaultdict(list)
    for deal in Deal.select().where(Deal.account == account).order_by(Deal.time):
        date = deal.time.date()
        deals[date].append(deal)

    created_cnt, update_cnt = 0, 0
    code2amount, code2cost, code2asset = defaultdict(float), defaultdict(float), {}
    for date, date_deals in sorted(deals.items(), key=itemgetter(0)):
        for item in date_deals:
            code, action = item.asset.zs_code, item.action
            if code not in code2asset:
                code2asset[code] = item.asset

            if action in ('buy', 'reinvest', 'transfer_in'):
                code2amount[code] += item.amount
                if action == 'buy':
                    code2amount['CASH'] -= item.money
                    code2cost[code] += item.money
            elif action in ('sell', 'transfer_out'):
                code2amount[code] -= item.amount
                if action == 'sell':
                    code2amount['CASH'] += item.money
                    code2cost[code] -= item.money
            elif action in ('bonus', 'fix_cash'):
                code2amount['CASH'] += item.amount
            elif action == 'spin_off':
                code2amount[code] = item.amount

        for code, amount in code2amount.items():
            record = AccountAssetsHistory.get_or_none(
                account=account, date=date, asset=code2asset[code]
            )
            created_or_updated = False
            if not record:
                AccountAssetsHistory.create(
                    account=account,
                    date=date,
                    asset=code2asset[code],
                    amount=code2amount[code],
                    cost=code2cost[code] if code != 'CASH' else None
                )
                created_cnt += 1
                created_or_updated = True
            elif record.amount != code2amount[code]:
                record.amount = code2amount[code]
                record.cost = code2cost[code]
                record.save()
                update_cnt += 1
                created_or_updated = True

            if verbse and created_or_updated and (created_cnt + update_cnt) % 100 == 0:
                LOGGER.info(
                    'created %d new assets history and updated %d records for account %s',
                    created_cnt, update_cnt, account
                )

    LOGGER.info(
        'created %d new assets history and updated %d records for account %s totally',
        created_cnt, update_cnt, account
    )


def compute_account_history(account):
    history = defaultdict(list)
    search = AccountAssetsHistory.select().where(AccountAssetsHistory.account == account)
    search = search.order_by(AccountAssetsHistory.date)
    for record in search:
        history[record.date].append(record)

    first_date = min(history.keys())
    end_date = datetime.now().date()
    if datetime.now().hour < 20:
        end_date -= timedelta(days=1)

    code2amount, results = {}, []
    for offset in range((end_date - first_date).days + 1):
        date = first_date + timedelta(days=offset)
        if date in history:
            code2amount = {}
            for record in history[date]:
                code2amount[record.asset.zs_code] = record.amount

        total_money = 0.0
        for code, amount in code2amount.items():
            if abs(amount) <= 0.00001:
                continue

            if code == 'CASH':
                total_money += amount
                continue

            asset = Asset.get(zs_code=code)
            price = 1.0
            price_record = asset.history.\
                where(AssetMarketHistory.date <= date).\
                order_by(AssetMarketHistory.date.desc()).\
                first()
            if not price_record and asset.category != 'other':
                buying_records = asset.get_buying_records(account, date)
                if buying_records:
                    price = buying_records[-1].price
                else:
                    LOGGER.warning('no price found: %s', code)
            elif price_record:
                price = price_record.nav if code.endswith('OF') else price_record.close_price

            total_money += amount * price

        cash = code2amount.get('CASH', 0.0)
        total_invested = Deal.get_total_invested(account, date=date)
        # 忽略非交易日
        if AssetMarketHistory.select().where(AssetMarketHistory.date == date).exists():
            results.append([
                date,
                round(total_invested, 2),
                round(total_money, 2),
                round(total_money / total_invested, 4),
                round(cash, 2),
                round(1 - cash / total_money if abs(total_money) > 0.0001 else 0.0, 4),
            ])

    return results


def get_accounts_history(accounts, start_date=None, end_date=None):
    data = []
    summary = {}
    for account in accounts:
        search = AccountHistory.select().where(AccountHistory.account == account)
        if start_date:
            search = search.where(AssetMarketHistory.date >= start_date)
        if end_date:
            search = search.where(AssetMarketHistory.date <= start_date)

        for item in search.order_by(AccountHistory.date):
            record = {
                'account': item.account,
                'date': item.date,
                'amount': item.amount,
                'money': item.money,
                'nav': item.nav,
                'cash': item.cash,
                'position': item.position,
            }
            data.append(record)

            date = record['date']
            if record['date'] not in summary:
                summary[date] = {
                    'date': date,
                    'amount': item.amount,
                    'money': item.money,
                    'cash': item.cash,
                }
            else:
                summary[date]['amount'] += item.amount
                summary[date]['money'] += item.money
                summary[date]['cash'] += item.cash

    for date, info in summary.items():
        info['account'] = '总计'
        info['nav'] = round(info['money'] / info['amount'], 4)
        info['position'] = round(1 - info['cash'] / info['money'], 4)
        info['amount'] = round(info['amount'], 2)
        info['money'] = round(info['money'], 2)
        data.append(info)

    data.sort(key=itemgetter('account', 'date'))
    return pd.DataFrame(data)


def get_accounts_summary(accounts=None, date=None):
    date = date or datetime.now().date()
    if date >= datetime.now().date():
        date -= timedelta(days=1)

    if not accounts:
        accounts = [deal.account for deal in Deal.select(Deal.account).distinct()]

    accounts_summary = AccountHistory.get_summary(accounts, date)
    assets = AccountAssetsHistory.get_assets(accounts, date)
    assets.sort(key=itemgetter('money'), reverse=True)
    return accounts_summary, assets
