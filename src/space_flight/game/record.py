from datetime import datetime
from pathlib import Path

import pandas as pd


class Record:
    def __init__(self):
        # Filesystem-safe timestamp: the default datetime str contains ":" which
        # is an illegal character in Windows paths (drive / alternate-data-stream
        # separator), so writing the parquet would fail with OSError 22.
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.filepath = (
            Path(__file__).parent.parent.parent.parent
            / "target"
            / f"{timestamp}_record.parquet"
        )
        self.data = []

    def new_time(self, time: float):
        self.data.append({"time_s": time})

    def record(self, variable_name: str, variable: float | int | bool | str):
        self.data[-1][variable_name] = variable

    def save(self):
        data_df = pd.DataFrame(self.data)
        data_df.to_parquet(self.filepath)
