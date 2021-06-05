import logging
from operator import itemgetter
from logging.config import dictConfig
from datetime import datetime, timedelta, date
from math import ceil

import dash
import dash_table
from dash_table.Format import Format, Scheme
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd
from chinese_calendar import get_holidays
import plotly.graph_objects as go
import numpy as np

from keysersoze.models import (
    Deal,
    Asset,
    AssetMarketHistory,
)
from keysersoze.utils import (
    get_accounts_history,
    get_accounts_summary,
)
from keysersoze.apps.app import APP
from keysersoze.apps.utils import make_card_component


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
pd.options.mode.chained_assignment = 'raise'

COLUMN_MAPPINGS = {
    'code': '代码',
    'name': '名称',
    'ratio': '占比',
    'return_rate': '收益率',
    'cost': '投入',
    'avg_cost': '成本',
    'price': '价格',
    'price_date': '价格日期',
    'amount': '份额',
    'money': '金额',
    'return': '收益',
    'action': '操作',
    'account': '账户',
    'date': '日期',
    'time': '时间',
    'fee': '费用',
    'position': '仓位',
    'day_return': '日收益',
}
FORMATS = {
    '价格日期': {'type': 'datetime', 'format': Format(nully='N/A')},
    '日期': {'type': 'datetime', 'format': Format(nully='N/A')},
    '时间': {'type': 'datetime', 'format': Format(nully='N/A')},
    '占比': {'type': 'numeric', 'format': Format(scheme='%', precision=2)},
    '收益率': {'type': 'numeric', 'format': Format(nully='N/A', scheme='%', precision=2)},
    '份额': {'type': 'numeric', 'format': Format(nully='N/A', precision=2, scheme=Scheme.fixed)},
    '金额': {'type': 'numeric', 'format': Format(nully='N/A', precision=2, scheme=Scheme.fixed)},
    '费用': {'type': 'numeric', 'format': Format(nully='N/A', precision=2, scheme=Scheme.fixed)},
    '投入': {'type': 'numeric', 'format': Format(nully='N/A', precision=2, scheme=Scheme.fixed)},
    '成本': {'type': 'numeric', 'format': Format(nully='N/A', precision=4, scheme=Scheme.fixed)},
    '价格': {'type': 'numeric', 'format': Format(nully='N/A', precision=4, scheme=Scheme.fixed)},
    '收益': {'type': 'numeric', 'format': Format(nully='N/A', precision=2, scheme=Scheme.fixed)},
}
ACCOUNT_PRIORITIES = {
    '长期投资': 0,
    '长赢定投': 1,
    'U定投': 2,
    '投资实证': 3,
    '稳健投资': 4,
    '证券账户': 6,
    '蛋卷基金': 7,
}


