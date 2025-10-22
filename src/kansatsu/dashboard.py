# FILE: src/kansatsu/dashboard.py

import dash
from dash import dcc, html, dash_table, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from flask import Flask, request, jsonify
import threading
import time
import pandas as pd
from collections import deque
from datetime import datetime
import argparse
import logging
import sys
from . import __version__

data_lock = threading.Lock()
MAX_GRAPH_POINTS = 30
app_data = {
    "general_stats": {"total_calls": 0, "errors": 0, "interaction_count": 0, "total_interaction_time_ms": 0.0},
    "llm_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    "quality_rai": {"quality_scores": [], "rai_alerts": []},
    "method_details": {},
    "live_graphs": {},
    "session_ended": False,
}

server = Flask(__name__)
app = dash.Dash(__name__, server=server, external_stylesheets=[dbc.themes.DARKLY])
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR) # Suppress noisy Flask logs

def get_default_live_graph_data():
    return {
        'timestamps': deque(maxlen=MAX_GRAPH_POINTS),
        'calls': deque(maxlen=MAX_GRAPH_POINTS),
        'tokens': deque(maxlen=MAX_GRAPH_POINTS),
    }

@server.route('/update', methods=['POST'])
def update_data():
    payload = request.json
    with data_lock:
        update_type = payload.get("type")
        if update_type == "method_performance":
            name = payload["name"]
            duration = payload["duration_ms"]
            if name not in app_data["method_details"]:
                app_data["method_details"][name] = {"calls": 0, "total_duration_ms": 0.0, "total_tokens": 0}
            if name not in app_data["live_graphs"]:
                app_data["live_graphs"][name] = get_default_live_graph_data()
            app_data["method_details"][name]["calls"] += 1
            app_data["method_details"][name]["total_duration_ms"] += duration
            app_data["general_stats"]["total_calls"] += 1
            app_data["live_graphs"][name]['timestamps'].append(datetime.now())
            app_data["live_graphs"][name]['calls'].append(1)
            app_data["live_graphs"][name]['tokens'].append(0)
        elif update_type == "method_llm_usage":
            name = payload["name"]
            tokens = payload["tokens"]
            if name not in app_data["method_details"]:
                app_data["method_details"][name] = {"calls": 0, "total_duration_ms": 0.0, "total_tokens": 0}
            app_data["method_details"][name]["total_tokens"] += tokens["total"]
            app_data["llm_usage"]["prompt_tokens"] += tokens["prompt"]
            app_data["llm_usage"]["completion_tokens"] += tokens["completion"]
            app_data["llm_usage"]["total_tokens"] += tokens["total"]
            if name in app_data["live_graphs"] and len(app_data["live_graphs"][name]['tokens']) > 0:
                app_data["live_graphs"][name]['tokens'][-1] = tokens["total"]
        elif update_type == "interaction_time":
            app_data["general_stats"]["interaction_count"] += 1
            app_data["general_stats"]["total_interaction_time_ms"] += payload["duration_ms"]
        elif update_type == "quality_feedback":
            app_data["quality_rai"]["quality_scores"].append(payload["score"])
        elif update_type == "rai_alert":
            app_data["quality_rai"]["rai_alerts"].append(payload.get("alert"))
        elif update_type == "error":
            app_data["general_stats"]["errors"] += 1
        elif update_type == "session_end":
            app_data["session_ended"] = True
    return jsonify(success=True)

def create_metric_card(title, value_id):
    return dbc.Card(
        dbc.CardBody([
            html.H4(title, className="card-title"),
            html.H2("0", id=value_id, className="card-text fw-bold"),
        ]),
        className="text-center m-2",
        style={"border": "2px solid #444", "borderRadius": "15px"}
    )

app.layout = dbc.Container([
    dcc.Interval(id='interval-component', interval=1*1000, n_intervals=0),
    html.H1("💮 Kansatsu Dashboard", className="text-center my-4"),
    html.H3("💹 General Stats"),
    dbc.Row([
        dbc.Col(create_metric_card("Total Monitored Calls", "total-calls-value")),
        dbc.Col(create_metric_card("Total Errors", "total-errors-value")),
        dbc.Col(create_metric_card("Avg Interaction Time (ms)", "avg-interaction-time-value")),
    ]),
    html.Hr(),
    html.H3("🧠 LLM Usage"),
    dbc.Row([
        dbc.Col(create_metric_card("Prompt Tokens", "prompt-tokens-value")),
        dbc.Col(create_metric_card("Completion Tokens", "completion-tokens-value")),
        dbc.Col(create_metric_card("Total Tokens", "total-tokens-value")),
    ]),
    html.Hr(),
    html.H3("📜 Quality & Responsible AI"),
    dbc.Row([
        dbc.Col(create_metric_card("Average User Quality Score", "avg-quality-score-value")),
        dbc.Col(create_metric_card("PII/PHI AI Alerts", "rai-alerts-value")),
    ]),
    html.Div(
        dbc.Card(
            dbc.CardBody([
                html.H5("👺 PII/PHI Alert Details:", className="card-title text-danger"),
                html.Ul(id='rai-alert-details-list', className="mb-0")
            ], style={'maxHeight': '300px', 'overflowY': 'auto'}),
        ),
        id='rai-alert-details-card',
        style={'display': 'none'}
    ),
    html.Hr(),
    html.H3("🔴 Live Method Activity"),
    html.Div(id='live-graphs-container'),
    html.Hr(),
    html.H3("📋 Final Summary Table"),
    html.Div(id='final-table-container')
], fluid=True)

