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
