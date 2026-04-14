from __future__ import annotations

import random
from datetime import datetime


OPENERS = [
    'A quiet moment from the wild.',
    'Nature always finds a way to calm the soul.',
    'Let this little escape slow your day down.',
    'A peaceful frame from nature for your feed.',
]

MIDDLES = [
    'Breathe in the stillness and let the noise fade away.',
    'Soft light, open skies, and the kind of peace we all need.',
    'A reminder that the most beautiful things are often the calmest.',
    'Saving this moment of calm and sharing it with you.',
]

CLOSERS = [
    'What kind of nature content would you love to see next?',
    'Take a pause, enjoy the view, and keep flowing gently.',
    'May your day feel a little softer after this.',
    'Here is your daily dose of calm from the natural world.',
]


def build_caption(theme: str, hashtags: list[str], query: str) -> str:
    date_label = datetime.now().strftime('%B %d, %Y')
    hashtag_text = ' '.join(f'#{tag.lstrip("#")}' for tag in hashtags)
    parts = [
        random.choice(OPENERS),
        f'{theme} inspired by {query} on {date_label}.',
        random.choice(MIDDLES),
        random.choice(CLOSERS),
        hashtag_text,
    ]
    return '\n\n'.join(parts)
