import io
from pathlib import Path
import numpy as np

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Apple Numbers等からxlsxに書き出したファイルは、フォント情報(family属性)が
# 規格の範囲(0-14)を超えた値で保存されていることがあり、その場合openpyxlが
# 「スタイルシートを読み込めません」というエラーで停止してしまう。
# 実際のデータには影響しない見た目上の情報なので、上限値を緩めて回避する。
import openpyxl.styles.fonts as _openpyxl_fonts
_openpyxl_fonts.Font.family.max = 255

st.set_page_config(page_title="3D散布図ビューア", layout="wide")
st.title("📊 CSV/Excelアップロード → 3D散布図（複数ファイル重ね合わせ対応）")
st.caption(
    "複数のCSVまたはExcelファイルをアップロードすると、色分けして同じ3D空間に重ねて表示します。"
)

# --- 0. データ入力用テンプレートのダウンロードリンク ---------------------------
# app.pyと同じフォルダに template.xlsx を置いておくと、ここからすぐ配布できる。
TEMPLATE_PATH = Path(__file__).parent / "template.xlsx"
if TEMPLATE_PATH.exists():
    st.download_button(
        "📥 データ入力用Excelテンプレートをダウンロード",
        data=TEMPLATE_PATH.read_bytes(),
        file_name="rocket_trajectory_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    st.caption(
        "（テンプレートを配布する場合は、app.pyと同じフォルダに`template.xlsx`という"
        "名前でExcelファイルを置いてください。ここにダウンロードボタンが表示されます。）"
    )


# --- 1. ファイルアップロード（複数可、CSV/Excel対応） ------------------------
uploaded_files = st.file_uploader(
    "ファイルを選択（CSVまたはExcel、複数選択可）",
    type=["csv", "xlsx", "xls"],
    accept_multiple_files=True,
)

if not uploaded_files:
    st.info("👆 CSVまたはExcelファイルをアップロードしてください（複数選択できます）。")
    st.stop()

# --- 2. 読み込み・表示設定 -------------------------------------------------
# 「ヘッダーあり」と「転置」を1つのラジオボタンにまとめ、
# 両方チェックした場合にデータが壊れる組み合わせを作れないようにしている。
with st.sidebar:
    st.header("読み込み設定")
    orientation = st.radio(
        "データの形式（すべてのファイルに共通で適用）",
        ["通常（1行目=列名、各列が1つの変数）", "転置（1列目=ラベル、各行が1つの変数）"],
        index=1,
        help="転置形式の例:  \nX,0,0.21,0.42,...  \nY,0,0.21,0.42,...  \nZ,0,0,0.0006,...",
    )

    st.header("表示設定")
    mode = st.radio("表示スタイル", ["点のみ (散布図)", "線でつなぐ (軌跡)"], index=1)
    aspect = st.checkbox("X/Y/Zの比率を実際の値通りに保つ", value=True)
    show_shadow = st.checkbox(
        "地面への影(グレーの破線)を表示する", value=True,
        help="Y軸の値を全軌道の最小値に揃えて投影することで、"
             "上から見たときのX-Z平面上の曲がり方（Z軸方向のずれ）を見やすくします。",
    )
    show_apex = st.checkbox("最高点を丸で強調表示する", value=True)
    st.header("アニメーション")
    animate = st.checkbox(
        "軌道を伸ばしながら再生する", value=False,
        help="「線でつなぐ」モードのときだけ有効です。",
    )
    n_frames = st.slider("アニメーションのコマ数", min_value=10, max_value=100, value=40) if animate else 40


def load_dataframe(file_bytes: bytes, file_name: str, orientation: str, sheet_name=0) -> pd.DataFrame:
    """アップロードされた1ファイル(CSV/Excel)を、1行=1点のデータフレームに整形する。"""
    is_excel = file_name.lower().endswith((".xlsx", ".xls"))
    buf = io.BytesIO(file_bytes)

    def reader(**kwargs):
        buf.seek(0)
        if is_excel:
            return pd.read_excel(buf, sheet_name=sheet_name, **kwargs)
        return pd.read_csv(buf, **kwargs)

    if orientation.startswith("転置"):
        # 1列目(ラベル: 例 X,Y,Z)をインデックスにしてから転置する。
        df = reader(header=None, index_col=0).T.reset_index(drop=True)
        df.columns.name = None
        # Excelシートの空行(ラベルなし)が転置後にNaN列名として残るので除外する。
        df = df.loc[:, df.columns.notna()]
    else:
        df = reader(header=0)
    return df