@app.callback(
    [
        Output('total-calls-value', 'children'),
        Output('total-errors-value', 'children'),
        Output('avg-interaction-time-value', 'children'),
        Output('prompt-tokens-value', 'children'),
        Output('completion-tokens-value', 'children'),
        Output('total-tokens-value', 'children'),
        Output('avg-quality-score-value', 'children'),
        Output('rai-alerts-value', 'children'),
        Output('live-graphs-container', 'children'),
        Output('final-table-container', 'children'),
        Output('rai-alert-details-card', 'style'),
        Output('rai-alert-details-list', 'children'),
    ],
    [Input('interval-component', 'n_intervals')]
)
def update_metrics(n):
    with data_lock:
        gs = app_data["general_stats"]
        llm = app_data["llm_usage"]
        qr = app_data["quality_rai"]
        avg_interaction_time = (gs["total_interaction_time_ms"] / gs["interaction_count"]) if gs["interaction_count"] > 0 else 0
        avg_quality_score = (sum(qr["quality_scores"]) / len(qr["quality_scores"])) if qr["quality_scores"] else 0
        graph_children = []
        for name, data in app_data["live_graphs"].items():
            fig = go.Figure()
            timestamps = list(data['timestamps'])
            fig.add_trace(go.Bar(x=timestamps, y=list(data['calls']), name='Calls', marker_color='cyan'))
            fig.add_trace(go.Bar(x=timestamps, y=list(data['tokens']), name='Tokens', marker_color='orange', yaxis='y2'))
            fig.update_layout(
                title=f'Activity for: {name}',
                template='plotly_dark',
                xaxis=dict(tickformat='%H:%M:%S'),
                yaxis=dict(title='Calls'),
                yaxis2=dict(title='Tokens', overlaying='y', side='right', range=[0, max(1, max(data['tokens'] or [1])) * 1.1]),
                barmode='group',
                legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
            )
            graph_children.append(dcc.Graph(figure=fig))
        table_children = []
        if app_data["session_ended"]:
            table_data = []
            for name, data in app_data["method_details"].items():
                calls = data['calls']
                avg_time = data['total_duration_ms'] / calls if calls > 0 else 0
                total_tokens = data.get('total_tokens', 0)
                avg_tokens = total_tokens / calls if calls > 0 else 0
                table_data.append({
                    'Method Name': name, 'Calls': calls, 'Avg Time (ms)': f"{avg_time:.2f}",
                    'Total Tokens': total_tokens, 'Avg Tokens': f"{avg_tokens:.0f}"
                })
            if table_data:
                table_data = sorted(table_data, key=lambda x: float(x['Avg Time (ms)']), reverse=True)
                table_children.append(dash_table.DataTable(
                    data=table_data,
                    columns=[{"name": i, "id": i} for i in table_data[0].keys()],
                    style_cell={'textAlign': 'left', 'backgroundColor': '#343a40', 'color': 'white'},
                    style_header={'fontWeight': 'bold', 'border': '1px solid pink'},
                    style_data={'border': '1px solid grey'},
                ))
        rai_alerts = qr.get("rai_alerts", [])
        rai_alert_count = len(rai_alerts)
        alert_list_items = []
        if rai_alert_count > 0:
            for alert in rai_alerts:
                if alert:
                    alert_list_items.append(
                        html.Li([
                            html.Strong(f"{alert.get('type', 'N/A')}: "),
                            html.Span(f"{alert.get('details', 'No details')}")
                        ], className="text-warning")
                    )
        card_style = {'display': 'block', 'marginTop': '15px'} if rai_alert_count > 0 else {'display': 'none'}
        return (
            f"{gs['total_calls']}", f"{gs['errors']}", f"{avg_interaction_time:.0f}",
            f"{llm['prompt_tokens']}", f"{llm['completion_tokens']}", f"{llm['total_tokens']}",
            f"{avg_quality_score:.2f}", f"{rai_alert_count}", graph_children, table_children,
            card_style, alert_list_items
        )

def main():
    parser = argparse.ArgumentParser(description="Run the Kansatsu Dashboard.", add_help = False)

    parser.add_argument("--version", action = "store_true", help = "Show the version number and exit")
    parser.add_argument("--help", action = "store_true", help = "Show the link to the README and exit")
    
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host IP to run the dashboard on.")
    parser.add_argument("--port", type=int, default=9999, help="Port to run the dashboard on.")
    args = parser.parse_args()

    if args.version:
        print(f"kansatsu version {__version__}")
        sys.exit(0)

    if args.help:
        print(f"💮 Visit https://github.com/AbhinavRMohan/kansatsu/blob/main/README.md to get started 💮")
        sys.exit(0)
    
    print(f"💮 Starting Kansatsu Dashboard at http://{args.host}:{args.port}\n\ncommands:\n* kansatsu-dashboard --version\nkansatsu-dashboard --help")
    app.run(host=args.host, port=args.port)

if __name__ == '__main__':
    main()