all_accounts = [deal.account for deal in Deal.select(Deal.account).distinct()]
all_accounts.sort(key=lambda name: ACCOUNT_PRIORITIES.get(name, 1000))
layout = html.Div(
    [
        dcc.Store(id='assets'),
        dcc.Store(id='stats'),
        dcc.Store(id='accounts_history'),
        dcc.Store(id='index_history'),
        dcc.Store(id='deals'),
        dcc.Store(id='start-date'),
        dcc.Store(id='end-date'),
        html.H3('投资账户概览'),
        dbc.Checklist(
            id='show-money',
            options=[{'label': '显示金额', 'value': 'show'}],
            value=[],
            switch=True,
        ),
        html.Hr(),
        dbc.InputGroup(
            [
                dbc.InputGroupAddon('选择账户', addon_type='prepend', className='mr-2'),
                dbc.Checklist(
                    id='checklist',
                    options=[{'label': a, 'value': a} for a in all_accounts],
                    value=[all_accounts[0]],
                    inline=True,
                    className='my-auto'
                ),
            ],
            className='my-2',
        ),
        html.Div(id='account-summary'),
        html.Br(),
        dbc.Tabs([
            dbc.Tab(
                label='资产走势',
                children=[
                    dcc.Graph(
                        id='asset-history-chart',
                        config={
                            'displayModeBar': False,
                        }
                    ),
                ]
            ),
            dbc.Tab(
                label='累计收益走势',
                children=[
                    dcc.Graph(
                        id="total-return-chart",
                        config={
                            'displayModeBar': False
                        }
                    ),
                ]
            ),
            dbc.Tab(
                label='累计收益率走势',
                children=[
                    dbc.InputGroup(
                        [
                            dbc.InputGroupAddon('比较基准', addon_type='prepend', className='mr-2'),
                            dbc.Checklist(
                                id='compare',
                                options=[
                                    {'label': '中证全指', 'value': '000985.CSI'},
                                    {'label': '上证指数', 'value': '000001.SH'},
                                    {'label': '深证成指', 'value': '399001.SZ'},
                                    {'label': '沪深300', 'value': '000300.SH'},
                                    {'label': '中证500', 'value': '000905.SH'},
                                ],
                                value=['000985.CSI'],
                                inline=True,
                                className='my-auto'
                            ),
                        ],
                        className='my-2',
                    ),
                    dcc.Graph(
                        id="return-curve-chart",
                        config={
                            'displayModeBar': False
                        }
                    ),
                ]
            ),
            dbc.Tab(
                label='日收益历史',
                children=[
                    dcc.Graph(
                        id="day-return-chart",
                        config={
                            'displayModeBar': False
                        },
                    ),
                ]
            ),
        ]),
        html.Center(
            [
                dbc.RadioItems(
                    id="date-range",
                    className='btn-group',
                    labelClassName='btn btn-light border',
                    labelCheckedClassName='active',
                    options=[
                        {"label": "近一月", "value": "1m"},
                        {"label": "近三月", "value": "3m"},
                        {"label": "近半年", "value": "6m"},
                        {"label": "近一年", "value": "12m"},
                        {"label": "今年以来", "value": "thisyear"},
                        {"label": "本月", "value": "thismonth"},
                        {"label": "本周", "value": "thisweek"},
                        {"label": "所有", "value": "all"},
                        {"label": "自定义", "value": "customized"},
                    ],
                    value="thisyear",
                ),
            ],
            className='radio-group',
        ),
        html.Div(
            id='customized-date-range-container',
            children=[
                dcc.RangeSlider(
                    id='customized-date-range',
                    min=2018,
                    max=2022,
                    step=None,
                    marks={year: str(year) for year in range(2018, 2023)},
                    value=[2018, 2022],
                )
            ],
            className='my-auto ml-0 mr-0',
            style={'max-width': '100%', 'display': 'none'}
        ),
        html.Hr(),
        dbc.Tabs([
            dbc.Tab(
                label='持仓明细',
                children=[
                    html.Br(),
                    dbc.Checklist(
                        id='show-cleared',
                        options=[{'label': '显示清仓品种', 'value': 'show'}],
                        value=[],
                        switch=True,
                    ),
                    html.Div(id='assets_cards'),
                    html.Center(
                        [
                            dbc.RadioItems(
                                id="assets-pagination",
                                className="btn-group",
                                labelClassName="btn btn-secondary",
                                labelCheckedClassName="active",
                                options=[
                                    {"label": "1", "value": 0},
                                ],
                                value=0,
                            ),
                        ],
                        className='radio-group',
                    ),
                ]
            ),
            dbc.Tab(
                label='交易记录',
                children=[
                    html.Br(),
                    html.Div(id='deals_table'),
                    html.Center(
                        [
                            dbc.RadioItems(
                                id="deals-pagination",
                                className="btn-group",
                                labelClassName="btn btn-secondary",
                                labelCheckedClassName="active",
                                options=[
                                    {"label": "1", "value": 0},
                                ],
                                value=0,
                            ),
                        ],
                        className='radio-group',
                    ),
                ]
            ),
        ])
    ],
)


@APP.callback(
    [
        dash.dependencies.Output('assets', 'data'),
        dash.dependencies.Output('stats', 'data'),
        dash.dependencies.Output('accounts_history', 'data'),
        dash.dependencies.Output('index_history', 'data'),
        dash.dependencies.Output('deals', 'data'),
        dash.dependencies.Output('deals-pagination', 'options'),
        dash.dependencies.Output('assets-pagination', 'options'),
    ],
    [
        dash.dependencies.Input('checklist', 'value'),
        dash.dependencies.Input('compare', 'value'),
    ],
)
def update_after_check(accounts, index_codes):
    accounts = accounts or all_accounts
    summary_data, assets_data = get_accounts_summary(accounts)

    history = get_accounts_history(accounts).to_dict('records')
    history.sort(key=itemgetter('account', 'date'))

    index_history = []
    for index_code in index_codes:
        index = Asset.get(zs_code=index_code)
        for record in index.history:
            index_history.append({
                'account': index.name,
                'date': record.date,
                'price': record.close_price
            })

    index_history.sort(key=itemgetter('account', 'date'))

    deals = []
    for record in Deal.get_deals(accounts):
        deals.append({
            'account': record.account,
            'time': record.time,
            'code': record.asset.zs_code,
            'name': record.asset.name,
            'action': record.action,
            'amount': record.amount,
            'price': record.price,
            'money': record.money,
            'fee': record.fee,
        })

    deals.sort(key=itemgetter('time'), reverse=True)

    valid_deals_count = 0
    for item in deals:
        if item['action'] == 'fix_cash':
            continue

        if item['code'] == 'CASH' and item['action'] == 'reinvest':
            continue

        valid_deals_count += 1

    pagination_options = [
        {'label': idx + 1, 'value': idx}
        for idx in range(ceil(valid_deals_count / 100))
    ]

    assets_pagination_options = []
    return (
        assets_data,
        summary_data,
        history,
        index_history,
        deals,
        pagination_options,
        assets_pagination_options
    )


