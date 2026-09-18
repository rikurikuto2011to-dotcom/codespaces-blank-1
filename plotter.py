import plotly.graph_objects as go
import plotly.express as px

def create_figure(dataframes: dict, config):
    fig = go.Figure()
    palette = px.colors.qualitative.Plotly

    # 共通Y最小値（影用）
    if config.show_shadow:
        y_floor = min(df[config.y_col].min() for df in dataframes.values())

    for i, (name, df) in enumerate(dataframes.items()):
        df = df.dropna(subset=[config.x_col, config.y_col, config.z_col])

        # サンプリング
        if len(df) > config.max_points:
            df = df.sample(config.max_points, random_state=42)

        color = palette[i % len(palette)]

        if config.mode == "点":
            fig.add_trace(go.Scatter3d(
                x=df[config.x_col],
                y=df[config.y_col],
                z=df[config.z_col],
                mode="markers",
                marker=dict(size=3, color=color),
                name=name
            ))
        else:
            fig.add_trace(go.Scatter3d(
                x=df[config.x_col],
                y=df[config.y_col],
                z=df[config.z_col],
                mode="lines",
                line=dict(color=color, width=4),
                name=name
            ))

        # 影
        if config.show_shadow:
            fig.add_trace(go.Scatter3d(
                x=df[config.x_col],
                y=[y_floor] * len(df),
                z=df[config.z_col],
                mode="lines",
                line=dict(color="#999999", width=2, dash="dot"),
                showlegend=(i == 0),
                name="影"
            ))

    fig.update_layout(
        scene=dict(
            xaxis_title=config.x_col,
            yaxis_title=config.y_col,
            zaxis_title=config.z_col,
            aspectmode="data" if config.aspect else "auto"
        ),
        margin=dict(l=0, r=0, t=20, b=0)
    )

    return fig