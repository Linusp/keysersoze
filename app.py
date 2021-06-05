import logging
from logging.config import dictConfig

import click
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output

from keysersoze.apps.app import APP
from keysersoze.apps import portfolio
from keysersoze.apps.asset_page import generate_asset_page


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


LOGO = APP.get_asset_url('logo.png')
APP.title = '投资账户概览'
APP.layout = html.Div(
    [
        dcc.Location(id='url', refresh=False),
        html.Link(
            rel='stylesheet',
            href=APP.get_asset_url('css/style.css'),
        ),
        html.Div(id='page-content')
    ],
    style={
        'padding-top': 20,
        'padding-left': '10%',
        'padding-right': '10%',
    },
)


@APP.callback(
    Output('page-content', 'children'),
    Input('url', 'pathname')
)
def display_page(pathname):
    if pathname in ('/portfolio', '/'):
        APP.title = '投资账户概览'
        return portfolio.layout
    elif pathname.startswith('/asset/'):
        asset_code = pathname.replace('/asset/', '').strip('/')
        layout = generate_asset_page(asset_code)
        return layout
    else:
        return '404'


@click.command()
@click.option("--port", type=int, default=8050)
@click.option("--debug", is_flag=True)
def main(port, debug):
    APP.run_server(host='0.0.0.0', port=port, debug=debug)


if __name__ == '__main__':
    main()