@APP.callback(
    dash.dependencies.Output('account-summary', 'children'),
    [
        dash.dependencies.Input('stats', 'data'),
        dash.dependencies.Input('show-money', 'value')
    ]
)
def update_summary(stats, show_money):
    body_content = []
    body_content.append(
        make_card_component(
            [
                {
                    'item_cls': html.P,
                    'type': 'text',
                    'content': '总资产',
                    'color': 'bg-primary',
                },
                {
                    'item_cls': html.H4,
                    'type': 'money',
                    'content': stats['money'],
                    'color': 'bg-primary',
                },
            ],
            show_money=show_money,
            inverse=True
        )
    )
    body_content.append(
        make_card_component(
            [
                {
                    'item_cls': html.P,
                    'type': 'text',
                    'content': '日收益',
                    'color': 'bg-primary',
                },
                {
                    'item_cls': html.H4,
                    'type': 'money',
                    'content': stats['day_return'],
                    'color': 'bg-primary',
                },
                {
                    'item_cls': html.P,
                    'type': 'percent',
                    'content': stats['day_return_rate'],
                    'color': 'bg-primary',
                },
            ],
            show_money=show_money,
            inverse=True
        )
    )
    body_content.append(
        make_card_component(
            [
                {
                    'item_cls': html.P,
                    'type': 'text',
                    'content': '累计收益',
                    'color': 'bg-primary',
                },
                {
                    'item_cls': html.H4,
                    'type': 'money',
                    'content': stats['return'],
                    'color': 'bg-primary',
                },
                {
                    'item_cls': html.P,
                    'type': 'percent',
                    'content': stats['return_rate'] if stats['amount'] > 0 else 'N/A(已清仓)',
                    'color': 'bg-primary',
                },
            ],
            show_money=show_money,
            inverse=True
        )
    )
    body_content.append(
        make_card_component(
            [
                {
                    'item_cls': html.P,
                    'type': 'text',
                    'content': '年化收益率',
                    'color': 'bg-primary',
                },
                {
                    'item_cls': html.H4,
                    'type': 'percent',
                    'content': stats['annualized_return'],
                    'color': 'bg-primary',
                },
            ],
            show_money=show_money,
            inverse=True,
        )
    )
    body_content.append(
        make_card_component(
            [
                {
                    'item_cls': html.P,
                    'type': 'text',
                    'content': '现金',
                    'color': 'bg-primary',
                },
                {
                    'item_cls': html.H4,
                    'type': 'money',
                    'content': stats['cash'],
                    'color': 'bg-primary',
                },

            ],
            show_money=show_money,
            inverse=True
        )
    )
    body_content.append(
        make_card_component(
            [
                {
                    'item_cls': html.P,
                    'type': 'text',
                    'content': '仓位',
                    'color': 'bg-primary',
                },
                {
                    'item_cls': html.H4,
                    'type': 'percent',
                    'content': stats['position'],
                    'color': 'bg-primary',
                },

            ],
            show_money=show_money,
            inverse=True
        )
    )

    card = dbc.Card(
        [
            dbc.CardBody(
                dbc.Row(
                    [dbc.Col([card_component]) for card_component in body_content],
                ),
                className='py-2',
            )
        ],
        className='my-auto',
        color='primary',
    )
    return [card]


@APP.callback(
    dash.dependencies.Output('assets_cards', 'children'),
    [
        dash.dependencies.Input('assets', 'data'),
        dash.dependencies.Input('show-money', 'value'),
        dash.dependencies.Input('show-cleared', 'value'),
    ]
)
def update_assets_table(assets_data, show_money, show_cleared):
    cards = [html.Hr()]
    for row in assets_data:
        if not show_cleared and abs(row['amount']) <= 0.001:
            continue

        if row["code"] in ('CASH', 'WZZNCK'):
            continue

        cards.append(make_asset_card(row, show_money))
        cards.append(html.Br())

    return cards


