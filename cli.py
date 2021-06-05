import os
import re
import csv
import json
from datetime import datetime, timedelta
import logging
from operator import itemgetter
from logging.config import dictConfig
from collections import defaultdict

import click
import tushare

from keysersoze.data import (
    QiemanExporter,
    EastMoneyFundExporter,
)
from keysersoze.models import (
    DATABASE,
    Deal,
    Asset,
    AssetMarketHistory,
    AccountHistory,
    AccountAssetsHistory,
    QiemanAsset,
)
from keysersoze.utils import (
    get_code_suffix,
    update_account_assets_history,
    compute_account_history,
)


LOGGER = logging.getLogger(__name__)
dictConfig({
    'version': 1,
    'formatters': {
        'simple': {
            'format': '%(asctime)s - %(filename)s:%(lineno)s: %(message)s',
        }
    },
    'handlers': {
        'default': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            "stream": "ext://sys.stdout",
        },
    },
    'loggers': {
        '__main__': {
            'handlers': ['default'],
            'level': 'DEBUG',
            'propagate': True
        },
        'keysersoze': {
            'handlers': ['default'],
            'level': 'DEBUG',
            'propagate': True
        }
    }
})


@click.group(context_settings=dict(help_option_names=['-h', '--help']))
def main():
    pass


@main.command("export-qieman")
@click.option("-c", "--config-file", required=True)
@click.option("--asset-id", required=True)
@click.option("-o", "--outfile", required=True)
def export_qieman_orders(config_file, asset_id, outfile):
    """导出且慢订单记录"""
    with open(config_file) as f:
        config = json.load(f)
        exporter = QiemanExporter(**config)
        orders = exporter.list_orders(asset_id)

    with open(outfile, 'w') as fout:
        for order in orders:
            line = json.dumps(order, ensure_ascii=False, sort_keys=True)
            print(line, file=fout)


