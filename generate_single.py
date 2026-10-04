import os
import re
import json
import time
import random
import datetime
import urllib.parse
from xml.sax.saxutils import escape as xml_escape
import asyncio
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont
from google import genai

from generate_digest import (
    load_history, save_history, get_date_stamp, get_font,
    format_author_citation, write_script_with_fallback,
    generate_episode_audio, generate_episode_art, build_paths,
    append_to_podcast_rss, fetch_openalex
)

CATEGORIES = [
    {"tag": "Music/Rhythm Priority", "query": "drummer drumming percussion rhythm meter", "review": False},
    {"tag": "Music/Rhythm Priority", "query": "music psychology emotion regulation auditory cognition", "review": False},
    {"tag": "Review / Synthesis", "query": "acceptance and commitment therapy psychological flexibility", "review": True},
    {"tag": "Review / Synthesis", "query": "emotion regulation cognitive reappraisal affective", "review": True},
    {"tag": "Review / Synthesis", "query": "psychological richness meaning in life well-being", "review": True},
    {"tag": "Empirical Article", "query": "relationship satisfaction sexual desire libido", "review": False},
    {"tag": "Empirical Article", "query": "calling career meaning vocational psychology", "review": False},
    {"tag": "Empirical Article", "query": "superstition magical thinking causal reasoning", "review": False}
]

def curate_single_random(history_set):
    random.shuffle(CATEGORIES)
    for cat in CATEGORIES:
        papers = fetch_openalex(cat["query"], is_review_only=cat["review"], days_back=150, limit=40)
        for p in papers:
            if p["id"] not in history_set:
                p["tag"] = cat["tag"]
                return p
    return None

async def main():
    os.makedirs("episodes", exist_ok=True)
    os.makedirs("artwork", exist_ok=True)
    
    history_set = load_history()
    date_slug = get_date_stamp()
    print(f"[{date_slug}] Fetching a single pseudo-random paper...")
    
    paper = curate_single_random(history_set)
    if not paper:
        print("No unseen papers found.")
        return

    print(f"Selected ({paper['tag']}): {paper['title']}")
    mp3_path, art_path = build_paths(99, paper)
    
    generate_episode_art(paper, art_path)
    script = write_script_with_fallback(paper)
    await generate_episode_audio(script, mp3_path)
    
    author_cite = format_author_citation(paper["authors"])
    ep_title = f"{date_slug} - Spotlight: {paper['title']} ({author_cite})"
    paper_link = paper["url"] if paper["url"] else "No direct link available"
    ep_desc = (
        f"{paper['title']} - {author_cite} - {paper['year']}\n"
        f"{paper_link}\n\n"
        f"{paper['journal']} ({paper['year']}). {paper['abstract']}"
    )
    
    entry = {
        "title": ep_title,
        "description": ep_desc,
        "audio_path": mp3_path,
        "art_path": art_path,
        "guid": f"digest-single-{paper['id'].split('/')[-1]}"
    }
    
    history_set.add(paper["id"])
    append_to_podcast_rss([entry])
    save_history(history_set)
    print(f"Single episode generated: {mp3_path}")

if __name__ == "__main__":
    asyncio.run(main())
