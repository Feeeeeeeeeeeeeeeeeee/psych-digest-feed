import os
import re
import json
import time
import math
import subprocess
import datetime
import urllib.parse
from xml.sax.saxutils import escape as xml_escape
import asyncio
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont
from google import genai

GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

VOICE_ALEX = "en-US-GuyNeural"
VOICE_JORDAN = "en-US-JennyNeural"

FEED_BASE_URL = "https://feeeeeeeeeeeeeeeeeee.github.io/psych-digest-feed/"
FEED_FILE = "feed.xml"
HISTORY_FILE = "history.json"

CANDIDATE_MODELS = [
    "models/gemini-3.5-flash-lite",
    "models/gemini-flash-latest"
]

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_history(history_set):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(history_set)), f, indent=2)

def get_week_of_month(dt):
    first_day = dt.replace(day=1)
    dom = dt.day
    adjusted_dom = dom + first_day.weekday()
    return int(math.ceil(adjusted_dom / 7.0))

def get_date_stamp():
    now = datetime.date.today()
    month_str = now.strftime("%b")
    week_num = get_week_of_month(now)
    year_short = now.strftime("%y")
    return f"{month_str} W{week_num} {year_short}"

def clean_abstract_for_tts(text):
    """Strips raw statistical clutter, formulas, and bracketed numbers for smooth spoken audio."""
    if not text:
        return ""
    # Strip parenthetical/bracketed statistical blocks like (p < .05), (F(1, 24) = 4.2, p = .03), (95% CI [...])
    cleaned = re.sub(r'\([^\)]*?(?:p\s*[<=><]|CI|F\(|t\(|\bd\b\s*=|\br\b\s*=|\bOR\b\s*=|\bSD\b)[^\)]*?\)', '', text)
    cleaned = re.sub(r'\[[^\]]*?(?:p\s*[<=><]|CI|F\(|t\(|\bd\b\s*=|\br\b\s*=|\bOR\b\s*=|\bSD\b)[^\]]*?\]', '', text)
    # Strip standalone inline p-values and confidence intervals
    cleaned = re.sub(r'\b[pP]\s*[<=><]\s*\.?\d+', '', cleaned)
    cleaned = re.sub(r'95%\s*CI\s*\[[^\]]+\]', '', cleaned)
    cleaned = re.sub(r'\b(?:t|F|z|Z)\s*\(\s*\d+(?:\.\d+)?(?:,\s*\d+(?:\.\d+)?)?\)\s*=\s*-?\d+(?:\.\d+)?', '', cleaned)
    # Clean up leftover artifacts, double spaces, and awkward punctuation
    cleaned = re.sub(r'\s+([,.;])', r'\1', cleaned)
    cleaned = re.sub(r'\(\s*\)', '', cleaned)
    cleaned = re.sub(r'\[\s*\]', '', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return cleaned.strip()

def reconstruct_abstract(inverted_index):
    if not inverted_index:
        return ""
    word_map = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            word_map[pos] = word
    return " ".join([word_map[i] for i in sorted(word_map.keys())])

def fetch_openalex(query, is_review_only=False, days_back=120, limit=40):
    since_date = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()
    type_filter = "type:review" if is_review_only else "type:article|review"
    filter_str = f"is_oa:true,{type_filter},from_publication_date:{since_date},has_abstract:true,topics.field.id:32|28"
    
    url = "https://api.openalex.org/works"
    params = {
        "filter": filter_str,
        "search": query,
        "sort": "publication_date:desc",
        "per_page": limit
    }
    headers = {"User-Agent": "mailto:psych-digest-curator@example.com"}
    try:
        r = requests.get(url, params=params, headers=headers)
        resp = r.json()
    except Exception:
        return []
    
    results = []
    for item in resp.get("results", []):
        abstract = reconstruct_abstract(item.get("abstract_inverted_index"))
        if not abstract or len(abstract.split()) < 40:
            continue
            
        authorships = item.get("authorships", [])
        authors = [a.get("author", {}).get("display_name", "") for a in authorships if a.get("author", {}).get("display_name")]
        
        source_name = "Unknown Journal"
        prim_loc = item.get("primary_location") or {}
        source = prim_loc.get("source") or {}
        if source.get("display_name"):
            source_name = source.get("display_name")
            
        pub_year = item.get("publication_year") or datetime.date.today().year
        paper_url = item.get("doi") or item.get("id") or ""
        
        results.append({
            "id": item.get("id"),
            "url": paper_url,
            "title": item.get("title", "Untitled"),
            "type": item.get("type", "article"),
            "year": pub_year,
            "journal": source_name,
            "authors": authors,
            "abstract": abstract
        })
    return results

def curate_new_papers(history_set):
    chosen = []
    seen = set(history_set)
    
    music_queries = [
        "drummer drumming percussion rhythm meter",
        "musicians auditory motor synchronization",
        "music psychology emotion regulation"
    ]
    for q in music_queries:
        for p in fetch_openalex(q, is_review_only=False, limit=35):
            if p["id"] not in seen:
                p["tag"] = "Music/Rhythm Priority"
                chosen.append(p)
                seen.add(p["id"])
                if len(chosen) >= 2:
                    break
        if len(chosen) >= 2:
            break
            
    topic_queries = [
        "acceptance and commitment therapy psychological flexibility",
        "emotion regulation cognitive reappraisal affective",
        "psychological richness meaning in life well-being",
        "relationship satisfaction sexual desire libido",
        "calling career meaning vocational psychology",
        "superstition magical thinking causal reasoning"
    ]
    
    for q in topic_queries:
        if len(chosen) >= 7:
            break
        for p in fetch_openalex(q, is_review_only=True, limit=30):
            if p["id"] not in seen:
                p["tag"] = "Review / Synthesis"
                chosen.append(p)
                seen.add(p["id"])
                break
                    
    if len(chosen) < 7:
        for q in topic_queries:
            if len(chosen) >= 7:
                break
            for p in fetch_openalex(q, is_review_only=False, limit=35):
                if p["id"] not in seen:
                    p["tag"] = "Empirical Article"
                    chosen.append(p)
                    seen.add(p["id"])
                    if len(chosen) >= 7:
                        break
                        
    return chosen

def format_author_citation(authors):
    if not authors:
        return "Unknown Authors"
    if len(authors) == 1:
        return authors[0]
    return f"{authors[0]} et al."

def format_spoken_authors(authors):
    if not authors:
        return "an unknown research team"
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} and {authors[1]}"
    if len(authors) == 3:
        return f"{authors[0]}, {authors[1]}, and {authors[2]}"
    return f"{authors[0]}, {authors[1]}, {authors[2]}, and colleagues"