@main.command("parse-qieman")
@click.option("-i", "--infile", required=True)
@click.option("-o", "--outfile", required=True)
@click.option("--add-transfer", is_flag=True, help="是否在买入时自动产生一笔等额资金转入")
def parse_qieman_orders(infile, outfile, add_transfer):
    """解析且慢订单记录为 csv 格式"""
    results = []
    with open(infile) as fin:
        pattern = re.compile(r'再投资份额(\d+\.\d+)份')
        unknown_buyings, transfer_in = [], defaultdict(float)
        for line in fin:
            item = json.loads(line)
            account = item['umaName']
            sub_account = item['capitalAccountName']
            if item['capitalAccountName'] == '货币三佳':
                pass
            elif item['hasDetail']:
                if item['orderStatus'] != 'SUCCESS':
                    continue

                for order in item['compositionOrders']:
                    value = order['nav']
                    fee = order['fee']
                    order_time = datetime.fromtimestamp(order['acceptTime'] / 1000)
                    count = order['uiShare']
                    money = order['uiAmount']
                    action = 'unknown'
                    if order['payStatus'] == '2':
                        action = 'buy'
                    elif order['payStatus'] == '0':
                        action = 'sell'

                    fund_code = order['fund']['fundCode']
                    fund_name = order['fund']['fundName']
                    if fund_name.find('广发钱袋子') >= 0:  # FIXME: 应当用基金类型来判断
                        continue

                    if 'destFund' in order:
                        money -= fee
                        unknown_buyings.append([
                            account, sub_account, order_time,
                            order['destFund']['fundCode'], order['destFund']['fundName'],
                            money
                        ])
                    elif add_transfer and action == 'buy':
                        transfer_in[(account, str(order_time.date()))] += money

                    results.append([
                        account, sub_account, order_time, fund_code, fund_name,
                        action, count, value, money, fee
                    ])
            elif item['uiOrderDesc'].find('再投资') >= 0:
                fee = 0
                order_time = datetime.fromtimestamp(item['acceptTime'] / 1000)
                count = float(pattern.findall(item['uiOrderDesc'])[0])
                money = item['uiAmount']
                value = round(float(money) / float(count), 4)
                action = 'reinvest'
                fund_code = item['fund']['fundCode']
                fund_name = item['fund']['fundName']
                # 且慢交易记录里红利再投资日期是再投资到账日期，不是实际发生的日期，
                # 这里尝试根据净值往前查找得到真正的日期
                fund = Asset.get_or_none(code=f'{fund_code}.OF')
                if fund:
                    search = fund.history.where(AssetMarketHistory.date < order_time.date())
                    search = search.where(
                        AssetMarketHistory.date >= order_time.date() - timedelta(days=10)
                    )
                    search = search.order_by(AssetMarketHistory.date.desc())
                    candidates = []
                    for record in search[:3]:
                        candidates.append((record, abs(record.nav - value)))

                    record, nav_diff = min(candidates, key=itemgetter(1))
                    LOGGER.info(
                        "correct reinvestment time of `%s` from `%s` to `%s`(nav diff: %f)",
                        fund_code, order_time, record.date, nav_diff
                    )
                    value = record.nav
                    order_time = datetime.strptime(f'{record.date} 08:00:00', '%Y-%m-%d %H:%M:%S')
                else:
                    LOGGER.warning(
                        "can not guess real order time of reinvestment(code: %s;time: %s; nav: %s)",
                        fund_code, order_time, value
                    )

                results.append([
                    account, sub_account, order_time, fund_code, fund_name,
                    action, count, value, money, fee
                ])
            elif item['uiOrderCodeName'].find('现金分红') >= 0:
                order_time = datetime.fromtimestamp(item['acceptTime'] / 1000)
                results.append([
                    account, sub_account, order_time,
                    item['fund']['fundCode'], item['fund']['fundName'],
                    'bonus', item['uiAmount'], 1.0, item['uiAmount'], 0.0
                ])

        for (account, date), money in transfer_in.items():
            order_time = datetime.strptime(f'{date} 08:00:00', '%Y-%m-%d %H:%M:%S')
            results.append([
                account, '', order_time, 'CASH', '现金',
                'transfer_in', money, 1.0, money, 0.0
            ])

        for account, sub_account, order_time, code, name, money in unknown_buyings:
            fund = Asset.get_or_none(zs_code=f'{code}.OF')
            if not fund:
                LOGGER.warning(
                    "fund `%s` is not found in database, add it with `update-fund`",
                    code
                )
                continue

            close_time = datetime.strptime(f'{order_time.date()} 15:00:00', '%Y-%m-%d %H:%M:%S')
            if order_time > close_time:
                history_date = order_time.replace(days=1).date()
            else:
                history_date = order_time.date()

            history_records = list(fund.history.where(AssetMarketHistory.date == history_date))
            if not history_records:
                LOGGER.warning(
                    "history data of fund `%s` is not found in database, try `update-fund`",
                    code
                )
                continue

            value = history_records[0].nav
            count = round(money / value, 2)
            results.append([
                account, sub_account, order_time, code, name,
                'buy', count, value, money, 0.0
            ])

    results.sort(key=itemgetter(2, 0, 1, 3, 5))
    with open(outfile, 'w') as fout:
        for row in results:
            if row[3] != 'CASH':
                row[3] = row[3] + '.OF'

            line = '\t'.join([
                '\t'.join(map(str, row[:6])),
                f'{row[6]:0.2f}', f'{row[7]:0.4f}',
                '\t'.join([f'{r:.2f}' for r in row[8:]]),
            ])
            print(line, file=fout)


@main.command("parse-pingan")
@click.option("-i", "--infile", required=True)
@click.option("-o", "--outfile", required=True)
def parse_pingan(infile, outfile):
    """解析平安证券的交易记录"""
    action_mappings = {
        '证券买入': 'buy',
        '证券卖出': 'sell',
        '银证转入': 'transfer_in',
        '银证转出': 'transfer_out',
        '利息归本': 'reinvest',
    }
    results = []
    with open(infile) as fin:
        reader = csv.DictReader(fin)
        for row in reader:
            if row['操作'] not in action_mappings:
                LOGGER.warning("unsupported action: %s", row['操作'])
                continue

            order_time = datetime.strptime(f'{row["成交日期"]} {row["成交时间"]}', '%Y%m%d %H:%M:%S')
            action = action_mappings[row['操作']]
            code, name = row['证券代码'], row['证券名称']
            count, price = float(row['成交数量']), float(row['成交均价'])
            money = float(row['发生金额'].lstrip('-'))
            fee = float(row["手续费"]) + float(row["印花税"])
            if action.startswith('transfer') or action == 'reinvest':
                code, name, count, price = 'CASH', '现金', money, 1.0

            if code != 'CASH':
                suffix = get_code_suffix(code)
                code = f'{code}.{suffix}'

            results.append([
                '平安证券', '平安证券', order_time, code, name,
                action, count, price, money, fee
            ])

    results.sort(key=itemgetter(2, 3, 5))
    with open(outfile, 'w') as fout:
        for row in results:
            line = '\t'.join([
                '\t'.join(map(str, row[:6])),
                f'{row[6]:0.2f}', f'{row[7]:0.4f}',
                '\t'.join([f'{r:0.2f}' for r in row[8:]]),
            ])
            print(line, file=fout)


