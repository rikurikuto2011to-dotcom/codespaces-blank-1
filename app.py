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
    # 線の太さを調整するスライダー（1〜10の間で選べる、初期値は4）
    line_width = st.slider("線の太さ", min_value=1, max_value=10, value=4)


def load_dataframe(file, orientation: str, sheet_name=0) -> pd.DataFrame:
    """アップロードされた1ファイル(CSV/Excel)を、1行=1点のデータフレームに整形する。"""
    is_excel = file.name.lower().endswith((".xlsx", ".xls"))
    file.seek(0)

    def reader(**kwargs):
        file.seek(0)
        if is_excel:
            return pd.read_excel(file, sheet_name=sheet_name, **kwargs)
        return pd.read_csv(file, **kwargs)

    if orientation.startswith("転置"):
        # 1列目(ラベル: 例 X,Y,Z)をインデックスにしてから転置する。
        df = reader(header=None, index_col=0).T.reset_index(drop=True)
        df.columns.name = None
        # Excelシートの空行(ラベルなし)が転置後にNaN列名として残るので除外する。
        df = df.loc[:, df.columns.notna()]
    else:
        df = reader(header=0)
    return df


# --- 3. 全ファイルを読み込む（Excelは複数シートがあればシートも選択） -----------
dataframes = {}
for f in uploaded_files:
    sheet_name = 0
    if f.name.lower().endswith((".xlsx", ".xls")):
        f.seek(0)
        sheet_names = pd.ExcelFile(f).sheet_names
        if len(sheet_names) > 1:
            sheet_name = st.selectbox(
                f"「{f.name}」のシートを選択", sheet_names, key=f"sheet_{f.name}"
            )
        else:
            sheet_name = sheet_names[0]
    try:
        dataframes[f.name] = load_dataframe(f, orientation, sheet_name)
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
st.subheader("データプレビュー")
tabs = st.tabs(list(dataframes.keys()))
for tab, (name, df) in zip(tabs, dataframes.items()):
    with tab:
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

# --- 6. 3Dグラフの作成（ファイルごとに色分けして重ね描き） -------------------
palette = px.colors.qualitative.Plotly  # ファイルごとの色を自動で割り当てる
fig = go.Figure()

# 影を落とす高さ(床)を、全ファイル共通のY最小値に揃える。
# こうすることで、複数の軌道の影が同じ高さに揃い、上から見た形を比較しやすくなる。
if show_shadow:
    y_floor = min(df[y_col].min() for df in dataframes.values())

for i, (name, df) in enumerate(dataframes.items()):
    plot_df = df.dropna(subset=[x_col, y_col, z_col])
    color = palette[i % len(palette)]

    trace_kwargs = dict(
        x=plot_df[x_col], y=plot_df[y_col], z=plot_df[z_col], name=name,
    )
    if mode.startswith("点"):
        trace_kwargs["mode"] = "markers"
        trace_kwargs["marker"] = dict(size=3, color=color)
    else:
        trace_kwargs["mode"] = "lines"
        trace_kwargs["line"] = dict(color=color, width=line_width)
    # --- [追加機能] タップ・長押ししている間だけ、その点の詳細な3次元座標を浮かび上がらせる ---
    trace_kwargs["hoverinfo"] = "text"
    trace_kwargs["hovertemplate"] = (
        f"<b>📁 ファイル: {name}</b><br>"
        f"📍 位置: %{{currentpoint.index}}点目<br>"
        f"────────────────<br>"
        f"🔴 {x_col} (X軸): %{{x:<.4f}}<br>"
        f"🟢 {y_col} (Y軸): %{{y:<.4f}}<br>"
        f"🔵 {z_col} (Z軸): %{{z:<.4f}}<extra></extra>"
    )

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
        ))
    # --- [追加機能] 各ファイルの最高点（Yが最大）を強調表示する ---
    if not plot_df.empty:
        # Y軸（y_col）の値が最大の行（インデックス）を見つける
        max_y_idx = plot_df[y_col].idxmax()
        max_point = plot_df.loc[max_y_idx]

        # 最高点だけに目立つマーカーを重ねて描画する
        fig.add_trace(go.Scatter3d(
            x=[max_point[x_col]],
            y=[max_point[y_col]],
            z=[max_point[z_col]],
            mode="markers",
            marker=dict(
                size=8,               # 通常の点（サイズ3）より大幅に大きく
                color=color,          # 同じファイルの色に合わせる
                symbol="square",     # ダイヤ型にする（"circle" や "square" でも可）
                line=dict(color="black", width=2) # 黒いフチを付けて目立たせる
            ),
            name=f"最高点 ({name})",
            hovertemplate=(
                f"<b>最高点 ({name})</b><br>"
                f"{x_col}: %{{x}}<br>"
                f"{y_col}: %{{y}} (MAX)<br>"
                f"{z_col}: %{{z}}<extra></extra>"
            ),
            legendgroup=f"max_{name}",
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
)

st.plotly_chart(fig, use_container_width=True)

# --- 7. HTMLとして書き出し ---------------------------------------------------
html_bytes = fig.to_html(include_plotlyjs="cdn").encode("utf-8")
st.download_button(
    "グラフをHTMLファイルとしてダウンロード",
    data=html_bytes,
    file_name="3d_scatter_overlay.html",
    mime="text/html",
)
