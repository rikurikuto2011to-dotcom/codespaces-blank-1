import io
from pathlib import Path

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
    for name, df in dataframes.items():
        st.write(f"**{name}**")
        st.dataframe(df.head())
    st.stop()

# --- 4. データプレビュー（ファイルごとにタブ表示） -------------------------
        st.subheader("データレビュー")
        tabs = st.tabs(list(dataframes.keys()))
        for tab, (name, df) in zip(tabs, dataframes.items()):
            with tab:
                n_rows = len(df)
                max_idx = n_rows - 1
                start, end = st.slider(
                    "反映する行の範囲（0始まり）",
                    min_value=0, max_value=max_idx, value=(0, max_idx),
                    key=f"rowrange_{name}",
                )
                df = df.iloc[start:end + 1]
                st.dataframe(df.head(10), use_container_width=True)



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
with st.expander("ファイルごとに太さを調整する", expanded=(len(dataframes) <= 3)):
    for name in dataframes.keys():
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

for i, (name, df) in enumerate(dataframes.items()):
    plot_df = df.dropna(subset=[x_col, y_col, z_col])
    if plot_df.empty:
        continue
    color = palette[i % len(palette)]
    width = line_widths[name]

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

    if show_shadow:
        fig.add_trace(go.Scatter3d(
            x=plot_df[x_col],
            y=[y_floor] * len(plot_df),
            z=plot_df[z_col],
            mode="lines",
            line=dict(color="#999999", width=2, dash="dot"),
            name="地面への投影",
            legendgroup="shadow",
            showlegend=(i == 0),  # 影の凡例は1つだけ表示すれば十分
            hoverinfo="skip",  # 影は投影用の補助線なので、押しても実座標と紛らわしくないよう非表示
        ))

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

st.plotly_chart(fig, use_container_width=True)
st.caption(
    "グラフ上の点を押す（またはカーソルを合わせる）と、その点のX/Y/Z座標が表示されます。"
    "少し大きめの丸は各軌道の最高点です。"
)

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