@main.command("parse-huabao")
@click.option("-i", "--infile", required=True)
@click.option("-o", "--outfile", required=True)
def parse_huabao(infile, outfile):
    """解析华宝证券的交易记录"""
    ignore_actions = set(['中签通知', '配号'])
    action_mappings = {
        '买入': 'buy',
        '卖出': 'sell',
        '中签扣款': 'buy',
    }
    data = []
    stagging_data = []
    with open(infile) as fin:
        reader = csv.DictReader(fin)
        for row in reader:
            if row['委托类别'] in ignore_actions:
                continue

            if row['委托类别'] not in action_mappings:
                # 将打新股/打新债的扣款、托管相关的交易记录另外记录待之后处理
                if row['委托类别'] in ('托管转入', '托管转出'):
                    stagging_data.append(row)
                    continue
                else:
                    LOGGER.warning("unsupported action: %s", row)

                continue

            order_time = datetime.strptime(f'{row["成交日期"]} {row["成交时间"]}', '%Y%m%d %H:%M:%S')
            action = action_mappings[row['委托类别']]
            money, fee = float(row['发生金额']), float(row['佣金']) + float(row['印花税'])
            if action == 'buy':
                money += fee
            elif action == 'sell':
                money -= fee

            # 有些品种用「手」作为单位，将其转换为「股」
            count, price = float(row['成交数量']), float(row['成交价格'])
            if abs(money / (float(count) * float(price)) - 10) < 0.5:
                count = float(count) * 10

            code, name = row['证券代码'], row['证券名称']
            if row['委托类别'] != '中签扣款':
                suffix = get_code_suffix(code)
                code = f'{code}.{suffix}'

            data.append((
                '华宝证券', '华宝证券', order_time, code, name,
                action, count, price, money, fee
            ))

    name2codes = defaultdict(dict)
    for row in stagging_data:
        if not row['证券名称'].strip():
            continue

        if row['委托类别'] == '托管转出' and row['成交编号'] == '清理过期数据':
            name2codes[row['证券名称']]['origin'] = row['证券代码']
        elif row['委托类别'] == '托管转入':
            suffix = get_code_suffix(row['证券代码'])
            name2codes[row['证券名称']]['new'] = row['证券代码'] + f'.{suffix}'

    code_mappings = {}
    for codes in name2codes.values():
        code_mappings[codes['origin']] = codes['new']

    data.sort(key=itemgetter(2, 3, 5))
    with open(outfile, 'w') as fout:
        for row in data:
            row = list(row)
            if row[5] == 'buy' and row[3] in code_mappings:
                LOGGER.info("convert code from `%s` to `%s`", row[4], code_mappings[row[3]])
                row[3] = code_mappings[row[3]]

            line = '\t'.join([
                '\t'.join(map(str, row[:6])),
                '\t'.join([f'{r:.4f}' for r in row[6:]]),
            ])
            print(line, file=fout)


@main.command("create-db")
def create_db():
    """创建资产相关的数据库"""
    DATABASE.connect()
    DATABASE.create_tables([
        Asset,
        Deal,
        AssetMarketHistory,
        AccountHistory,
        AccountAssetsHistory,
        QiemanAsset,
    ])
    DATABASE.close()


@main.command('add-asset')
@click.option('--zs-code', required=True)
@click.option('--code', required=True)
@click.option('--name', required=True)
@click.option('--category', required=True)
def add_asset(zs_code, code, name, category):
    """添加资产品种到数据库"""
    _, created = Asset.get_or_create(
        zs_code=zs_code,
        code=code,
        name=name,
        category=category,
    )
    if created:
        LOGGER.info('created asset in database successfully')
    else:
        LOGGER.warning('asset is already in database')


