"""
Music playlist discovered from folders - no database, no JSON file to edit.

Every sub-folder of  portfolio_app/static/assets/music/  is one category ("mood") in the player:

    music/calm/        01_Morning_Light.mp3  02_Slow_River.mp3
    music/energetic/   01_Drive.mp3
    music/flute/       01_Bamboo_Dawn.mp3

Add a folder and it becomes a new category button; add a file and it becomes a track. The names do the rest:
  - Folder "02_energetic" -> category "Energetic". A number prefix only controls the order of the categories.
  - File "01_Tum_Hi_Ho.mp3" -> track "Tum Hi Ho". A number prefix only controls the order of the tracks.
Folders and files starting with "." are ignored, and so are folder names with spaces or odd characters
(use letters, numbers, "_" and "-").
"""
import logging
import re
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

AUDIO_EXTS = {'.mp3', '.m4a', '.ogg', '.wav'}
FOLDER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$')
MAX_CATEGORIES = 12
MAX_PER_CATEGORY = 60
CACHE_KEY = 'chatbot:music:v2'
CACHE_SECONDS = 300


def music_root():
    return Path(__file__).resolve().parent.parent / 'static' / 'assets' / 'music'


def title_from_filename(stem):
    title = re.sub(r'^\s*\d+\s*[-_.)]+\s*', '', stem)      # "01 - ", "02_", "3. " prefixes
    title = re.sub(r'[_\s]+', ' ', title).strip(' -')
    return (title or stem)[:80]


def label_from_folder(name):
    label = re.sub(r'^\d+[\s_.-]*', '', name)               # "02_energetic" -> "energetic"
    label = re.sub(r'[_\s]+', ' ', label).strip(' -') or name
    return label[:1].upper() + label[1:]


def _url(folder, filename):
    rel = f'assets/music/{folder}/{filename}'
    try:
        from django.templatetags.static import static
        return static(rel)
    except Exception:  # noqa: BLE001 - e.g. a manifest storage without this file
        return f"{settings.STATIC_URL}assets/music/{folder}/{quote(filename)}"


def _scan():
    root = music_root()
    if not root.is_dir():
        return []
    folders = sorted((d for d in root.iterdir()
                      if d.is_dir() and not d.is_symlink() and FOLDER_RE.match(d.name)),
                     key=lambda d: d.name.lower())[:MAX_CATEGORIES]
    tracks = []
    for folder in folders:
        files = sorted(
            (f for f in folder.iterdir()
             if f.is_file() and not f.is_symlink() and not f.name.startswith('.')
             and f.suffix.lower() in AUDIO_EXTS),
            key=lambda f: f.name.lower())
        label = label_from_folder(folder.name)
        for f in files[:MAX_PER_CATEGORY]:
            # "lang" is the category id (the folder name); the field keeps its old name for the player.
            tracks.append({'id': f'{folder.name}/{f.name}', 'lang': folder.name, 'label': label,
                           'title': title_from_filename(f.stem), 'url': _url(folder.name, f.name)})
    return tracks


def playlist():
    """List of {'id','lang','label','title','url'}. Never raises. Categories with no audio files are left out."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    try:
        tracks = _scan()
    except OSError:
        logger.exception('Chatbot music: could not read the music folder')
        return []
    cache.set(CACHE_KEY, tracks, CACHE_SECONDS)
    return tracks