def make_asset_card(asset_info, show_money=True):

    def get_color(value):
        if not isinstance(value, (float, int)):
            return None

        if value > 0:
            return 'text-danger'
        if value < 0:
            return 'text-success'

        return None

    header = dbc.CardHeader([
        html.H5(
            html.A(
                f'{asset_info["name"]}({asset_info["code"]})',
                href=f'/asset/{asset_info["code"].replace(".", "").lower()}',
                target='_blank'
            ),
            className='mb-0'
        ),
        html.P(f'更新日期 {asset_info["price_date"]}', className='mb-0'),
    ])

    body_content = []
    body_content.append(
        make_card_component(
            [
                {'item_cls': html.P, 'type': 'text', 'content': '持有金额/份额'},
                {'item_cls': html.H4, 'type': 'money', 'content': asset_info['money']},
                {'item_cls': html.P, 'type': 'amount', 'content': asset_info['amount']}
            ],
            show_money=show_money,
        )
    )
    body_content.append(
        make_card_component(
            [
                {'item_cls': html.P, 'type': 'text', 'content': '日收益'},
                {
                    'item_cls': html.H4,
                    'type': 'money',
                    'content': asset_info['day_return'],
                    'color': get_color(asset_info['day_return']),
                },
                {
                    'item_cls': html.P,
                    'type': 'percent',
                    'content': asset_info['day_return_rate'],
                    'color': get_color(asset_info['day_return']),
                }
            ],
            show_money=show_money,
        )
    )
    body_content.append(
        make_card_component(
            [
                {'item_cls': html.P, 'type': 'text', 'content': '现价/成本'},
                {'item_cls': html.H4, 'type': 'price', 'content': asset_info['price']},
                {'item_cls': html.P, 'type': 'price', 'content': asset_info['avg_cost'] or 'N/A'}
            ],
            show_money=show_money,
        )
    )

    asset = Asset.get(zs_code=asset_info['code'])
    prices = []
    for item in asset.history.order_by(AssetMarketHistory.date.desc()).limit(10):
        if item.close_price is not None:
            prices.append({
                'date': item.date,
                'price': item.close_price,
            })
        else:
            prices.append({
                'date': item.date,
                'price': item.nav,
            })

        if len(prices) >= 10:
            break

    prices.sort(key=itemgetter('date'))
    df = pd.DataFrame(prices)
    df['date'] = pd.to_datetime(df['date'])
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df['date'],
            y=df['price'],
            showlegend=False,
            marker={'color': 'orange'},
            mode='lines+markers',
        )
    )
    fig.update_layout(
        width=150,
        height=100,
        margin={'l': 4, 'r': 4, 'b': 20, 't': 10, 'pad': 4},
        xaxis={'showticklabels': False, 'showgrid': False, 'fixedrange': True},
        yaxis={'showticklabels': False, 'showgrid': False, 'fixedrange': True},
    )
    fig.update_xaxes(
        rangebreaks=[
            {'bounds': ["sat", "mon"]},
            {
                'values': get_holidays(df.date.min(), df.date.max(), False)
            }
        ]
    )
    body_content.append(
        make_card_component(
            [
                {'item_cls': html.P, 'type': 'text', 'content': '十日走势'},
                {
                    'item_cls': None,
                    'type': 'figure',
                    'content': fig
                }
            ],
            show_money=show_money
        )
    )
    body_content.append(
        make_card_component(
            [
                {'item_cls': html.P, 'type': 'text', 'content': '累计收益'},
                {
                    'item_cls': html.H4,
                    'type': 'money',
                    'content': asset_info['return'],
                    'color': get_color(asset_info['return']),
                },
                {
                    'item_cls': html.P,
                    'type': 'percent',
                    'content': asset_info['return_rate'],
                    'color': get_color(asset_info['return']),
                }
            ],
            show_money=show_money,
        )
    )
    body_content.append(
        make_card_component(
            [
                {'item_cls': html.P, 'type': 'text', 'content': '占比'},
                {'item_cls': html.H4, 'type': 'percent', 'content': asset_info['position']},
            ],
            show_money=show_money,
        )
    )

    card = dbc.Card(
        [
            header,
            dbc.CardBody(
                dbc.Row(
                    [dbc.Col([card_component]) for card_component in body_content],
                ),
                className='py-2',
            )
        ],
        className='my-auto'
    )

    return card


