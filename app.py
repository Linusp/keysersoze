import logging
from operator import itemgetter
from logging.config import dictConfig

import dash
import dash_table
from dash_table.Format import Format, Scheme
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd

from keysersoze.models import (
    Deal,
    Asset,
    AssetMarketHistory,
)
from keysersoze.utils import (
    get_accounts_history,
    get_accounts_summary,
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
}
FORMATS = {
    '价格日期': {'type': 'datetime', 'format': Format(nully='N/A')},
    '占比': {'type': 'numeric', 'format': Format(scheme='%', precision=2)},
    '收益率': {'type': 'numeric', 'format': Format(nully='N/A', scheme='%', precision=2)},
    '份额': {'type': 'numeric', 'format': Format(nully='N/A', precision=2, scheme=Scheme.fixed)},
    '金额': {'type': 'numeric', 'format': Format(nully='N/A', precision=2, scheme=Scheme.fixed)},
    '投入': {'type': 'numeric', 'format': Format(nully='N/A', precision=2, scheme=Scheme.fixed)},
    '成本': {'type': 'numeric', 'format': Format(nully='N/A', precision=4, scheme=Scheme.fixed)},
    '价格': {'type': 'numeric', 'format': Format(nully='N/A', precision=4, scheme=Scheme.fixed)},
    '收益': {'type': 'numeric', 'format': Format(nully='N/A', precision=2, scheme=Scheme.fixed)},
}
ACCOUNT_PRIORITIES = {
    '长期投资': 0,
    'U定投': 1,
    '长赢定投': 2,
    '投资实证': 3,
    '稳健投资': 4,
    '蛋卷基金': 5,
    '华宝证券': 6,
    '平安证券': 7,
    '微众银行': 8,
}


