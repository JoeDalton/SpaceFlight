from datetime import datetime
from pathlib import Path

import pandas as pd


class Record:
    def __init__(self):
        self.filepath = (
            Path(__file__).parent.parent.parent.parent
            / "target"
            / f"{datetime.now()}_record.parquet"
        )
        self.data = []

    def new_time(self, time: float):
        self.data.append({"time_s": time})

    def record(self, variable_name: str, variable: float | int | bool | str):
        self.data[-1][variable_name] = variable

    def save(self):
        data_df = pd.DataFrame(self.data)
        data_df.to_parquet(self.filepath)