def get_font(size, bold=False):
    candidate_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf"
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()

def generate_episode_art(paper, output_image_path):
    width, height = 1400, 1400
    
    is_music = "Music" in paper.get("tag", "")
    is_review = "review" in paper.get("type", "").lower()
    
    if is_music:
        accent_color = (235, 94, 40)
        category_label = "MUSIC & RHYTHM"
    elif is_review:
        accent_color = (43, 147, 226)
        category_label = "SYSTEMATIC REVIEW"
    else:
        accent_color = (16, 185, 129)
        category_label = "EMPIRICAL RESEARCH"

    bg_color = (15, 20, 28)
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([(80, 80), (620, 170)], radius=18, fill=accent_color)
    font_badge = get_font(44, bold=True)
    draw.text((105, 102), category_label, fill=(255, 255, 255), font=font_badge)

    date_stamp = get_date_stamp()
    font_date = get_font(42, bold=False)
    draw.text((1050, 105), date_stamp, fill=(140, 155, 175), font=font_date)

    words = paper['title'].split()
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if len(" ".join(cur)) > 20:
            lines.append(" ".join(cur))
            cur = []
    if cur:
        lines.append(" ".join(cur))

    font_title = get_font(90, bold=True)
    y_pos = 260
    for line in lines[:5]:
        draw.text((85, y_pos), line, fill=(255, 255, 255), font=font_title)
        y_pos += 125

    card_top = 1060
    draw.rounded_rectangle([(80, card_top), (1320, 1320)], radius=24, fill=(26, 34, 46))
    draw.rounded_rectangle([(80, card_top), (105, 1320)], radius=8, fill=accent_color)

    font_journal = get_font(52, bold=True)
    font_authors = get_font(44, bold=False)

    journal_text = f"{paper['journal']} ({paper['year']})"
    draw.text((140, card_top + 45), journal_text[:40], fill=(240, 245, 255), font=font_journal)

    cite = format_author_citation(paper["authors"])
    draw.text((140, card_top + 130), f"By {cite}", fill=(160, 175, 200), font=font_authors)

    img.save(output_image_path)