@APP.callback(
    dash.dependencies.Output('return-curve-chart', 'figure'),
    [
        dash.dependencies.Input('accounts_history', 'data'),
        dash.dependencies.Input('index_history', 'data'),
        dash.dependencies.Input('start-date', 'data'),
        dash.dependencies.Input('end-date', 'data'),
    ]
)
def draw_return_chart(accounts_history, index_history, start_date, end_date):
    df = pd.DataFrame(accounts_history)[['amount', 'account', 'date', 'nav']]
    df['date'] = pd.to_datetime(df['date'])
    if start_date is not None:
        df = df[df['date'] >= pd.to_datetime(start_date)]
    if end_date is not None:
        df = df[df['date'] < pd.to_datetime(end_date)]

    df = df[df['account'] == '总计']
    df['account'] = '我的'

    fig = go.Figure()
    if len(df) > 0:
        start_nav = float(df[df['date'] == df['date'].min()].nav)
        df.loc[:, 'nav'] = df['nav'] / start_nav - 1.0
        df.rename(columns={'nav': 'return'}, inplace=True)
        df = df.drop(df[df['amount'] <= 0].index)[['account', 'date', 'return']]
        start_date = df.date.min()
        fig.add_trace(
            go.Scatter(
                x=df['date'],
                y=df['return'],
                marker={'color': 'orange'},
                name='我的',
                mode='lines',
            )
        )

    index_df = None
    if index_history:
        index_history = pd.DataFrame(index_history)
        index_history['date'] = pd.to_datetime(index_history['date'])
        if start_date is not None:
            index_history = index_history[index_history['date'] >= pd.to_datetime(start_date)]
        if end_date is not None:
            index_history = index_history[index_history['date'] < pd.to_datetime(end_date)]

        index_names = set(index_history.account)
        for name in index_names:
            cur_df = index_history[index_history['account'] == name].copy()
            cur_df.loc[:, 'price'] = cur_df['price'] / cur_df.iloc[0].price - 1.0
            cur_df.rename(columns={'price': 'return'}, inplace=True)
            if index_df is None:
                index_df = cur_df
            else:
                index_df = pd.concat([index_df, cur_df], ignore_index=True)

            fig.add_trace(
                go.Scatter(x=cur_df['date'], y=cur_df['return'], name=name)
            )

    fig.update_layout(
        legend_title_text='',
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, font_size=14),
        margin={'l': 4, 'r': 4, 'b': 20, 't': 10, 'pad': 4},
        yaxis_tickformat='%',
        xaxis_tickformat="%m/%d\n%Y",
        hovermode='x unified',
        xaxis={'fixedrange': True},
        yaxis={'fixedrange': True},
    )
    return fig


