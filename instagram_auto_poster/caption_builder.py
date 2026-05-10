from __future__ import annotations

import random
import re


ENGAGEMENT = [
    "Follow for more content like this 🔥",
    "Save this if it made you smile! 😄",
    "Tag someone who would enjoy this 👇",
    "Double tap if you loved this! ❤️",
    "Share with someone who needs this today 🙌",
    "Hit follow so you never miss a post! 🎯",
]

CLOSERS = [
    "Comment your thoughts below! 💬",
    "What do you think? Let us know! 👇",
    "Like and follow for daily updates! 🎬",
    "Turn on notifications so you never miss a post!",
    "Follow for more amazing content every day!",
    "Drop a comment — we read every one! 🙌",
]


def _clean_title(title: str) -> str:
    """Strip YouTube-specific noise so the title works as an Instagram hook."""
    cleaned = re.sub(r'#\S+', '', title)                  # remove #shorts etc.
    cleaned = re.sub(r'\[.*?\]|\(.*?\)', '', cleaned)     # remove [channel] / (official)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # Capitalise first letter if not already
    return cleaned[0].upper() + cleaned[1:] if cleaned else cleaned


INSTAGRAM_MAX_CAPTION = 2_200


def build_caption_from_youtube(title: str, description: str, hashtags: list[str]) -> str:
    """Build caption from YouTube localized title + description + hashtags.

    Truncates description if the combined caption would exceed Instagram's
    2,200-character limit. Title and hashtags are never truncated.
    """
    hashtag_text = " ".join(f'#{tag.lstrip("#")}' for tag in hashtags)
    clean_title = _clean_title(title)
    clean_desc = description.strip()

    parts = [p for p in [clean_title, clean_desc, hashtag_text] if p]
    full = "\n\n".join(parts)

    if len(full) <= INSTAGRAM_MAX_CAPTION:
        return full

    # Separators between the three parts (title always present, hashtags always present)
    # title + \n\n + desc + \n\n + hashtags
    fixed_len = len(clean_title) + 2 + 2 + len(hashtag_text)  # 2+2 for two \n\n separators
    available = INSTAGRAM_MAX_CAPTION - fixed_len - 3  # 3 for trailing "..."

    if available <= 0 or not clean_desc:
        return "\n\n".join(p for p in [clean_title, hashtag_text] if p)

    truncated_desc = clean_desc[:available] + "..."
    return "\n\n".join(p for p in [clean_title, truncated_desc, hashtag_text] if p)


def build_caption(theme: str, hashtags: list[str], query: str, title: str = "") -> str:
    hashtag_text = ' '.join(f'#{tag.lstrip("#")}' for tag in hashtags)

    hook = _clean_title(title) if title.strip() else f'Amazing {theme} content you cannot miss!'

    parts = [
        hook,
        random.choice(ENGAGEMENT),
        random.choice(CLOSERS),
        hashtag_text,
    ]
    return '\n\n'.join(p for p in parts if p)
