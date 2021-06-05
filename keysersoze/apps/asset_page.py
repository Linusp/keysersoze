import re
from operator import itemgetter
from datetime import datetime, timedelta, date

import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
import pandas as pd
from chinese_calendar import get_holidays
import plotly.graph_objects as go

from keysersoze.models import (
    Deal,
    Asset,
    AssetMarketHistory,
)
from keysersoze.apps.app import APP
from keysersoze.apps.utils import make_card_component


def generate_asset_page(asset_code):
    asset_code = re.sub(r'^([0-9]+)([a-zA-Z]+)$', r'\1.\2', asset_code).upper()
    layout = html.Div([
        dcc.Store(id='asset-code', data=asset_code),
        html.Div(id='asset-info'),
        dbc.Checklist(
            id='show-asset-money',
            options=[{'label': '显示金额', 'value': 'show'}],
            value=[],
            switch=True,
        ),
        html.Hr(),
        dcc.Graph(
            id='asset-prices-graph',
            config={
                'displayModeBar': False
            },
        ),
        html.Center(
            [
                dbc.RadioItems(
                    id="asset-history-range",
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
                    value="all",
                ),
            ],
            className='radio-group',
        ),
        html.Div(
            id='customized-asset-history-range-container',
            children=[
                dcc.RangeSlider(
                    id='customized-asset-history-range',
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
        html.Div(id='asset-deals'),
    ])
    return layout


@APP.callback(
    dash.dependencies.Output('asset-info', 'children'),
    dash.dependencies.Input('asset-code', 'data')
)
def update_asset_info(asset_code):
    asset = Asset.get(zs_code=asset_code)
    return [
        html.H3(f'{asset.name} ({asset.zs_code})'),
    ]


@APP.callback(
    dash.dependencies.Output('customized-asset-history-range-container', 'style'),
    dash.dependencies.Input('asset-history-range', 'value'),
)
def toggle_datepicker(date_range):
    if date_range == 'customized':
        return {'display': 'block'}

    return {'display': 'none'}


@APP.callback(
    dash.dependencies.Output('asset-prices-graph', 'figure'),
    [
        dash.dependencies.Input('asset-code', 'data'),
        dash.dependencies.Input('asset-history-range', 'value'),
        dash.dependencies.Input('customized-asset-history-range', 'value'),
    ]
)
def update_asset_graph(asset_code, date_range, customized_date_range):
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

    asset = Asset.get(zs_code=asset_code)
    deals = []
    for item in asset.deals:
        if item.action not in ('buy', 'sell'):
            continue

        if start_date and item.time.date() < start_date:
            continue

        if end_date and item.time.date() >= end_date:
            continue

        deals.append({
            'account': item.account,
            'date': item.time.date(),
            'action': item.action,
            'amount': item.amount,
            'price': item.price,
        })

    df = pd.DataFrame(deals)
    if len(deals):
        df.date = pd.to_datetime(df.date)

    fig = go.Figure()
    data = []
    min_date = df.date.min() if start_date is None else start_date
    prices = asset.history.where(AssetMarketHistory.date >= min_date)
    if end_date:
        prices = prices.where(AssetMarketHistory.date < end_date)

    for item in prices.order_by(AssetMarketHistory.date.desc()):
        if item.close_price is not None:
            data.append({
                'date': item.date,
                'open': item.open_price,
                'close': item.close_price,
                'high': item.high_price,
                'low': item.low_price,
            })
        else:
            data.append({
                'date': item.date,
                'price': item.nav,
            })

    data.sort(key=itemgetter('date'))
    price_df = pd.DataFrame(data)
    price_df.date = pd.to_datetime(price_df.date)
    if len(price_df.columns) == 2:
        fig.add_trace(
            go.Scatter(
                x=price_df.date,
                y=price_df.price,
                line={'color': 'orange', 'width': 2},
                name='价格',
                mode='lines'
            )
        )
        if deals and len(df[df.action == 'buy']) > 0:
            fig.add_trace(
                go.Scatter(
                    x=df[df.action == 'buy'].date,
                    y=df[df.action == 'buy'].price,
                    text=[f'{price:0.4f}' for price in df[df.action == 'buy'].price.tolist()],
                    name='买入',
                    mode='markers',
                    marker={'color': 'green'},
                )
            )
        if deals and len(df[df.action == 'sell']) > 0:
            fig.add_trace(
                go.Scatter(
                    x=df[df.action == 'sell'].date,
                    y=df[df.action == 'sell'].price,
                    text=[f'{price:0.4f}' for price in df[df.action == 'sell'].price.tolist()],
                    name='卖出',
                    mode='markers',
                    marker={'color': 'red'},
                )
            )
    else:
        fig.add_trace(
            go.Candlestick(
                x=price_df.date,
                open=price_df.open,
                close=price_df.close,
                high=price_df.high,
                low=price_df.low,
                name='价格',
                opacity=0.3,
                increasing_fillcolor='red',
                increasing_line_color='red',
                decreasing_line_color='green',
                decreasing_fillcolor='green',
            )
        )
        if deals and len(df[df.action == 'buy']) > 0:
            fig.add_trace(
                go.Scatter(
                    x=df[df.action == 'buy'].date,
                    y=df[df.action == 'buy'].price,
                    text=[f'{price:0.4f}' for price in df[df.action == 'buy'].price.tolist()],
                    name='买入',
                    mode='markers',
                    marker={'color': '#1E90FF'},
                )
            )
        if deals and len(df[df.action == 'sell']) > 0:
            fig.add_trace(
                go.Scatter(
                    x=df[df.action == 'sell'].date,
                    y=df[df.action == 'sell'].price,
                    text=[f'{price:0.4f}' for price in df[df.action == 'sell'].price.tolist()],
                    name='卖出',
                    mode='markers',
                    marker={'color': 'purple'},
                )
            )

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=500,
        margin={'l': 4, 'r': 4, 'b': 20, 't': 10, 'pad': 4},
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, font_size=14),
        xaxis={'fixedrange': True},
        yaxis={'fixedrange': True},
    )
    fig.update_xaxes(
        tickformat="%m/%d\n%Y",
        rangebreaks=[
            {'bounds': ["sat", "mon"]},
            {
                'values': get_holidays(price_df.date.min(), price_df.date.max(), False)
            }
        ]
    )
    return fig


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
    body_content = [
        make_card_component(
            [
                {
                    'item_cls': html.H5,
                    'type': 'text',
                    'content': action_mappings[deal_info['action']]
                },
                {
                    'item_cls': html.P,
                    'type': 'text',
                    'content': pd.to_datetime(deal_info['time']).strftime('%Y-%m-%d %H:%M:%S'),
                },
            ]
        ),
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
    ]
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
    dash.dependencies.Output('asset-deals', 'children'),
    [
        dash.dependencies.Input('asset-code', 'data'),
        dash.dependencies.Input('show-asset-money', 'value')
    ]
)
def update_asset_deals(asset_code, show_money):
    cards = []
    asset = Asset.get(zs_code=asset_code)
    deals = [
        {
            'account': item.account,
            'time': item.time,
            'action': item.action,
            'amount': item.amount,
            'price': item.price,
            'money': item.money,
            'fee': item.fee,
        }
        for item in asset.deals.order_by(Deal.time.desc())
    ]
    for row in deals:
        cards.append(make_deal_card(row, show_money))
        cards.append(html.Br())

    return cards
