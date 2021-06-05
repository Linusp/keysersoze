import dash
import dash_bootstrap_components as dbc


external_stylesheets = [dbc.themes.BOOTSTRAP]
APP = dash.Dash(__name__, external_stylesheets=external_stylesheets)
