from youtube_transcript_api import YouTubeTranscriptApi
import inspect

try:
    print(f"Has get_transcript: {hasattr(YouTubeTranscriptApi, 'get_transcript')}")
    print(f"Has list_transcripts: {hasattr(YouTubeTranscriptApi, 'list_transcripts')}")
    print(f"Has get_transcripts: {hasattr(YouTubeTranscriptApi, 'get_transcripts')}")
    print("-" * 20)
    print(dir(YouTubeTranscriptApi))
except Exception as e:
    print(e)