def main():
    external_stylesheets = [dbc.themes.BOOTSTRAP]
    app = dash.Dash(__name__, external_stylesheets=external_stylesheets)

    all_accounts = [deal.account for deal in Deal.select(Deal.account).distinct()]
    all_accounts.sort(key=lambda name: ACCOUNT_PRIORITIES.get(name, 1000))
    app.layout = html.Div(
        [
            dcc.Store(id='assets'),
            dcc.Store(id='stats'),
            dcc.Store(id='accounts_history'),
            dcc.Store(id='index_history'),
            dcc.Store(id='deals'),
            html.H3('投资账户概览'),
            dbc.Checklist(
                id='show-money',
                options=[{'label': '显示金额', 'value': 'show'}],
                value=[],
                switch=True,
            ),
            html.Hr(),
            dbc.Label('选择账户'),
            dbc.Checklist(
                id='checklist',
                options=[{'label': a, 'value': a} for a in all_accounts],
                value=[],
                inline=True,
            ),
            html.Br(),
            html.Div([
                dbc.Row(
                    [
                        dbc.Col([
                            dbc.Card(
                                dbc.CardBody([
                                    html.P("累计收益"),
                                    html.H4(id="total_return"),
                                ]),
                                color='primary',
                                inverse=True,
                            ),
                        ]),
                        dbc.Col([
                            dbc.Card(
                                dbc.CardBody([
                                    html.P("累计收益率"),
                                    html.H4(id="total_return_rate"),
                                ]),
                                color='primary',
                                inverse=True,
                            )
                        ]),
                        dbc.Col([
                            dbc.Card(
                                dbc.CardBody([
                                    html.P("年化收益率"),
                                    html.H4(id="annualized_return"),
                                ],),
                                color='primary',
                                inverse=True,
                            )
                        ]),
                        dbc.Col([
                            dbc.Card(
                                dbc.CardBody([
                                    html.P("仓位"),
                                    html.H4(id="position"),
                                ]),
                                color='primary',
                                inverse=True,
                            )
                        ]),
                    ],
                    no_gutters=True
                ),
            ]),
            html.Br(),
            dcc.Tabs([
                dcc.Tab(
                    label='收益率走势',
                    children=[
                        html.Br(),
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
                        ),
                        dcc.Graph(id="return-curve-chart"),
                    ]
                ),
                dcc.Tab(
                    label='盈亏明细',
                    children=[
                        html.Br(),
                        dbc.Row([
                            dbc.Col([dcc.Graph(id="profit_detail_graph")]),
                            dbc.Col([dcc.Graph(id="loss_detail_graph")]),
                        ]),
                        dbc.Row([
                            dbc.Col([
                                html.H3('已清仓资产列表（盈利）'),
                                dash_table.DataTable(id='quit_profits_table')
                            ]),
                            dbc.Col([
                                html.H3('已清仓资产列表（亏损）'),
                                dash_table.DataTable(id='quit_loss_table')
                            ]),
                        ])
                    ]
                ),
                dcc.Tab(
                    label='持仓明细',
                    children=[
                        html.Br(),
                        dash_table.DataTable(id='assets_table')
                    ]
                ),
                dcc.Tab(
                    label='交易记录',
                    children=[
                        html.Br(),
                        dash_table.DataTable(
                            id='deals_table',
                            editable=True,
                            page_current=0,
                            page_size=20,
                            page_action='custom',
                        ),
                    ]
                )
            ])
        ],
        style={
            'padding-left': '10%',
            'padding-right': '10%',
        }
    )

    @app.callback(
        [
            dash.dependencies.Output('assets', 'data'),
            dash.dependencies.Output('stats', 'data'),
            dash.dependencies.Output('accounts_history', 'data'),
            dash.dependencies.Output('index_history', 'data'),
            dash.dependencies.Output('deals', 'data'),
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
        begin_date = min(history, key=itemgetter('date'))['date']
        end_date = max(history, key=itemgetter('date'))['date']
        for index_code in index_codes:
            index = Asset.get(zs_code=index_code)
            search = index.history.where(AssetMarketHistory.date >= begin_date)
            search = search.where(AssetMarketHistory.date <= end_date)
            for record in search:
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

        return assets_data, summary_data, history, index_history, deals

    @app.callback(
        [
            dash.dependencies.Output('total_return', 'children'),
            dash.dependencies.Output('total_return_rate', 'children'),
            dash.dependencies.Output('annualized_return', 'children'),
            dash.dependencies.Output('position', 'children'),
        ],
        [
            dash.dependencies.Input('stats', 'data'),
            dash.dependencies.Input('show-money', 'value')
        ]
    )
    def update_stats(stats, show_money):
        item = [row for row in stats if row['account'] == '总计'][0]
        total_return = f'{item["return"]:0.2f}' if show_money else '**********'
        if item['amount'] > 0:
            total_return_rate = f'{100 * item["return_rate"]:0.2f}%'
        else:
            total_return_rate = 'N/A(已清仓)'

        annualized_return = f'{100 * item["annualized_return"]:0.2f}%'
        position = f'{100 * item["position"]:0.2f}%'
        return total_return, total_return_rate, annualized_return, position

    @app.callback(
        [
            dash.dependencies.Output('assets_table', 'data'),
            dash.dependencies.Output('assets_table', 'columns'),
            dash.dependencies.Output('assets_table', 'style_data_conditional'),
        ],
        [
            dash.dependencies.Input('assets', 'data'),
            dash.dependencies.Input('show-money', 'value')
        ]
    )
    def update_assets_table(assets_data, show_money):
        df = pd.DataFrame(assets_data)
        df = df[df['amount'] > 0]
        df = df.rename(columns=COLUMN_MAPPINGS)
        columns = [
            {
                "name": name,
                "id": name,
                **FORMATS.get(name, {})
            }
            for name in df.columns
        ]
        style_data_conditional = [
            {
                'if': {
                    'filter_query': '{收益率} < 0',
                    'column_id': '收益率',
                },
                'backgroundColor': '#3D9970',
            },
            {
                'if': {
                    'filter_query': '{收益率} > 0',
                    'column_id': '收益率',
                },
                'backgroundColor': '#FF4136',
            }
        ]
        if not show_money:
            df['份额'] = '****'
            df['金额'] = '****'
            df['投入'] = '****'
            df['收益'] = '****'

        return df.to_dict('records'), columns, style_data_conditional

    @app.callback(
        dash.dependencies.Output('return-curve-chart', 'figure'),
        [
            dash.dependencies.Input('accounts_history', 'data'),
            dash.dependencies.Input('index_history', 'data')
        ]
    )
    def update_return_chart(accounts_history, index_history):
        df = pd.DataFrame(accounts_history)
        df = df[df['account'] == '总计']
        df['account'] = '我的'
        df['nav'] -= 1.0
        df.rename(columns={'nav': 'return'}, inplace=True)

        index_df = None
        if index_history:
            index_history = pd.DataFrame(index_history)
            index_names = set(index_history.account)
            for name in index_names:
                cur_df = index_history[index_history['account'] == name]
                cur_df['price'] /= cur_df.iloc[0].price
                cur_df['price'] -= 1.0
                cur_df.rename(columns={'price': 'return'}, inplace=True)
                if not index_df:
                    index_df = cur_df
                else:
                    index_df = pd.concat([index_df, cur_df], ignore_index=True)

        df = df.drop(df[df['amount'] <= 0].index)[['account', 'date', 'return']]
        df = pd.concat([df, index_df], ignore_index=True)

        fig = px.line(df, x='date', y='return', color='account', height=500)
        fig.update_layout(
            legend_title_text='',
            legend=dict(
                font_size=24,
            ),
            yaxis_tickformat='%',
            margin={'l': 4, 'r': 4, 'b': 20, 't': 40, 'pad': 4},
        ),
        fig.update_xaxes(
            # rangeslider_visible=True,
            rangeselector=dict(
                buttons=list([
                    dict(count=1, label="近一月", step="month", stepmode="backward"),
                    dict(count=3, label="近三月", step="month", stepmode="backward"),
                    dict(count=6, label="近半年", step="month", stepmode="backward"),
                    dict(count=1, label="今年以来", step="year", stepmode="todate"),
                    dict(count=1, label="近一年", step="year", stepmode="backward"),
                    dict(label='所有', step="all")
                ]),
            ),
            tickformat='%Y/%m/%d',
        )
        return fig

    @app.callback(
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
        stats = [row for row in stats_data if row['account'] == '总计'][0]
        total_return = stats['money'] - stats['amount']

        assets = pd.DataFrame(assets_data)
        profits, loss, total_profit = [], [], 0
        for _, row in assets.iterrows():
            if row['code'] == 'CASH':
                continue

            value = row['return']
            if abs(value) < 0.001:
                continue
            if value > 0:
                profits.append({
                    'code': row['code'],
                    'name': row['name'],
                    'branch': '盈利',
                    'value': value,
                    'category': '实盈' if row['amount'] <= 0 else '浮盈',
                })
            else:
                loss.append({
                    'code': row['code'],
                    'name': row['name'],
                    'branch': '亏损',
                    'value': abs(value),
                    'category': '实亏' if row['amount'] <= 0 else '浮亏',
                })

            total_profit += value

        if abs(total_return - total_profit) > 0.001:
            profits.append({
                'category': '实盈',
                'code': 'CASH',
                'name': '现金',
                'branch': '盈利',
                'value': round(total_return - total_profit, 2),
            })

        if not show_money:
            profit_sum = sum([item['value'] for item in profits])
            for item in profits:
                item['value'] = round(10000 * item['value'] / profit_sum, 2)

            loss_sum = sum([item['value'] for item in loss])
            for item in loss:
                item['value'] = round(10000 * item['value'] / loss_sum, 2)

        profits = profits or [{
            'code': '',
            'name': '',
            'branch': '盈利',
            'category': '实盈',
            'value': 0,
        }]
        profits = pd.DataFrame(profits)
        profit_fig = px.treemap(
            profits,
            path=['branch', 'category', 'name'],
            values='value',
            branchvalues="total",
            color='name',
        )
        profit_fig.update_layout(margin={'l': 4, 'r': 4, 'b': 20, 't': 10, 'pad': 4})

        loss = loss or [{
            'code': '',
            'name': '',
            'branch': '亏损: 无',
            'category': '实亏',
            'value': 0,
        }]
        loss = pd.DataFrame(loss)
        loss_fig = px.treemap(
            loss,
            path=['branch', 'category', 'name'],
            values='value',
            branchvalues="total",
            color='name',
        )
        loss_fig.update_layout(margin={'l': 4, 'r': 4, 'b': 20, 't': 10, 'pad': 4})

        df = profits[profits['category'] == '实盈'][['code', 'name', 'value']]
        if not show_money:
            df['value'] /= 10000

        df.rename(columns={'value': '盈利', **COLUMN_MAPPINGS}, inplace=True)

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

        df = loss[loss['category'] == '实亏'][['code', 'name', 'value']]
        if not show_money:
            df['value'] /= 10000

        df.rename(columns={'value': '亏损', **COLUMN_MAPPINGS}, inplace=True)
        data2 = [item for item in df.to_dict('records') if item['名称']]

        return profit_fig, loss_fig, columns1, data1, columns2, data2

    @app.callback(
        [
            dash.dependencies.Output('deals_table', 'columns'),
            dash.dependencies.Output('deals_table', 'data'),
        ],
        [
            dash.dependencies.Input('deals', 'data'),
            dash.dependencies.Input('deals_table', 'page_current'),
            dash.dependencies.Input('deals_table', 'page_size'),
            dash.dependencies.Input('show-money', 'value')
        ]
    )
    def add_deal_record(deals, page_current, page_size, show_money):
        start = page_current * page_size
        end = (page_current + 1) * page_size
        df = pd.DataFrame(deals[start:end])
        df = df.rename(columns=COLUMN_MAPPINGS)
        if not show_money:
            df['份额'] = '***'
            df['金额'] = '***'
            df['费用'] = '***'

        columns = [{'id': name, 'name': name} for name in df.columns]
        return columns, df.to_dict('records')

    app.run_server(debug=True)


if __name__ == '__main__':
    main()
