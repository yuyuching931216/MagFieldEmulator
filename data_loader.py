import pandas as pd
import traceback
from typing import Optional

class DataLoader:
    @staticmethod
    def load_data(file_path: str) -> Optional[pd.DataFrame]:
        try:
            print(f"載入磁場資料中: {file_path}...")
            df = pd.read_csv(file_path, delim_whitespace=True, skiprows=3)
            
            if len(df.columns) < 4:
                raise ValueError("數據文件需要至少4列 (時間, Bx, By, Bz)")
                
            df = df.rename(columns={
                df.columns[0]: 'Time',
                df.columns[1]: 'Bx',
                df.columns[2]: 'By',
                df.columns[3]: 'Bz'
            })
            print(f"資料筆數：{len(df)}")
            return df
        except pd.errors.EmptyDataError:
            print("錯誤：數據文件為空")
        except FileNotFoundError:
            print(f"錯誤：找不到文件 {file_path}")
        except Exception as e:
            print(f"載入資料時發生錯誤: {e}")
            traceback.print_exc()
        return None
