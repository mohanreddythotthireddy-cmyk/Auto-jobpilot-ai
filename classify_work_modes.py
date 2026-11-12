from config import DB_PATH
from db import connect, init_db
from work_mode import classify_work_mode

def main():
    init_db()
    counts = {}
    with connect() as con:
        rows = con.execute("SELECT id,title,location,description FROM jobs").fetchall()
        for row in rows:
            mode = classify_work_mode(dict(row))
            con.execute("UPDATE jobs SET work_mode=? WHERE id=?", (mode, row["id"]))
            counts[mode] = counts.get(mode, 0) + 1
    print(f"Classified {sum(counts.values())} existing jobs without changing their statuses or application records.")
    for mode, count in sorted(counts.items()):
        print(f"{mode}: {count}")

if __name__ == "__main__":
    main()
