import os
import re
import json
import time
import datetime
import urllib.parse
from xml.sax.saxutils import escape as xml_escape
import asyncio
import edge_tts
from PIL import Image, ImageDraw, ImageFont
from google import genai

from generate_digest import (
    get_date_stamp, get_font, generate_episode_audio,
    append_to_podcast_rss, FEED_BASE_URL, FEED_FILE,
    CANDIDATE_MODELS, client
)

def parse_recent_episodes_from_feed(days=7):
    if not os.path.exists(FEED_FILE):
        return []
    with open(FEED_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    items = re.findall(r'<item>(.*?)</item>', content, re.DOTALL)
    recent = []
    # Grab items from the last 7 days (up to 14 episodes)
    for raw in items[:14]:
        title_m = re.search(r'<title>(.*?)</title>', raw)
        desc_m = re.search(r'<description>(.*?)</description>', raw)
        if title_m and desc_m:
            title = title_m.group(1).replace("&amp;", "&")
            desc = desc_m.group(1).replace("&amp;", "&")
            if "Weekly Roundup" not in title:
                recent.append({"title": title, "details": desc})
    return recent

def generate_recap_art(output_path):
    width, height = 1400, 1400
    img = Image.new("RGB", (width, height), color=(18, 20, 32))
    draw = ImageDraw.Draw(img)

    # Gold / Amber Roundup Banner
    draw.rounded_rectangle([(80, 80), (660, 170)], radius=18, fill=(217, 119, 6))
    font_badge = get_font(44, bold=True)
    draw.text((105, 102), "WEEKLY ROUNDUP", fill=(255, 255, 255), font=font_badge)

    date_stamp = get_date_stamp()
    font_date = get_font(42, bold=False)
    draw.text((1050, 105), date_stamp, fill=(160, 175, 200), font=font_date)

    font_title = get_font(96, bold=True)
    draw.text((85, 280), "Psychology", fill=(255, 255, 255), font=font_title)
    draw.text((85, 400), "Research Digest", fill=(255, 255, 255), font=font_title)
    draw.text((85, 520), "Weekly Brief", fill=(217, 119, 6), font=font_title)

    card_top = 1060
    draw.rounded_rectangle([(80, card_top), (1320, 1320)], radius=24, fill=(28, 32, 48))
    draw.rounded_rectangle([(80, card_top), (105, 1320)], radius=8, fill=(217, 119, 6))

    font_sub = get_font(48, bold=True)
    font_meta = get_font(40, bold=False)
    draw.text((140, card_top + 45), "Seven-Day Synthesis & Key Takeaways", fill=(240, 245, 255), font=font_sub)
    draw.text((140, card_top + 130), "Music Cognition • Reviews • Behavioral Science", fill=(160, 175, 200), font=font_meta)

    img.save(output_path)

def write_recap_script(episodes):
    summary_corpus = "\n\n".join([f"Episode: {ep['title']}\nNotes: {ep['details'][:400]}" for ep in episodes])
    
    prompt = f"""
    You are writing a weekly summary episode for 'Psychology Research Digest' with hosts Alex and Jordan.
    
    Here are the papers covered across this week's episodes:
    {summary_corpus}
    
    STRUCTURE:
    1. Alex introduces the weekly roundup: "Alex: Welcome to the weekly roundup for Psychology Research Digest, synthesizing the key findings across this week's research."
    2. Group the papers logically (starting with Music/Rhythm psychology, then Reviews/Syntheses, then Empirical findings).
    3. For EACH paper, Alex and Jordan deliver a rapid-fire, bite-sized breakdown:
       - Title, First Author, and Year.
       - The core research question or objective (1 concise sentence).
       - The essential finding / takeaway (1 concise sentence).
    4. Jordan asks quick clarifying or connecting questions between papers to keep the flow lively and conversational.
    5. Closing: Jordan gives a 2-sentence sign-off tying together the week's themes.
    
    TARGET LENGTH: 700 to 950 words.
    FORMAT: Strictly alternate lines beginning with 'Alex: ' and 'Jordan: '. No stage directions.
    """
    for attempt in range(4):
        for model in CANDIDATE_MODELS:
            try:
                res = client.models.generate_content(model=model, contents=prompt)
                if res and res.text:
                    return res.text
            except Exception:
                time.sleep(2)
        time.sleep(3)
    raise RuntimeError("Failed to generate recap script.")

async def main():
    os.makedirs("episodes", exist_ok=True)
    os.makedirs("artwork", exist_ok=True)
    
    recent_eps = parse_recent_episodes_from_feed(days=7)
    if not recent_eps:
        print("No recent episodes found in feed to summarize.")
        return

    date_slug = get_date_stamp()
    base_name = f"{date_slug} - Weekly_Roundup_Synthesis"
    mp3_path = f"episodes/{base_name}.mp3"
    art_path = f"artwork/{base_name}.png"
    
    print(f"Generating weekly recap for {len(recent_eps)} papers...")
    generate_recap_art(art_path)
    script = write_recap_script(recent_eps)
    await generate_episode_audio(script, mp3_path)
    
    entry = {
        "title": f"{date_slug} - Weekly Roundup: Seven-Day Research Digest",
        "description": f"Weekly executive synthesis covering {len(recent_eps)} papers across music cognition, affective science, and behavioral research.",
        "audio_path": mp3_path,
        "art_path": art_path,
        "guid": f"digest-recap-{date_slug.lower().replace(' ', '-')}"
    }
    append_to_podcast_rss([entry])
    print(f"Weekly recap complete: {mp3_path}")

if __name__ == "__main__":
    asyncio.run(main())