# ウィジェットを1つ動かすたびにStreamlitはスクリプト全体を再実行するため、
# キャッシュがないと同じファイルを毎回読み直すことになり、Community Cloudの
# メモリ上限(無料枠は1GB)を圧迫しやすい。@st.cache_dataで
# 「同じ中身のファイル・同じ設定」の組み合わせは結果を使い回すようにする。
load_dataframe_cached = st.cache_data(show_spinner="ファイルを読み込み中...")(load_dataframe)


# --- 3. 全ファイルを読み込む（Excelは複数シートがあればシートも選択） -----------
dataframes = {}
for f in uploaded_files:
    file_bytes = f.getvalue()
    sheet_name = 0
    if f.name.lower().endswith((".xlsx", ".xls")):
        sheet_names = pd.ExcelFile(io.BytesIO(file_bytes)).sheet_names
        if len(sheet_names) > 1:
            sheet_name = st.selectbox(
                f"「{f.name}」のシートを選択", sheet_names, key=f"sheet_{f.name}"
            )
        else:
            sheet_name = sheet_names[0]
    try:
        dataframes[f.name] = load_dataframe_cached(file_bytes, f.name, orientation, sheet_name)
    except Exception as e:
        st.error(f"「{f.name}」の読み込みに失敗しました: {e}")
        st.stop()

# 全ファイルに共通して存在する数値列だけを軸の候補にする
# (ファイルによって列構成が違う場合、共通部分だけがX/Y/Z候補になる)
numeric_col_sets = [
    set(df.select_dtypes(include="number").columns) for df in dataframes.values()
]
common_numeric_cols = sorted(set.intersection(*numeric_col_sets))

if len(common_numeric_cols) < 3:
    st.error(
        "全ファイルに共通する数値列が3つ未満です。"
        "読み込み設定や、各ファイルの列名・列数を確認してください。"
    )
# --- 4. データプレビュー（ファイルごとにタブ表示） -------------------------
st.subheader("データプレビュー")
tabs = st.tabs(list(dataframes.keys()))
for tab, (name, df) in zip(tabs, dataframes.items()):
    with tab:
        n_rows = len(df)
        max_idx = max(n_rows - 1, 0)
        start, end = st.slider(
            "反映する行の範囲（0始まり）",
            min_value=0, max_value=max_idx, value=(0, max_idx),
            key=f"rowrange_{name}",
        )
        dataframes[name] = df.iloc[start:end + 1]
        st.dataframe(dataframes[name].head(10), use_container_width=True)

# --- 5. 軸の選択 ------------------------------------------------------------
st.subheader("グラフ設定")
col1, col2, col3 = st.columns(3)
with col1:
    x_col = st.selectbox("X軸", common_numeric_cols, index=0)
with col2:
    y_col = st.selectbox("Y軸", common_numeric_cols, index=min(1, len(common_numeric_cols) - 1))
with col3:
    z_col = st.selectbox("Z軸", common_numeric_cols, index=min(2, len(common_numeric_cols) - 1))

# --- 5b. ファイルごとの線の太さ／点の大きさ ----------------------------------
st.subheader("ファイルごとの表示設定")
line_widths = {}
visible = {}
with st.expander("ファイルごとに太さを調整する", expanded=(len(dataframes) <= 3)):
    for name in dataframes.keys():
        visible[name] = st.checkbox("グラフに表示する", value=True, key=f"visible_{name}")
        line_widths[name] = st.slider(
            f"「{name}」の太さ", min_value=1, max_value=14, value=4, key=f"width_{name}"
        )


# --- 6. 3Dグラフの作成（ファイルごとに色分けして重ね描き） -------------------
palette = px.colors.qualitative.Plotly  # ファイルごとの色を自動で割り当てる
fig = go.Figure()

# 影を落とす高さ(床)を、全ファイル共通のY最小値に揃える。
# こうすることで、複数の軌道の影が同じ高さに揃い、上から見た形を比較しやすくなる。
if show_shadow:
    y_floor = min(df[y_col].min() for df in dataframes.values())
summary_rows = []
shadow_legend_shown = False
plot_dfs = {}
anim_targets = []

