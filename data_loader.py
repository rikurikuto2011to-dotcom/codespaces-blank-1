import pandas as pd

def load_file(file, orientation: str, sheet_name=0):
    is_excel = file.name.lower().endswith((".xlsx", ".xls"))
    file.seek(0)

    def reader(**kwargs):
        file.seek(0)
        if is_excel:
            return pd.read_excel(file, sheet_name=sheet_name, **kwargs)
        return pd.read_csv(file, **kwargs)

    if orientation.startswith("転置"):
        df = reader(header=None, index_col=0).T.reset_index(drop=True)
        df.columns.name = None
        df = df.loc[:, df.columns.notna()]
    else:
        df = reader(header=0)

    return df