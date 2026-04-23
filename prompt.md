# ScrobbleBox v3
## Project Overview
ScrobbleBox is a tool that assists in recording and displaying information about vinyl playback. To do so, it utilizes the following services:
- Last.FM for keeping track of plays, or "scrobbles",
- Shazam via ShazamIO or equivalent Python library
- Discogs for record metadata and Shazam output validation

The project is separated into three parts: ScrobbleBox Core, ScrobbleBox Lyrics, and ScrobbleBox Oscilloscope.

## ScrobbleBox Core
ScrobbleBox Core is the central engine in the ScrobbleBox ecosystem. It is a constantly running daemon-like process, and it behaves as follows.

1. Listen to line-level input from record player
2. When music starts playing, capture an audio clip to send to Shazam via ShazamIO library
3. Recieve Title, Artist, and Offset (when in the song the clip started) data from ShazamIO
4. Validate Shazam recognition results against record collection
    - Note: Because Shazam isn't perfect, it frequently returns false positives and false negatives. 
        - To deal with any false positives, we attempt to match the Shazam results to the user's Discogs collection. We do this through fuzzy matching each of the fields. If the Shazam results sufficiently match a Title on an owned Album by the Artist, we continue, treating the Discogs version of the metadata as the "source of truth". If the results do not match sufficiently, we throw out the Shazam results.
        - To deal with any false negatives, we try recognition again on a new clip. 
        - Unfortunately, some tracks will never get recognized. This could be for audio clarity reasons or Shazam database reasons. To account for this, ScrobbleBox core has a Scrobble Inference system to retroactively put together what tracks were missed. See the Scrobble Inferrence subheader for more information.
5. Scrobble plays with matching Discogs metadata to Last.FM using Offset to calculate when the play began
6. Repeat!
    - Core keeps internal timer for how long music has been playing and the Shazam Offset datapoint, decide when a new song is likely playing and loop back to #1. This timer must have some tolerance for silence — there's often short periods of silence even while music is playing!

### Scrobble Inferrence
Because Shazam isn't perfect, it'll miss some of the tracks played. The Scrobble Inferrence system smartly tries to fill in these gaps.

As mentioned in Step #6 of the ScrobbleBox Core loop outline, the engine keeps a constant timer of how long audio has been playing. This, in combination with metadata of the user's Discogs library, allows ScrobbleBox Core to figure out what was likely playing between confirmed tracks. Take the following scenarios as a comprehensive guide to when it should or should not infer plays:

#### Example 1: Pre-confirmed/Post-confirmed inferrence on record WITH track lengths
ScrobbleBox Core sends an audio clip to Shazam, which returns a result. It then confirms this result by getting a fuzzy match in the user's Discogs library. It recognizes it as Track A3 on Album X by Artist Y. The Shazam Offset endpoint says that the audio clip began at 0:13 into the track.

ScrobbleBox Core knows that audio had been playing for 8:27 when the clip started recording. It then can deduce that there was music playing for 8:14 when the current confirmed track started — it just doesn't know what.

ScrobbleBox Core can reasonably assume that if audio was near-constantly detected in for the preceeding 8:14, it was from tracks on the same record. ScrobbleBox Core has access to the Discogs metadata for the release that its confirmed play is on. Sure enough, the sum of the length of the previous tracks on the album (A1 and A2) add up to 8:20, which is close enough to 8:14. It then can safely assume that these songs were played and send scrobbles with backfilled play times to Last.FM.

Say A2 was 7:20 and A1 was 5:15. This would be a little different — the sum of these lengths (12:35) is too dissimilar to 8:14 to infer that both tracks were played. Instead, it should only backfill as many of the preceeding tracks it can without going over.

The logic follows with end tracks. Say that we're talking about D3 being confirmed, and then audio plays for another 5:14 minutes. If the following tracks fit into this time frame, they should be scrobbled as well.

*Lesson: By default, ScrobbleBox Core should try and "fill in" tracks that played before or after known tracks by comparing the play timer to track lengths. If the duration or sum of durations matches the timer within a threshold, they should be appropriately timestamped and scrobbled.*

#### Example 2: Pre-confirmed/Post-confirmed inferrence on record WITHOUT track lengths
ScrobbleBox Core sends an audio clip to Shazam, which returns a result. It then confirms this result by getting a fuzzy match in the user's Discogs library. It recognizes it as Track A3 on Album X by Artist Y. The Shazam Offset endpoint says that the audio clip began at 0:13 into the track.

ScrobbleBox Core knows that audio had been playing for 8:27 when the clip started recording. It then can deduce that there was music playing for 8:14 when the current confirmed track started — it just doesn't know what.

ScrobbleBox Core can reasonably assume that if audio was near-constantly detected in for the preceeding 8:14, it was from tracks on the same record. ScrobbleBox Core has access to the Discogs metadata for the release that its confirmed play is on. However, this Discogs release doesn't have track lengths as part of its metadata. Because it doesn't know how long the preceeding tracks (A1 and A2) are, it cannot reliably infer that these tracks were played. Better safe than sorry!

