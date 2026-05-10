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


_URL_RE = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)


def _strip_urls(text: str) -> str:
    return re.sub(r'\s*' + _URL_RE.pattern, '', text, flags=re.IGNORECASE).strip()


def _clean_title(title: str) -> str:
    """Strip YouTube-specific noise so the title works as an Instagram hook."""
    cleaned = _strip_urls(title)
    cleaned = re.sub(r'#\S+', '', cleaned)                # remove #shorts etc.
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
    hashtag_text = " ".join(f'#{tag.lstrip("#")}' for tag in hashtags if tag.strip())
    if not hashtag_text:
        raise ValueError(
            "DEFAULT_HASHTAGS is empty — set it in your environment variables "
            "(e.g. DEFAULT_HASHTAGS=#reels,#shorts,#viral)"
        )

    clean_title = _clean_title(title)
    clean_desc = _strip_urls(description.strip())

    # Build full caption: title + description + hashtags (each separated by blank line)
    body_parts = [p for p in [clean_title, clean_desc] if p]
    body = "\n\n".join(body_parts)
    full = f"{body}\n\n{hashtag_text}" if body else hashtag_text

    if len(full) <= INSTAGRAM_MAX_CAPTION:
        return full

    # Truncate description to fit within limit; title and hashtags are never cut
    # Structure: body_fixed + "\n\n" + truncated_desc + "..." + "\n\n" + hashtags
    # body_fixed = clean_title + "\n\n" (if title present), else ""
    title_part = f"{clean_title}\n\n" if clean_title else ""
    fixed_len = len(title_part) + 2 + len(hashtag_text)  # 2 for final \n\n before hashtags
    available = INSTAGRAM_MAX_CAPTION - fixed_len - 3     # 3 for "..."

    if available <= 0 or not clean_desc:
        # No room for description; return title + hashtags only
        return f"{title_part.rstrip()}\n\n{hashtag_text}" if clean_title else hashtag_text

    truncated_desc = clean_desc[:available] + "..."
    return f"{title_part}{truncated_desc}\n\n{hashtag_text}"


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
