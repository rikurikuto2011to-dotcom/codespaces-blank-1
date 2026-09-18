import pandas as pd

def enforce_numeric(df, cols):
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=cols)

def get_common_numeric_columns(dataframes: dict):
    numeric_sets = [
        set(df.select_dtypes(include="number").columns)
        for df in dataframes.values()
    ]
    return sorted(set.intersection(*numeric_sets))

def validate_min_columns(cols, min_cols=3):
    if len(cols) < min_cols:
        raise ValueError("共通の数値列が不足しています（3列以上必要）")