def write_script_with_fallback(paper):
    spoken_authors = format_spoken_authors(paper["authors"])
    short_cite = format_author_citation(paper["authors"])
    paper_type_display = "systematic review or meta-analysis" if "review" in paper["type"].lower() else "empirical research article"
    clean_abstract = clean_abstract_for_tts(paper["abstract"])
    
    prompt = f"""
    You are writing a psychology podcast breakdown between two colleagues: Alex and Jordan.
    
    RAW ABSTRACT FOR CONTEXT:
    \"\"\"{paper['abstract']}\"\"\"

    CLEANED ABSTRACT FOR AUDIO READING:
    \"\"\"{clean_abstract}\"\"\"

    MANDATORY SEQUENCE:
    
    1. ALEX - CITATION & CLEANED ABSTRACT:
    Alex starts immediately with:
    "Alex: Today we're looking at a {paper_type_display} titled, '{paper['title']}', published in {paper['year']} in {paper['journal']}, by {spoken_authors}. Here is the abstract: {clean_abstract}"

    2. ALEX - STUDY CONTEXT & DEMOGRAPHICS (BEFORE THE CHAT):
    Immediately after the abstract, Alex states the sample and demographic profile based on the abstract information:
    - Sample size: Must use the exact phrase format: "The sample size was [X] participants" (or for reviews, state the number of studies analyzed: "This review analyzed [X] studies"). If completely omitted from the text, Alex states: "The specific sample size is not specified in the abstract."
    - Demographics: Alex summarizes participant characteristics if available (e.g., age range or mean, gender/sex distribution, geographic location, athlete/musician/clinical status, or ethnicity). If details aren't reported, Alex states: "Specific demographic breakdowns like age and gender were not detailed in the abstract."
    
    3. THE DISCUSSION (JORDAN & ALEX):
    Only AFTER Alex delivers the sample size and demographics does Jordan enter the conversation.
    - Jordan is the inquisitive learner reacting to the methodology, questioning the ecological validity, and probing implications.
    - Alex explains the mechanisms, theoretical framework, and methodological strengths/limitations.
    
    CRITICAL STATISTICAL TRANSLATION RULE:
    - NEVER read raw statistical metrics or formula numbers aloud (no p-values, t-scores, F-ratios, d = 0.42, r = .61, or confidence intervals).
    - TRANSLATE ALL EFFECT SIZES INTO PLAIN-ENGLISH MEANING. Use intuitive terms such as "a small but notable shift", "a moderate correlation", "a robust and statistically strong effect", or "a negligible difference".
    
    4. MANDATORY CLOSING (FINAL 2 TURNS):
    - Jordan: "So to recap, that was '{paper['title']}' by {short_cite}."
    - Alex: gives the final sign-off with exactly 2 sentences:
      1. A one-sentence summary of the core research question.
      2. A one-sentence summary of the main finding and its real-world implication.
    
    FORMATTING:
    - Strictly alternate lines starting with 'Alex: ' and 'Jordan: '.
    - Discussion length: 600 to 750 words.
    - No bracketed notes, stage directions, or audio tags.
    """
    
    for attempt in range(4):
        for model_name in CANDIDATE_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text:
                    return response.text
            except Exception as e:
                time.sleep(2)
        time.sleep(3)
            
    raise RuntimeError("Could not generate script after retrying available models.")

async def generate_episode_audio(script_text, output_mp3):
    lines = script_text.strip().split("\n")
    temp_files = []
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or ":" not in line:
            continue
        speaker, text = line.split(":", 1)
        voice = VOICE_ALEX if "Alex" in speaker else VOICE_JORDAN
        temp_filename = f"temp_part_{i}.mp3"
        
        communicate = edge_tts.Communicate(text.strip(), voice)
        await communicate.save(temp_filename)
        temp_files.append(temp_filename)
        
    with open(output_mp3, 'wb') as outfile:
        for f in temp_files:
            if os.path.exists(f):
                with open(f, 'rb') as infile:
                    outfile.write(infile.read())
                os.remove(f)

def build_paths(idx, paper):
    date_slug = get_date_stamp()
    snappy = "Music_Rhythm" if "Music" in paper["tag"] else ("Review" if "Review" in paper["tag"] else "Empirical")
    doc_type = "Review" if "review" in paper["type"].lower() else "Article"
    author_str = format_author_citation(paper["authors"])
    
    clean_title = re.sub(r'[^a-zA-Z0-9\s]', '', paper['title'])
    words = clean_title.split()
    short_title = "_".join(words[:6])
    clean_author = re.sub(r'[^a-zA-Z0-9\s]', '', author_str).replace(' ', '_')
    
    base_name = f"{date_slug} - {idx:02d}_{snappy} - [{doc_type}] - {short_title} ({clean_author})"
    mp3_path = f"episodes/{base_name}.mp3"
    art_path = f"artwork/{base_name}.png"
    return mp3_path, art_path

