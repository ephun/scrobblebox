# Architecture Notes

## Core

The core service is expected to:

1. Monitor line-level audio input.
2. Capture clips when playback starts.
3. Recognize tracks from captured audio.
4. Validate recognition results against the user's Discogs collection.
5. Scrobble confirmed tracks to Last.fm.
6. Infer missing plays conservatively when enough timing evidence exists.

## Lyrics

The lyrics service should provide a now-playing experience with:

- Discogs-backed metadata
- lyric timing support
- conservative real-time inference
- no backward movement in displayed progress

## Oscilloscope

The oscilloscope service is intentionally narrow:

- turn the smart plug on when playback starts
- turn it off after prolonged inactivity

## Shared Concerns

- Environment-based configuration
- track and release metadata models
- side-aware inference rules for vinyl playback
- clean separation between hardware, third-party APIs, and business logic