@APP.callback(
    [
        dash.dependencies.Output('profit_detail_graph', 'figure'),
        dash.dependencies.Output('loss_detail_graph', 'figure'),
        dash.dependencies.Output('quit_profits_table', 'columns'),
        dash.dependencies.Output('quit_profits_table', 'data'),
        dash.dependencies.Output('quit_loss_table', 'columns'),
        dash.dependencies.Output('quit_loss_table', 'data'),
    ],
    [
        dash.dependencies.Input('stats', 'data'),
        dash.dependencies.Input('assets', 'data'),
        dash.dependencies.Input('show-money', 'value')
    ]
)
def update_return_details(stats_data, assets_data, show_money):
    stats = stats_data
    total_return = stats['money'] - stats['amount']

    assets = pd.DataFrame(assets_data)
    profits, loss, total_profit = [], [], 0
    for _, row in assets.iterrows():
        if row['code'] == 'CASH':
            continue

        return_value = row['return']
        if abs(return_value) < 0.001:
            continue
        if return_value > 0:
            profits.append({
                'code': row['code'],
                'name': row['name'],
                'branch': '盈利',
                'return_value': return_value,
                'category': '实盈' if row['amount'] <= 0 else '浮盈',
            })
        else:
            loss.append({
                'code': row['code'],
                'name': row['name'],
                'branch': '亏损',
                'return_value': abs(return_value),
                'category': '实亏' if row['amount'] <= 0 else '浮亏',
            })

        total_profit += return_value

    if abs(total_return - total_profit) > 0.001:
        profits.append({
            'category': '实盈',
            'code': 'CASH',
            'name': '现金',
            'branch': '盈利',
            'return_value': round(total_return - total_profit, 2),
        })

    if not show_money:
        profit_sum = sum([item['return_value'] for item in profits])
        for item in profits:
            item['return_value'] = round(10000 * item['return_value'] / profit_sum, 2)

        loss_sum = sum([item['return_value'] for item in loss])
        for item in loss:
            item['return_value'] = round(10000 * item['return_value'] / loss_sum, 2)

    profits = profits or [{
        'code': '',
        'name': '',
        'branch': '盈利',
        'category': '实盈',
        'return_value': 0,
    }]
    profits = pd.DataFrame(profits)
    if not show_money:
        profits.loc[:, 'return_value'] = profits['return_value'] / 10000

    profit_fig = px.treemap(
        profits,
        path=['branch', 'category', 'name'],
        values='return_value',
        branchvalues="total",
        color='name',
    )
    profit_fig.update_layout(margin={'l': 4, 'r': 4, 'b': 20, 't': 10, 'pad': 4})

    loss = loss or [{
        'code': '',
        'name': '',
        'branch': '亏损: 无',
        'category': '实亏',
        'return_value': 0,
    }]
    loss = pd.DataFrame(loss)
    if not show_money:
        loss.loc[:, 'return_value'] = loss['return_value'] / 10000

    loss_fig = px.treemap(
        loss,
        path=['branch', 'category', 'name'],
        values='return_value',
        branchvalues="total",
        color='name',
    )
    loss_fig.update_layout(margin={'l': 4, 'r': 4, 'b': 20, 't': 10, 'pad': 4})

    df = profits[['code', 'name', 'return_value']]
    df = df.rename(columns={'return_value': '盈利', **COLUMN_MAPPINGS})

    columns1, columns2 = [], []
    for name in df.columns:
        if name != '盈利':
            columns1.append({'id': name, 'name': name})
            columns2.append({'id': name, 'name': name})
            continue

        column = {'type': 'numeric'}
        if not show_money:
            column['format'] = Format(scheme='%', precision=2)
        else:
            column['format'] = Format(scheme=Scheme.fixed, precision=2)

        columns1.append({'id': '盈利', 'name': '盈利', **column})
        columns2.append({'id': '亏损', 'name': '亏损', **column})

    data1 = df.to_dict('records')
    data1.sort(key=itemgetter('盈利'), reverse=True)

    df = loss[['code', 'name', 'return_value']]
    df = df.rename(columns={'return_value': '亏损', **COLUMN_MAPPINGS})
    data2 = [item for item in df.to_dict('records') if item['名称']]
    data2.sort(key=itemgetter('亏损'), reverse=True)

    return profit_fig, loss_fig, columns1, data1, columns2, data2


@APP.callback(
    dash.dependencies.Output('deals_table', 'children'),
    [
        dash.dependencies.Input('deals', 'data'),
        dash.dependencies.Input('show-money', 'value'),
        dash.dependencies.Input('deals-pagination', 'value'),
    ]
)
def add_deal_record(deals, show_money, page_num):
    cards = []
    deals = [
        item for item in deals
        if item['action'] != 'fix_cash' and not (
            item['code'] == 'CASH' and item['action'] == 'reinvest'
        )
    ]
    for row in deals[page_num * 100:(page_num + 1) * 100]:
        cards.append(make_deal_card(row, show_money))
        cards.append(html.Br())

    return cards


