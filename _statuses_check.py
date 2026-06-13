# -*- coding: utf-8 -*-
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
con = sqlite3.connect(r"В2В проект\rmko\rmko.db")
print("Комбинации флагов (deleted, posted, reserved) -> кол-во:")
for row in con.execute(
        "SELECT deleted, posted, reserved, COUNT(*) FROM deals "
        "GROUP BY deleted, posted, reserved ORDER BY 4 DESC"):
    print(f"  deleted={row[0]} posted={row[1]} reserved={row[2]}  ->  {row[3]}")
