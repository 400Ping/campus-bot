
from datetime import datetime
from .notes_service import get_notes_for_date
from .summarize_service import build_review_pack

def generate_review_for_date(user_id, date_obj: datetime):
    notes = get_notes_for_date(user_id, date_obj)
    return build_review_pack(notes)