@main.command('init-assets')
def init_assets():
    """获取市场资产列表写入到数据库"""
    token = os.environ.get('TS_TOKEN')
    if not token:
        LOGGER.warning('environment `TS_TOKEN` is empty!')
        return -1

    client = tushare.pro_api(token)
    created_cnt, total = 0, 0
    for _, row in client.stock_basic(list_status='L', fields='ts_code,name').iterrows():
        _, created = Asset.get_or_create(
            zs_code=row['ts_code'],
            code=row['ts_code'][:6],
            name=row['name'],
            category='stock',
        )
        created_cnt += created
        total += 1

    LOGGER.info('got %d stocks and created %d new in database', total, created_cnt)

    created_cnt, total = 0, 0
    for _, row in client.cb_basic(fields='ts_code,bond_short_name').iterrows():
        _, created = Asset.get_or_create(
            zs_code=row['ts_code'],
            code=row['ts_code'][:6],
            name=row['bond_short_name'],
            category='bond',
        )
        created_cnt += created
        total += 1

    LOGGER.info('got %d bonds and created %d new in database', total, created_cnt)

    for market in 'EO':
        created_cnt, total = 0, 0
        funds = client.fund_basic(market=market, status='L')
        for _, row in funds.iterrows():
            zs_code = row['ts_code']
            if zs_code[0] not in '0123456789':
                LOGGER.warning('invalid fund code: %s', zs_code)
                total += 1
                continue

            _, created = Asset.get_or_create(
                zs_code=zs_code,
                code=zs_code[:6],
                name=row['name'],
                category='fund',
            )
            created_cnt += created
            total += 1
            if market == 'E':
                zs_code = zs_code[:6] + '.OF'
                _, created = Asset.get_or_create(
                    zs_code=zs_code,
                    code=zs_code[:6],
                    name=row['name'],
                    category='fund',
                )
                created_cnt += created
                total += 1

        LOGGER.info(
            'got %d funds(market:%s) and created %d new in database',
            total, market, created_cnt
        )


@main.command('update-prices')
@click.option('--category', type=click.Choice(['index', 'stock', 'fund', 'bond']))
@click.option('--codes')
@click.option('--start-date')
def update_prices(category, codes, start_date):
    '''更新交易记录涉及到的资产的历史价格'''
    token = os.environ.get('TS_TOKEN')
    if not token:
        LOGGER.warning('environment `TS_TOKEN` is empty!')
        return -1

    assets = []
    if codes:
        for code in codes.split(','):
            asset = Asset.get_or_none(zs_code=code)
            if asset is None:
                LOGGER.warning("code `%s` is not found in database", code)
                continue
            assets.append(asset)
    else:
        categories = set(['index', 'stock', 'bond', 'fund'])
        if category:
            categories = categories & set([category])

        assets = [
            deal.asset for deal in Deal.select(Deal.asset).distinct()
            if deal.asset.category in categories
        ]
        if 'index' in categories:
            assets.extend(list(Asset.select().where(Asset.category == 'index')))

    now = datetime.now()
    if start_date is None:
        start_date = (now - timedelta(days=10)).date()
    else:
        start_date = datetime.strptime(start_date, '%Y%m%d').date()

    if now.hour >= 15:
        end_date = now.date()
    else:
        end_date = (now - timedelta(days=1)).date()

    api = EastMoneyFundExporter()
    client = tushare.pro_api(token)
    methods = {
        'stock': client.daily,
        'bond': client.cb_daily,
        'fund': client.fund_daily,
        'index': client.index_daily
    }
    for asset in assets:
        created_cnt = 0
        if asset.category in ('stock', 'bond', 'index') or \
           (asset.category == 'fund' and not asset.zs_code.endswith('OF')):
            days = (end_date - start_date).days + 1
            method = methods[asset.category]
            for offset in range(0, days, 1000):
                cur_start_date = start_date + timedelta(days=offset)
                cur_end_date = min(cur_start_date + timedelta(days=1000), end_date)
                data = method(
                    ts_code=asset.zs_code,
                    start_date=cur_start_date.strftime('%Y%m%d'),
                    end_date=cur_end_date.strftime('%Y%m%d')
                )
                for _, row in data.iterrows():
                    _, created = AssetMarketHistory.get_or_create(
                        date=datetime.strptime(row['trade_date'], '%Y%m%d').date(),
                        open_price=row['open'],
                        close_price=row['close'],
                        pre_close=row['pre_close'],
                        change=row['change'],
                        pct_change=row['pct_chg'],
                        vol=row['vol'],
                        amount=row['amount'],
                        high_price=row['high'],
                        low_price=row['low'],
                        asset=asset
                    )
                    created_cnt += created
        elif asset.category == 'fund':
            fund_data = api.get_fund_data(asset.code)
            if fund_data is None:
                LOGGER.warning('no data for fund: %s', asset.zs_code)
                continue
            history = defaultdict(dict)
            for nav in fund_data['Data_netWorthTrend']:
                date = str(datetime.fromtimestamp(nav['x'] / 1000).date())
                history[date]['nav'] = nav['y']
                if nav.get('unitMoney'):
                    bonus_text = nav['unitMoney']
                    action, value = 'unknown', None
                    if bonus_text.startswith('分红'):
                        action = 'bonus'
                        value = float(re.findall(r'派现金(\d\.\d+)元', bonus_text)[0])
                    elif bonus_text.startswith('拆分'):
                        action = 'spin_off'
                        value = float(re.findall(r'折算(\d\.\d+)份', bonus_text)[0])
                    else:
                        LOGGER.wanring("unknown bonus text: %s", bonus_text)

                    if action != 'unknown':
                        history[date]['bonus_action'] = action
                        history[date]['bonus_value'] = value

            for auv in fund_data['Data_ACWorthTrend']:
                date = str(datetime.fromtimestamp(auv[0] / 1000).date())
                history[date]['auv'] = auv[1]

            for date, info in history.items():
                if 'nav' not in info:
                    LOGGER.warning("invalid history data: %s(%s)", info, date)

                _, created = AssetMarketHistory.get_or_create(
                    date=datetime.strptime(date, '%Y-%m-%d').date(),
                    nav=info['nav'],
                    auv=info.get('auv'),
                    bonus_action=info.get('bonus_action'),
                    bonus_value=info.get('bonus_value'),
                    asset=asset
                )
                created_cnt += created

        LOGGER.info('created %d history records for %s(%s)', created_cnt, asset.name, asset.zs_code)