def make_deal_card(deal_info, show_money=False):
    action_mappings = {
        'transfer_in': '转入',
        'transfer_out': '转出',
        'buy': '买入',
        'sell': '卖出',
        'reinvest': '红利再投资',
        'bonus': '现金分红',
        'spin_off': '拆分/合并'
    }

    body_content = []
    if deal_info['code'] not in ('CASH', 'WZZNCK'):
        body_content.append(
            make_card_component(
                [
                    {
                        'item_cls': html.P,
                        'type': 'text',
                        'content': f'{action_mappings[deal_info["action"]]}',
                    },
                    {
                        'item_cls': html.H5,
                        'type': 'text',
                        'content': html.A(
                            f'{deal_info["name"]}({deal_info["code"]})',
                            href=f'/asset/{deal_info["code"].replace(".", "").lower()}',
                            target='_blank'
                        ),
                    },
                    {
                        'item_cls': html.P,
                        'type': 'text',
                        'content': pd.to_datetime(deal_info['time']).strftime('%Y-%m-%d %H:%M:%S'),
                    }
                ],
                show_money=show_money
            )
        )
    else:
        body_content.append(
            make_card_component(
                [
                    {
                        'item_cls': html.P,
                        'type': 'text',
                        'content': f'{action_mappings[deal_info["action"]]}',
                    },
                    {
                        'item_cls': html.H5,
                        'type': 'text',
                        'content': deal_info['name'],
                    },
                    {
                        'item_cls': html.P,
                        'type': 'text',
                        'content': pd.to_datetime(deal_info['time']).strftime('%Y-%m-%d %H:%M:%S'),
                    }
                ],
                show_money=show_money
            )
        )

    body_content.extend([
        make_card_component(
            [
                {
                    'item_cls': html.P,
                    'type': 'text',
                    'content': '份额/价格',
                },
                {
                    'item_cls': html.H5,
                    'type': 'amount',
                    'content': deal_info['amount'],
                },
                {
                    'item_cls': html.P,
                    'type': 'price',
                    'content': deal_info['price'],
                }
            ],
            show_money=show_money
        ),
        make_card_component(
            [
                {
                    'item_cls': html.P,
                    'type': 'text',
                    'content': '金额/费用',
                },
                {
                    'item_cls': html.H5,
                    'type': 'money',
                    'content': deal_info['money'],
                },
                {
                    'item_cls': html.P,
                    'type': 'money',
                    'content': deal_info['fee'],
                }
            ],
            show_money=show_money
        )
    ])
    card = dbc.Card(
        [
            dbc.CardBody(
                dbc.Row(
                    [
                        dbc.Col([card_component], width=6 if idx == 0 else 3)
                        for idx, card_component in enumerate(body_content)
                    ],
                ),
                className='py-2',
            )
        ],
        className='my-auto'
    )

    return card


@APP.callback(
    dash.dependencies.Output('customized-date-range-container', 'style'),
    dash.dependencies.Input('date-range', 'value'),
)
def toggle_datepicker(date_range):
    if date_range == 'customized':
        return {'display': 'block'}

    return {'display': 'none'}


@APP.callback(
    [
        dash.dependencies.Output('start-date', 'data'),
        dash.dependencies.Output('end-date', 'data'),
    ],
    [
        dash.dependencies.Input('date-range', 'value'),
        dash.dependencies.Input('customized-date-range', 'value'),
    ]
)
def update_return_range(date_range, customized_date_range):
    start_date, end_date = None, None
    if date_range == '1m':
        start_date = (datetime.now() - timedelta(days=30)).date()
    elif date_range == '3m':
        start_date = (datetime.now() - timedelta(days=60)).date()
    elif date_range == '6m':
        start_date = (datetime.now() - timedelta(days=180)).date()
    elif date_range == '12m':
        start_date = (datetime.now() - timedelta(days=365)).date()
    elif date_range == 'thisyear':
        start_date = datetime.now().replace(month=1, day=1).date()
    elif date_range == 'thismonth':
        start_date = datetime.now().replace(day=1).date()
    elif date_range == 'thisweek':
        today = datetime.now().date()
        start_date = today - timedelta(days=today.weekday())
    elif date_range == 'customized' and customized_date_range:
        start_year, end_year = customized_date_range
        start_date = date(start_year, 1, 1)
        end_date = date(end_year, 1, 1)

    return start_date, end_date


@APP.callback(
    dash.dependencies.Output('asset-history-chart', 'figure'),
    [
        dash.dependencies.Input('accounts_history', 'data'),
        dash.dependencies.Input('show-money', 'value'),
        dash.dependencies.Input('start-date', 'data'),
        dash.dependencies.Input('end-date', 'data'),
    ]
)
def draw_asset_history(accounts_history, show_money, start_date, end_date):
    accounts_history.sort(key=itemgetter('date'))
    df = pd.DataFrame(accounts_history)
    df = df[df['account'] == '总计']
    df.date = pd.to_datetime(df.date)
    if start_date is not None:
        df = df[df['date'] >= pd.to_datetime(start_date)]
    if end_date is not None:
        df = df[df['date'] < pd.to_datetime(end_date)]

    if not show_money:
        df.loc[:, "amount"] = df.amount / accounts_history[0]['amount']
        df.loc[:, "money"] = df.money / accounts_history[0]['amount']

    df["color"] = np.where(df.money > df.amount, 'red', 'green')

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df.date,
            y=df.amount,
            name='总投入',
            marker={'color': 'green'},
            mode='lines',
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df.date,
            y=df.money,
            name='总资产',
            fill='tonexty',
            marker={'color': 'red'},
            mode='lines',
        )
    )
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, font_size=14),
        margin={'l': 4, 'r': 4, 'b': 20, 't': 10, 'pad': 4},
        xaxis={'fixedrange': True},
        yaxis={'fixedrange': True},
        hovermode='x unified',
    )
    fig.update_xaxes(tickformat="%m/%d\n%Y")

    return fig