for i, (name, df) in enumerate(dataframes.items()):
    if not visible.get(name, True):
        continue
    plot_df = df.dropna(subset=[x_col, y_col, z_col])
    plot_dfs[name] = plot_df

    color = palette[i % len(palette)]
    width = line_widths[name]
    summary_rows.append({
        "ファイル": name,
        "点数": len(plot_df),
        f"{x_col} 最小〜最大": f"{plot_df[x_col].min():.3g} 〜 {plot_df[x_col].max():.3g}",
        f"{y_col} 最小〜最大": f"{plot_df[y_col].min():.3g} 〜 {plot_df[y_col].max():.3g}",
        f"{z_col} 最小〜最大": f"{plot_df[z_col].min():.3g} 〜 {plot_df[z_col].max():.3g}",
    })

    # 軸ラベルを埋め込んだホバー表示。押す(タップする)/カーソルを合わせると、
    # その点のX/Y/Z座標がこの書式で表示される。指を離す・カーソルを外すと消える。
    hovertemplate = (
        f"{x_col}: %{{x:.4f}}<br>{y_col}: %{{y:.4f}}<br>{z_col}: %{{z:.4f}}"
        f"<extra>{name}</extra>"
    )

    trace_kwargs = dict(
        x=plot_df[x_col], y=plot_df[y_col], z=plot_df[z_col], name=name,
        hovertemplate=hovertemplate,
    )
    if mode.startswith("点"):
        trace_kwargs["mode"] = "markers"
        trace_kwargs["marker"] = dict(size=width, color=color)
    else:
        # lines単体だと、線上のどこでも同じ扱いになり座標が拾いにくいことがあるため、
        # 小さな点(marker)を線の上に重ねて、各データ点ごとに正確に反応するようにする。
        trace_kwargs["mode"] = "lines+markers"
        trace_kwargs["line"] = dict(color=color, width=width)
        trace_kwargs["marker"] = dict(size=max(2, width * 0.4), color=color)

    fig.add_trace(go.Scatter3d(**trace_kwargs))
    main_idx = len(fig.data) - 1
    shadow_idx = None

    if show_shadow:
        fig.add_trace(go.Scatter3d(
            x=plot_df[x_col],
            y=[y_floor] * len(plot_df),
            z=plot_df[z_col],
            mode="lines",
            line=dict(color="#999999", width=2, dash="dot"),
            name="地面への投影",
            legendgroup="shadow",
            showlegend=(not shadow_legend_shown),# 影の凡例は1つだけ表示すれば十分
            hoverinfo="skip",  # 影は投影用の補助線なので、押しても実座標と紛らわしくないよう非表示
        ))
        shadow_legend_shown = True
        shadow_idx = len(fig.data) - 1
    if animate and not mode.startswith("点"):
        anim_targets.append((main_idx, shadow_idx, plot_df))

    if show_apex:
        apex_idx = plot_df[y_col].idxmax()
        apex_x = plot_df.loc[apex_idx, x_col]
        apex_y = plot_df.loc[apex_idx, y_col]
        apex_z = plot_df.loc[apex_idx, z_col]
        fig.add_trace(go.Scatter3d(
            x=[apex_x], y=[apex_y], z=[apex_z],
            mode="markers",
            marker=dict(size=9, color=color, line=dict(color="white", width=1)),
            name=f"{name} 最高点",
            showlegend=False,
            hovertemplate=(
                f"最高点<br>{x_col}: %{{x:.4f}}<br>{y_col}: %{{y:.4f}}<br>{z_col}: %{{z:.4f}}"
                f"<extra>{name}</extra>"
            ),
        ))

fig.update_layout(
    scene=dict(
        xaxis_title=x_col,
        yaxis_title=y_col,
        zaxis_title=z_col,
        aspectmode="data" if aspect else "auto",
    ),
    legend=dict(orientation="h", y=-0.05),
    margin=dict(l=0, r=0, t=10, b=0),
    hovermode="closest",
)
if animate and anim_targets:
    frames = []
    for k in range(1, n_frames + 1):
        frac = k / n_frames
        frame_data = []
        frame_traces = []
        for main_idx, shadow_idx, pdf in anim_targets:
            count = max(1, round(frac * len(pdf)))
            sub = pdf.iloc[:count]
            frame_data.append(go.Scatter3d(x=sub[x_col], y=sub[y_col], z=sub[z_col]))
            frame_traces.append(main_idx)
            if shadow_idx is not None:
                frame_data.append(go.Scatter3d(x=sub[x_col], y=[y_floor] * len(sub), z=sub[z_col]))
                frame_traces.append(shadow_idx)
        frames.append(go.Frame(data=frame_data, traces=frame_traces, name=str(k)))
    fig.frames = frames
    fig.update_layout(
        updatemenus=[dict(
            type="buttons", showactive=False, x=0.0, y=1.08, xanchor="left", yanchor="top",
            buttons=[
                dict(label="▶ 再生", method="animate", args=[None, dict(
                    frame=dict(duration=80, redraw=True), fromcurrent=True, transition=dict(duration=0),
                )]),
                dict(label="⏸ 一時停止", method="animate", args=[[None], dict(
                    frame=dict(duration=0, redraw=False), mode="immediate", transition=dict(duration=0),
                )]),
            ],
        )],
        sliders=[dict(
            x=0.1, y=-0.12, len=0.85,
            steps=[dict(
                method="animate", label=str(k),
                args=[[str(k)], dict(mode="immediate", frame=dict(duration=0, redraw=True))],
            ) for k in range(1, n_frames + 1)],
        )],
    )