@main.command()
@click.option("-i", "--infile", required=True)
def import_deals(infile):
    """从文件中批量导入交易"""
    with open(infile) as fin:
        reader = csv.reader(fin, delimiter='\t')
        cnt, total = 0, 0
        for row in reader:
            if len(row) != 10:
                LOGGER.warning('column number is not 10: %s', row)
                continue

            asset = Asset.get_or_none(Asset.zs_code == row[3])
            if asset is None:
                LOGGER.warning('no asset found for code: %s', row[3])
                continue

            if asset.zs_code == 'CASH' and row[6] != row[8]:
                LOGGER.error('cash record is not balanced: %s', row)
                return

            if row[5] == 'buy':
                try:
                    diff = abs(float(row[6]) * float(row[7]) + float(row[9]) - float(row[8]))
                    assert diff < 0.001
                except AssertionError:
                    LOGGER.warning("record is not balanced: %s", row)
                    print(row)

            elif row[5] == 'sell':
                try:
                    diff = abs(float(row[6]) * float(row[7]) - float(row[9]) - float(row[8]))
                    assert diff < 0.001
                except AssertionError:
                    LOGGER.warning("record is not balanced: %s", row)

            _, created = Deal.get_or_create(
                account=row[0],
                sub_account=row[1],
                time=datetime.strptime(row[2], '%Y-%m-%d %H:%M:%S'),
                asset=asset,
                action=row[5],
                amount=row[6],
                price=row[7],
                money=row[8],
                fee=row[9]
            )
            total += 1
            if created:
                cnt += 1

        if cnt != total:
            LOGGER.warning("%d records are already in database", total - cnt)

        LOGGER.info("created %d records in database", cnt)


@main.command()
def validate_deals():
    """检查交易记录是否有缺失（如分红/拆分）或错误"""
    deals = defaultdict(list)
    for record in Deal.select().order_by(Deal.time):
        deals[record.asset.zs_code].append(record)

    for code, records in deals.items():
        asset = records[0].asset
        bonus_history = list(
            asset.history.where(
                AssetMarketHistory.bonus_action.is_null(False)
            ).where(
                AssetMarketHistory.date >= records[0].time.date()
            )
        )
        if not bonus_history:
            continue

        for bonus_record in bonus_history:
            matched = False
            for deal in records:
                if deal.time.date() == bonus_record.date:
                    matched = True
                    break

            if not matched:
                LOGGER.warning(
                    "bonus is missing in deals - fund: %s(%s), "
                    "date: %s, action: %s, value: %s",
                    asset.name, asset.zs_code, bonus_record.date,
                    bonus_record.bonus_action, bonus_record.bonus_value
                )


@main.command()
@click.option('--accounts')
def update_accounts(accounts):
    """更新账户持仓和收益数据"""
    if not accounts:
        accounts = set([
            deal.account
            for deal in Deal.select(Deal.account).distinct()
        ])
    else:
        accounts = set(accounts.split(','))

    for account in accounts:
        update_account_assets_history(account)

    for account in accounts:
        created_cnt = 0
        for item in compute_account_history(account):
            _, created = AccountHistory.get_or_create(
                account=account,
                date=item[0],
                amount=item[1],
                money=item[2],
                nav=item[3],
                cash=item[4],
                position=item[5],
            )
            created_cnt += created

        LOGGER.info('created %d new history for account %s', created_cnt, account)


if __name__ == '__main__':
    main()
