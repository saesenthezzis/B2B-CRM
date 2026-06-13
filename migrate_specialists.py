import core
import glob
import pandas as pd
import os

def migrate():
    # Fetch old data directly
    path = None
    for d in (os.path.dirname(core.BASE), core.BASE):
        for pat in ("ЗоныОтвет*ности.xlsx", "Зоны*ответ*ности.xlsx"):
            hits = glob.glob(os.path.join(d, pat))
            if hits:
                path = hits[0]
                break
        if path:
            break
            
    out = []
    if path:
        try:
            df = pd.read_excel(path, sheet_name="Лист1")
            df.columns = [str(c).strip() for c in df.columns]
            spec_col = next((c for c in df.columns if "специалист" in c.lower()), None)
            city_col = next((c for c in df.columns if "город" in c.lower()), None)
            if spec_col and city_col:
                for _, r in df.iterrows():
                    name, city = core.clean_text(r.get(spec_col)), core.clean_text(r.get(city_col))
                    if name:
                        out.append({"name": name, "city": city})
        except Exception as e:
            print("Error parsing Excel:", e)

    if not out:
        print("No specialists found to migrate.")
        return

    # Add table to db
    con = core.db()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS specialists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            city TEXT
        );
    """)
    con.executescript("DELETE FROM specialists;")
    
    # Insert rows
    for row in out:
        con.execute("INSERT INTO specialists (name, city) VALUES (:name, :city)", row)
    
    print(f"Successfully migrated {len(out)} specialists to the database.")

if __name__ == "__main__":
    migrate()
