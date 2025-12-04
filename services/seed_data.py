
import csv, os
from .db import init_db, get_conn

CSV_PATH = os.environ.get('SCHEDULE_CSV', os.path.join(os.path.dirname(__file__), '..', 'data', 'schedule.sample.csv'))

def main():
    init_db()
    conn = get_conn()
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            conn.execute(
                "INSERT INTO schedule(user_id, course_name, day_of_week, start_time, end_time, location) VALUES (?,?,?,?,?,?)",
                (row['user_id'], row['course_name'], int(row['day_of_week']), row['start_time'], row['end_time'], row['location'])
            )
    conn.commit()
    conn.close()
    print('Seeded schedule from', CSV_PATH)

if __name__ == '__main__':
    main()