st.plotly_chart(fig, use_container_width=True)
st.caption(
    "グラフ上の点を押す（またはカーソルを合わせる）と、その点のX/Y/Z座標が表示されます。"
    "少し大きめの丸は各軌道の最高点です。"
)
if animate and not anim_targets:
    st.caption("※ アニメーションは「線でつなぐ」モードで、表示中のファイルがあるときだけ再生できます。")

st.subheader("軌道の要約")
if summary_rows:
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
else:
    st.caption("表示中のファイルがありません。上の「表示する」チェックを確認してください。")
st.subheader("理論値と実測値の誤差")
if len(plot_dfs) < 2:
    st.caption("誤差を計算するには、2つ以上のファイルを表示する必要があります。")
else:
    compare_enabled = st.checkbox("誤差を計算する", value=False, key="compare_enabled")
    if compare_enabled:
        file_names = list(plot_dfs.keys())
        ref_name = st.selectbox(
            "基準にするファイル（理論値・シミュレーション側）", file_names, key="ref_name",
        )
        # np.interpはxpが単調増加である必要があるため、念のためXでソートしておく。
        ref_sorted = plot_dfs[ref_name].sort_values(x_col)
        ref_x = ref_sorted[x_col].to_numpy()
        ref_y = ref_sorted[y_col].to_numpy()
        ref_z = ref_sorted[z_col].to_numpy()

        error_rows = []
        error_charts = {}
        total_out_of_range = 0
        for name, pdf in plot_dfs.items():
            if name == ref_name:
                continue
            xv = pdf[x_col].to_numpy()
            yv = pdf[y_col].to_numpy()
            zv = pdf[z_col].to_numpy()

            y_interp = np.interp(xv, ref_x, ref_y)
            z_interp = np.interp(xv, ref_x, ref_z)
            dists = pd.Series(
                np.sqrt((yv - y_interp) ** 2 + (zv - z_interp) ** 2), name="誤差",
            )

            out_of_range = int(((xv < ref_x.min()) | (xv > ref_x.max())).sum())
            total_out_of_range += out_of_range

            error_rows.append({
                "ファイル": name,
                "基準": ref_name,
                "平均誤差": f"{dists.mean():.4g}",
                "最大誤差": f"{dists.max():.4g}",
                f"{x_col}が基準の範囲外だった点": out_of_range,
            })
            error_charts[name] = dists.reset_index(drop=True)

        if error_rows:
            st.dataframe(pd.DataFrame(error_rows), use_container_width=True, hide_index=True)
            st.caption(
                f"誤差は、実測側の各点の{x_col}に合わせて基準（{ref_name}）側を線形補間し、"
                f"同じ{x_col}地点における{y_col}・{z_col}の差から計算した距離です。"
            )
            if total_out_of_range > 0:
                st.caption(
                    f"⚠️ {x_col}が基準の範囲外だった点が{total_out_of_range}件ありました。"
                    "これらは基準の端の値を使って計算しているため、誤差が実態より"
                    "小さく/大きく出ている可能性があります。"
                )
            for name, series in error_charts.items():
                st.caption(f"「{name}」の誤差の推移（点の順番ごと）")
                st.line_chart(series)
        else:
            st.caption("基準以外に表示中のファイルがありません。")




# --- 7. HTMLとして書き出し ---------------------------------------------------
html_bytes = fig.to_html(include_plotlyjs="cdn").encode("utf-8")
st.download_button(
    "グラフをHTMLファイルとしてダウンロード",
    data=html_bytes,
    file_name="3d_scatter_overlay.html",
    mime="text/html",
)
st.caption(
    "※ ダウンロードした際に0KBの空ファイルになる場合は、"
    "サイトとの接続が一時的に切れている状態です。"
    "ページを再読み込みしてからもう一度お試しください。"
)