def append_to_podcast_rss(new_entries):
    now_rfc822 = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    new_items_xml = []
    for ep in new_entries:
        encoded_audio = urllib.parse.quote(ep["audio_path"])
        encoded_art = urllib.parse.quote(ep["art_path"])
        
        audio_url = urllib.parse.urljoin(FEED_BASE_URL, encoded_audio)
        art_url = urllib.parse.urljoin(FEED_BASE_URL, encoded_art)
        filesize = os.path.getsize(ep["audio_path"]) if os.path.exists(ep["audio_path"]) else 15000000
        
        item_block = f"""    <item>
      <title>{xml_escape(ep['title'])}</title>
      <description>{xml_escape(ep['description'])}</description>
      <pubDate>{now_rfc822}</pubDate>
      <enclosure url="{audio_url}" length="{filesize}" type="audio/mpeg" />
      <itunes:image href="{art_url}" />
      <guid isPermaLink="false">{ep['guid']}</guid>
      <itunes:duration>480</itunes:duration>
      <itunes:explicit>no</itunes:explicit>
    </item>"""
        new_items_xml.append(item_block)
        
    all_new_str = "\n".join(new_items_xml)
    
    existing_items = ""
    if os.path.exists(FEED_FILE):
        with open(FEED_FILE, "r", encoding="utf-8") as f:
            old_content = f.read()
            match = re.search(r'(<item>.*?</item>)', old_content, re.DOTALL)
            if match:
                items_start = old_content.find("    <item>")
                items_end = old_content.rfind("</item>") + len("</item>")
                if items_start != -1 and items_end != -1:
                    existing_items = old_content[items_start:items_end]

    combined_items = all_new_str
    if existing_items:
        combined_items = all_new_str + "\n" + existing_items

    rss_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Psychology Research Digest</title>
    <link>{FEED_BASE_URL}</link>
    <language>en-us</language>
    <itunes:author>Felix</itunes:author>
    <description>Twice-weekly deep-dives into music psychology, affective science, and behavioural research.</description>
    <itunes:summary>Curated literature breakdowns covering music cognition, rhythm, emotional regulation, and clinical psychology.</itunes:summary>
    <itunes:category text="Science">
      <itunes:category text="Social Sciences"/>
    </itunes:category>
    <itunes:image href="https://raw.githubusercontent.com/Feeeeeeeeeeeeeeeeeee/psych-digest-feed/main/cover.png"/>
    <itunes:explicit>no</itunes:explicit>
{combined_items}
  </channel>
</rss>
"""
    with open(FEED_FILE, "w", encoding="utf-8") as f:
        f.write(rss_content)
    print(f"Updated {FEED_FILE} (added {len(new_entries)} fresh episodes).")

async def main():
    os.makedirs("episodes", exist_ok=True)
    os.makedirs("artwork", exist_ok=True)
    
    history_set = load_history()
    date_slug = get_date_stamp()
    print(f"[{date_slug}] Checking for brand-new papers (skipping {len(history_set)} previously covered)...")
    
    new_papers = curate_new_papers(history_set)
    if not new_papers:
        print("No new papers found since last cycle. Exiting without changes.")
        return

    print(f"Found {len(new_papers)} new papers. Synthesizing...\n")
    episode_entries = []

    for idx, paper in enumerate(new_papers, 1):
        mp3_path, art_path = build_paths(idx, paper)
        print(f"--- [{idx}/{len(new_papers)}] {paper['title'][:65]} ---")
        
        generate_episode_art(paper, art_path)
        script = write_script_with_fallback(paper)
        await generate_episode_audio(script, mp3_path)
        
        author_cite = format_author_citation(paper["authors"])
        ep_title = f"{date_slug} - {idx:02d}: {paper['title']} ({author_cite})"
        
        paper_link = paper["url"] if paper["url"] else "No direct link available"
        ep_desc = (
            f"{paper['title']} - {author_cite} - {paper['year']}\n"
            f"{paper_link}\n\n"
            f"{paper['journal']} ({paper['year']}). {paper['abstract']}"
        )
        
        episode_entries.append({
            "title": ep_title,
            "description": ep_desc,
            "audio_path": mp3_path,
            "art_path": art_path,
            "guid": f"digest-{paper['id'].split('/')[-1]}"
        })
        
        history_set.add(paper["id"])
        if idx < len(new_papers):
            time.sleep(3)

    append_to_podcast_rss(episode_entries)
    save_history(history_set)
    print(f"All {len(new_papers)} episodes compiled successfully.")

if __name__ == "__main__":
    asyncio.run(main())
