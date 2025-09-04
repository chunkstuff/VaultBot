from logging import log
import re
import secrets
import string
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_.]{3,32}$")

def is_valid_username(name: str) -> bool:
    return bool(USERNAME_REGEX.fullmatch(name))

EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w{2,}$")

def is_valid_email(email: str) -> bool:
    return bool(EMAIL_REGEX.fullmatch(email.strip()))

def generate_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits
    password = ''.join(secrets.choice(chars) for _ in range(length))
    logger.debug(f"Generated password: {password}")
    return password


## MAKEMEWORSE MATCHING FUNCTIONS
def normalize_label(label):
    return re.sub(r"[^\w\s]", "", label).lower()

def find_best_match(user_input, choices):
    norm_input = normalize_label(user_input)
    matches = [
        (name, normalize_label(name).find(norm_input))
        for name in choices
        if norm_input in normalize_label(name)
    ]
    matches.sort(key=lambda x: (x[1], x[0]))
    return matches[0][0] if matches else None

def match_multiple(inputs, choices, limit=3):
    results = []
    for raw in inputs:
        if raw and raw.strip():
            match = find_best_match(raw.strip(), choices)
            if match:
                results.append(match)
        if len(results) == limit:
            break
    return results

def unmatched_inputs(inputs, choices, limit=3):
    unmatched = []
    for raw in inputs:
        if raw and raw.strip():
            match = find_best_match(raw.strip(), choices)
            if not match:
                unmatched.append(raw.strip())
        if len(unmatched) == limit:
            break
    return unmatched

def match_tags_from_comma_delimited(tags_input, tags_list, limit=3):
    """
    Parse comma-delimited tags and match them against the tags_list
    Returns tuple of (matched_tags, unmatched_tags)
    """
    if not tags_input or not tags_input.strip():
        return [], []
    
    # Split by comma and clean up
    tag_inputs = [tag.strip() for tag in tags_input.split(",") if tag.strip()]
    logger.info(f'[match_tags] Provided tags: {tags_input}')
    
    # Use the existing matching logic
    matched_tags = match_multiple(tag_inputs, tags_list, limit)
    unmatched_tags = unmatched_inputs(tag_inputs, tags_list, limit)
    
    return matched_tags, unmatched_tags