*Lesson: By default, ScrobbleBox Core should try and "fill in" tracks that played before or after known tracks by comparing the play timer to track lengths. However, if the track lengths are unknown, scrobbles cannot be safely inferred.*

#### Example 3: Between-confirmed inferrence on record WITH OR WITHOUT track lengths.
ScrobbleBox Core sends an audio clip to Shazam, which returns a result. It then confirms this result by getting a fuzzy match in the user's Discogs library. It recognizes it as Track A1 on Album X by Artist Y. The Shazam Offset endpoint says that the audio clip began at 0:13 into the track. Later, ScrobbleBox Core recognizes Track A4 on the same album. The Shazam Offset endpoint says that the audio clip began at 0:31 into the track. 

ScrobbleBox Core can reasonably assume that if audio was near-constantly detected in between these two confirmed plays, it was from tracks on the same record, and almost certainly from the tracks in between them. ScrobbleBox Core has access to the Discogs metadata for the release that its confirmed play is on. If all of these tracks are on the same side of the same record, it can fill them in. If it has the track lengths and offsets, it can do the math to figure out when these tracks likely started playing. If it just has the offsets, it doesn't know exactly how long each track should be played, so it should equally space them.

*Lesson: by default, ScrobbleBox Core should try and "fill in" tracks between two known plays, provided they are on the same side. Otherwise, the track will be inferred by the pre-post inferrence rules or be not scrobbled.*

The takeaway is that Scrobble Inferrence should be smart, but still kind of conservative.

## ScrobbleBox Lyrics
ScrobbleBox Lyrics is an add-on lyric server and UI for ScrobbleBox Core, meant to serve as a Spotify-style "Now Playing" TV display. ScrobbleBox Lyrics takes the "fake it 'till you make it" approach to display, inferring what is playing in real-time even if it hasn't been confirmed by ScrobbleBox Core. This second inferrence system is more liberal in approach and is detailed below.

### Visuals
The display is sleek and modern, split into two panels: Track Info and Lyrics. Track Info takes up the left third of the screen and Lyrics takes up the right two-thirds.

#### Track Info
Track Info looks like a typical "Now Playing" Display: There's the album art from Discogs, a "Now Playing" chip, and the Artist/Album information. Below that is a time elapsed bar and timestamps for current time and total time. It determines this info using the Display Inferrence system (see below).

#### Lyrics
The Lyrics panel is reminiscent of the Spotify lyrics screen or Instagram lyrics sticker. At all times, it displays the previous lyric in a card that takes up the vertical top third of the window, the current (and highlighted) lyric in the middle third, and the next lyric in the bottom third. It scrapes the lyric files and uses the Display Inferrence system to determine what lyric we're on. Sometimes the Offset output is slightly off, so it can make micro-adjustments over time by averaging out the Shazam Offset values. When the lyrics transition, there is an animation where all of the cards are pushed up a spot, and the new current lyric is highlighted.

### Display Inferrence
To ensure a smooth visual experience, we sometimes have to guess at metadata. The Scrobble Inferrence system has the luxury of being able to retroactively infer. By definition, a live display does not.

Display Inferrence fills the two ScrobbleBox Lyrics panels with information the moment a ShazamIO result is verified, pulling Album Art (or a generic filler image if there is none), Artist Name, Album Name, and Length from Discogs. It pulls the lyrics file from somewhere and uses Offset to determine how far into the track we are, etc.

A few rules:
1. Never jump back in time. If a averaging from the first and second Offset call reveals that we are slightly ahead, do not jump back in time on the duration bar or the lyrics. Freeze in place until the track catches up.
2. If a track length is unavailable on Discogs, just put it out of 0:00.
3. The moment the elapsed bar is full and the Display Inferrence shows that the song is over, it must immediately go to the next track on the album (provided it is on the same side — never visually infer across sides because records need to be flipped). Get lyrics, all of it. The actual time, if different, will be adjusted by Offset Call averages as soon as they are available.
4. If lyrics aren't available, make the middle card say "No lyrics available." If lyric metadata shows that the song is instrumental, just put a music note.
5. If no audio is playing, write "Listening..."
6. Long Titles/Artist names/Album names should only take up one line but do the music player overflow thing where it scrolls across, stops at the end, and jumps back to the beginning.

## ScrobbleBox Oscilloscope
The smallest project of them all. This module assumes someone has an oscilloscope hooked up to their record player a la Jerobeam Fenderson and that the Oscilloscope is calibrated, turned on, and connected to power by a Kasa smart plug. Its only purpose is to power on the oscilloscope when music starts playing, and turn it back off when music hasn't been playing for 15 minutes to avoid display burn.

# Instructions for Codex
Please initialize this as a Github repo for me. All credentials should be stored in an .env file. This repo will be public so include an example but not my own env file when committing. Keep it organized and make it nice and clean :)