@APP.callback(
    dash.dependencies.Output('portfolio-analysis', 'children'),
    dash.dependencies.Input('assets', 'data'),
)
def update_porfolio_analysis(assets):
    return html.P("hello")


@APP.callback(
    dash.dependencies.Output('total-return-chart', 'figure'),
    [
        dash.dependencies.Input('accounts_history', 'data'),
        dash.dependencies.Input('start-date', 'data'),
        dash.dependencies.Input('end-date', 'data'),
        dash.dependencies.Input('show-money', 'value')
    ]
)
def draw_total_return_chart(accounts_history, start_date, end_date, show_money):
    df = pd.DataFrame(accounts_history)
    df['date'] = pd.to_datetime(df['date'])
    if start_date is not None:
        df = df[df['date'] >= pd.to_datetime(start_date)]
    if end_date is not None:
        df = df[df['date'] < pd.to_datetime(end_date)]

    df = df[df['account'] == '总计']
    df.loc[:, 'return'] -= df.iloc[0]['return']
    df['account'] = '我的'

    if not show_money:
        max_return = df['return'].abs().max()
        df.loc[:, 'return'] = df['return'] / max_return

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df['date'],
            y=df['return'],
            marker={'color': 'orange'},
            mode='lines',
        )
    )

    max_idx = df['return'].argmax()
    fig.add_annotation(
        x=df.iloc[max_idx]['date'],
        y=df.iloc[max_idx]['return'],
        text=f'最大值: {df.iloc[max_idx]["return"]:0.2f}',
        showarrow=True,
        arrowhead=1
    )

    fig.update_layout(
        legend_title_text='',
        xaxis_tickformat='%m/%d\n%Y',
        margin={'l': 4, 'r': 4, 'b': 20, 't': 10, 'pad': 4},
        xaxis={'fixedrange': True},
        yaxis={'fixedrange': True},
        hovermode='x unified',
    )

    return fig


@APP.callback(
    dash.dependencies.Output('day-return-chart', 'figure'),
    [
        dash.dependencies.Input('accounts_history', 'data'),
        dash.dependencies.Input('start-date', 'data'),
        dash.dependencies.Input('end-date', 'data'),
        dash.dependencies.Input('show-money', 'value')
    ]
)
def draw_day_return_chart(accounts_history, start_date, end_date, show_money):
    df = pd.DataFrame(accounts_history)
    df['date'] = pd.to_datetime(df['date'])
    if start_date is not None:
        df = df[df['date'] >= pd.to_datetime(start_date)]
    if end_date is not None:
        df = df[df['date'] < pd.to_datetime(end_date)]

    df = df[df['account'] == '总计']
    df['day_return'] = (df['return'] - df['return'].shift()).replace({np.nan: 0})

    max_return = df['day_return'].abs().max()
    if not show_money:
        df.loc[:, 'day_return'] = df['day_return'] / max_return

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df[df['day_return'] >= 0]['date'],
            y=df[df['day_return'] >= 0]['day_return'],
            marker={'color': '#f2757a'},
            showlegend=False,
            name='盈利',
        )
    )
    fig.add_trace(
        go.Bar(
            x=df[df['day_return'] < 0]['date'],
            y=df[df['day_return'] < 0]['day_return'],
            marker={'color': 'green'},
            showlegend=False,
            name='亏损',
        )
    )
    fig.add_hline(
        y=df.day_return.mean(),
        annotation_text="平均值",
        annotation_position="top left",
        line_width=1,
        opacity=0.5,
        line_dash='dot',
    )
    fig.add_hline(
        y=df.day_return.std(),
        annotation_text="标准差",
        annotation_position="top left",
        line_width=1,
        line_dash='dot',
        opacity=0.5,
    )
    fig.update_layout(
        legend_title_text='',
        legend=dict(
            font_size=24,
        ),
        xaxis_tickformat='%m/%d\n%Y',
        margin={'l': 4, 'r': 4, 'b': 20, 't': 10, 'pad': 4},
        xaxis={'fixedrange': True},
        yaxis={'fixedrange': True},
        hovermode='x unified',
    )
    fig.update_xaxes(
        tickformat="%m/%d\n%Y",
        rangebreaks=[
            {'bounds': ["sat", "mon"]},
            {
                'values': get_holidays(df.date.min(), df.date.max(), False)
            }
        ]
    )
    return fig
