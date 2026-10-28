# Music for the portfolio assistant

The floating music player reads its tracks straight from the folders in here. There is no list to edit.
**Every folder is one mood (category) in the player**, and every audio file inside it is a track.

```
portfolio_app/static/assets/music/
    calm/           01_Morning_Light.mp3   02_Slow_River.mp3
    energetic/      01_Drive.mp3           02_Sunrise_Run.mp3
    flute/          01_Bamboo_Dawn.mp3
```

## Add a track
1. Copy an audio file into one of the folders (`.mp3` is best; `.m4a`, `.ogg`, `.wav` also work).
2. Commit and push. Render redeploys and the track appears. Locally, restart `runserver` (or wait 5 minutes).

## Add a new mood (category)
Create a new folder here, for example `focus/`, and put tracks in it. A button called "Focus" appears in the
player automatically. Use letters, numbers, `_` and `-` in folder names (no spaces).

## Names and order
- Folder `energetic` is shown as "Energetic". Folder `02_energetic` is also shown as "Energetic": a number at the
  start only controls the order of the categories, and it is hidden. Without numbers, folders are sorted A to Z.
- File `01_Tum_Hi_Ho.mp3` is shown as "Tum Hi Ho". A number at the start only sets the order of the tracks.
- The first category that has tracks is the default when a visitor says "Yes, play music".
- If there is only one category, the mood buttons are hidden and the player just shows the tracks.

## Remove a track or mood
Delete the file or folder and push.

## Tips
- Several separate tracks of about 2 to 5 minutes work better than one very long file: they load fast, next and
  previous work, and a visitor can skip. A single file also works and simply repeats when it ends.
- Keep each file under about 4 MB (a 3 to 4 minute MP3 at 128 kbps is roughly 3 MB). Big files slow your deploys
  and use visitors' data.
- Only add music you are allowed to use. "Free to download" is not the same as "free to use on a website":
  check the licence of each track (Pixabay Music tracks come with a licence that allows use on a website
  without credit; tracks under Creative Commons "BY" need a credit line; "NC" licences do not allow commercial use).
  Keep a note of where each track came from.
- If both folders are empty, the music dock and the "play some music?" question are not shown at all.
