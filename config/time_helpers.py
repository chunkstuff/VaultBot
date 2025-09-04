# config/time_helpers.py

def format_ticks(t: int) -> str:
    sec = t // 10_000_000
    return f"{sec//3600:02}:{(sec%3600)//60:02}:{sec%60:02}"