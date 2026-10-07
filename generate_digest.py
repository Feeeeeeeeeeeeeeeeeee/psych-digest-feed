import os
import sys
import email.utils
import datetime

EPISODES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "episodes")
os.makedirs(EPISODES_DIR, exist_ok=True)
def build_show_notes(papers):
    notes = ["<p><strong>Today\'s Morning Science Briefing:</strong></p><ul>"]
    for p in papers:
        url = p.get("url") or f"https://doi.org/{p.get('doi', '')}" if p.get("doi") else f"https://scholar.google.com/scholar?q={p['title'].replace(' ', '+')}"
        authors = ", ".join(p.get("authors", []))
        notes.append(f"<li><a href=\"{url}\"><strong>{p['title']}</strong></a> — {authors} (<em>{p.get('journal', '')}</em>, {p.get('year', '')})</li>")
    notes.append("</ul>")
    return "".join(notes)

def sanitize_tts_text(text):
    text = text.replace("*", "").replace("#", "").replace("_", "")
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"\(https?://[^\)]+\)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

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

VOICE_ANCHOR = {"name": "Molly", "id": "en-NZ-MollyNeural", "pitch": "+0Hz", "rate": "+16%"}
CORRESPONDENT_ROSTER = [
    {"name": "Natasha", "id": "en-AU-NatashaNeural", "pitch": "+0Hz", "rate": "+3%"},
    {"name": "Sonia", "id": "en-GB-SoniaNeural", "pitch": "+0Hz", "rate": "+3%"},
    {"name": "Libby", "id": "en-GB-LibbyNeural", "pitch": "+0Hz", "rate": "+3%"},
]

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

def generate_episode_art(papers, output_path):
    from PIL import Image, ImageDraw, ImageFont
    import textwrap
    import urllib.request
    
    img = Image.new("RGB", (1400, 1400), color="#090D16")
    draw = ImageDraw.Draw(img)

    # Accent top bar
    draw.rectangle([(0, 0), (1400, 28)], fill="#38BDF8")

    def get_font(size, bold=False):
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
        for p in font_paths:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
        cached_font = "/tmp/Roboto-Bold.ttf" if bold else "/tmp/Roboto-Regular.ttf"
        if not os.path.exists(cached_font):
            url = ("https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Bold.ttf"
                   if bold else "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Regular.ttf")
            try:
                urllib.request.urlretrieve(url, cached_font)
            except Exception:
                pass
        if os.path.exists(cached_font):
            return ImageFont.truetype(cached_font, size)
        return ImageFont.load_default(size=size) if hasattr(ImageFont, "load_default") else ImageFont.load_default()

    font_header = get_font(72, bold=True)
    font_sub = get_font(34, bold=True)
    font_num = get_font(54, bold=True)
    font_title = get_font(46, bold=True)
    font_meta = get_font(30, bold=False)

    # Header section
    date_str = datetime.datetime.now().strftime("%A, %d %B %Y").upper()
    draw.text((80, 65), "DAILY RESEARCH BRIEFING", fill="#F8FAFC", font=font_header)
    draw.text((80, 155), f"PSYCHOLOGY & NEUROSCIENCE  •  {date_str}", fill="#38BDF8", font=font_sub)
    draw.line([(80, 215), (1320, 215)], fill="#334155", width=4)

    # 3 Story Cards
    y_pos = 250
    for i, p in enumerate(papers[:3]):
        # Number block
        draw.rounded_rectangle([(80, y_pos), (170, y_pos + 72)], radius=12, fill="#1E293B")
        draw.text((98, y_pos + 6), f"0{i+1}", fill="#38BDF8", font=font_num)

        # Title wrapping with large font
        title_lines = textwrap.wrap(p.get("title", "Research Investigation"), width=32)
        curr_y = y_pos - 4
        for line in title_lines[:3]:
            draw.text((200, curr_y), line, fill="#F8FAFC", font=font_title)
            curr_y += 56

        # Journal & Metadata
        journal = p.get("journal", "Academic Journal")
        year = p.get("year", "Recent")
        draw.text((200, curr_y + 8), f"{journal.upper()}  •  {year}", fill="#94A3B8", font=font_meta)

        y_pos += 360
        if i < 2:
            draw.line([(80, y_pos - 35), (1320, y_pos - 35)], fill="#1E293B", width=2)

    img.save(output_path, "PNG")
    print(f"Generated jumbo-scale cover art: {output_path}")

def write_script_with_fallback(paper):
    spoken_authors = format_spoken_authors(paper["authors"])
    short_cite = format_author_citation(paper["authors"])
    paper_type_display = "systematic review or meta-analysis" if "review" in paper["type"].lower() else "empirical research article"
    clean_abstract = clean_abstract_for_tts(paper["abstract"])
    
    prompt = f"""
    You are writing a podcast conversation between two co-hosts: Jordan and Alex.

    - Jordan is the expert academic researcher (voice of authority, clear, measured, pedagogical).
    - Alex has NO psychology background. He is a curious layperson who needs concepts translated into plain English.

    RAW ABSTRACT FOR CONTEXT:
    \"\"\"{paper['abstract']}\"\"\"

    CLEANED ABSTRACT FOR AUDIO READING:
    \"\"\"{clean_abstract}\"\"\"

    MANDATORY SEQUENCE:

    1. JORDAN OPENS (EXPERT):
    Jordan MUST start line 1 immediately:
    "Jordan: Today we are looking at a {paper_type_display} titled, '{paper['title']}', published in {paper['year']} in {paper['journal']}, by {spoken_authors}. Here is the abstract: {clean_abstract}"

    2. JORDAN CONTEXT & DEMOGRAPHICS:
    Directly after reading the abstract, Jordan states the study setup:
    - Sample size: "The sample size was [X] participants" (or for reviews, "This review analyzed [X] studies"). If unstated: "The specific sample size is not specified in the abstract."
    - Demographics: Summarizes age, gender, group status, or notes: "Specific demographic breakdowns were not detailed in the abstract."

    3. CONVERSATIONAL DYNAMIC (ALEX & JORDAN):
    - Alex speaks first after Jordan finishes the setup.
    - Alex questions core constructs and domain jargon. When Jordan mentions abstract concepts, Alex stops her and asks: "Wait, what does that actually mean in the real world?"
    - Alex constantly reframes Jordan's explanations into simple analogies, gut checks, and everyday terms (e.g., "So basically, if you do X to get closer rather than to dodge an argument, things go better?").
    - Jordan validates or sharpens Alex's simplified summaries.
    - NEVER read raw statistics aloud (no p-values, t-scores, F-ratios, d, r, or CI numbers). Jordan must translate all effect sizes into qualitative descriptions like "a modest shift", "a massive link", or "barely any difference".

    4. CLOSING:
    - Alex summarizes the takeaway in simple terms: "So to recap, that was '{paper['title']}' by {short_cite}."
    - Jordan delivers the final sign-off in exactly two clear sentences:
      1. A one-sentence summary of the core question.
      2. A one-sentence summary of the main finding.

    FORMATTING:
    - Strictly alternate lines starting with 'Jordan: ' and 'Alex: '.
    - Total dialogue length: 600 to 750 words.
    - No audio tags, stage directions, or bracketed notes.
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
            except Exception:
                time.sleep(2)
        time.sleep(3)
            
    raise RuntimeError("Could not generate script after retrying available models.")

async def generate_episode_audio(script_text, output_mp3):
    lines = script_text.strip().splitlines()
    temp_files = []
    
    corrs = list(CORRESPONDENT_ROSTER)
    random.shuffle(corrs)
    
    voice_map = {
        "Anchor": VOICE_ANCHOR,
        "Correspondent 1": corrs[0],
        "Correspondent 2": corrs[1],
        "Correspondent 3": corrs[2],
    }

    for i, line in enumerate(lines):
        line = line.strip()
        if not line or ":" not in line:
            continue
        speaker, text = line.split(":", 1)
        speaker = speaker.strip()
        clean_text = sanitize_tts_text(text)

        meta = voice_map.get(speaker, VOICE_ANCHOR)
        fname = f"temp_daily_{i}.mp3"
        comm = edge_tts.Communicate(clean_text, meta["id"], rate=meta["rate"], pitch=meta["pitch"])
        await comm.save(fname)
        temp_files.append(fname)

    with open(output_mp3, "wb") as out:
        for f in temp_files:
            if os.path.exists(f):
                with open(f, "rb") as inf:
                    out.write(inf.read())
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


# --- NEWSDESK CONFIGURATION & VOICE ROSTER ---
VOICE_ANCHOR = {"name": "Molly", "id": "en-NZ-MollyNeural", "pitch": "+0Hz", "rate": "+16%"}
CORRESPONDENT_ROSTER = [
    {"name": "Natasha", "id": "en-AU-NatashaNeural", "pitch": "+0Hz", "rate": "+3%"},
    {"name": "Sonia", "id": "en-GB-SoniaNeural", "pitch": "+0Hz", "rate": "+3%"},
    {"name": "Libby", "id": "en-GB-LibbyNeural", "pitch": "+0Hz", "rate": "+3%"},
]

STYLE_PERSONAS = [
    {
        "id": "pedagogical_clarifier",
        "description": "Pedagogical & Conceptual Clarifier. Deliberate, structured, intentional framing (e.g., 'We are in the territory of...', 'The distinction here is intentional...', 'You will never have a neat, open-and-shut case where...'). Focuses on scope, underlying premises, and conceptual clarity."
    },
    {
        "id": "translational_narrator",
        "description": "Translational & Big-Picture Communicator. Warm, engaging, public science approach (e.g., 'What makes this so compelling is how it translates outside the lab...', 'Making sure this research isn\'t just tucked away in a journal...'). Focuses on human meaning, everyday resonance, and broader societal relevance."
    },
    {
        "id": "mechanistic_deconstructer",
        "description": "Applied Empirical & Mechanistic Deconstructer. Pragmatic analyst who immediately separates correlation from causation (e.g., 'The link here is not necessarily that X causes Y; rather, the mechanism appears to be...', 'Looking past the baseline, what this actually isolates is...'). Translates raw statistical shifts into concrete everyday effects."
    }
]

def sanitize_tts_text(text):
    text = text.replace("*", "").replace("#", "").replace("_", "")
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"\(https?://[^\)]+\)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def build_show_notes(papers):
    notes = ["<p><strong>Today's Morning Science Briefing:</strong></p><ul>"]
    for p in papers:
        url = p.get("url") or (f"https://doi.org/{p['doi']}" if p.get("doi") else f"https://scholar.google.com/scholar?q={p['title'].replace(' ', '+')}")
        authors = ", ".join(p.get("authors", []))
        notes.append(f"<li><a href=\"{url}\"><strong>{p['title']}</strong></a> — {authors} (<em>{p.get('journal', 'Academic Journal')}</em>, {p.get('year', 'Recent')})</li>")
    notes.append("</ul>")
    return "".join(notes)

def generate_broadcast_script(papers):
    import random
    assigned_personas = random.sample(STYLE_PERSONAS, 3)
    domain_pool = [
        "Cognitive & Motor Neuroscience Desk",
        "Affective Science & Music Psychology Desk",
        "Clinical & Behavioral Health Desk"
    ]
    random.shuffle(domain_pool)

    p_blocks = []
    for i, p in enumerate(papers):
        authors = format_spoken_authors(p["authors"])
        clean_abs = clean_abstract_for_tts(p["abstract"])
        desk = domain_pool[i]
        persona = assigned_personas[i]
        p_blocks.append(f"""STORY {i+1} [{desk}]:
Title: {p['title']}
Journal: {p.get('journal', 'Academic Journal')} ({p.get('year', 'Recent')})
Authors: {authors}
Clean Abstract: {clean_abs}
Assigned Rhetorical Persona: {persona['description']}""")

    papers_text = chr(10).join(p_blocks)

    prompt = f"""You are the executive showrunner for an in-depth, long-form morning radio science program (similar to BBC Radio 4 In Our Time or NPR Science Friday).
Your mission is to produce a comprehensive broadcast that runs for 7 to 8 minutes when read aloud.

TARGET SCRIPT LENGTH (MANDATORY WORD FLOORS):
- The entire script must be between 1,150 and 1,350 total words.
- Each Correspondent segment MUST be at least 350 to 400 words (do not provide brief summaries).
- Anchor segments should be tight, authoritative, and connecting (~40 to 60 words each).

CORRESPONDENT SEGMENT STRUCTURE (Each of the 3 correspondents MUST follow this 4-part structure):
  1. The Core Scientific Tension & Experimental Setup (How researchers isolated the question, participant cohorts, or stimulation protocols).
  2. The Empirical Mechanics & Statistical Reality (Not just that a trend existed, but specific measures, effect sizes, physiological markers, or control comparisons).
  3. The Cognitive/Mechanistic Explanation (Deconstruct WHY this occurs at a neurological, cognitive, or behavioral level).
  4. Real-World Translation & Conceptual Scope (What this actually means for clinicians, performers, educators, or everyday human experience).

SPEAKING ROLES:

1. ANCHOR (Molly - Studio Desk):
   - Fast, sharp morning radio pace (+16%).
   - Intro: 2-sentence morning hook framing today's scientific themes.
   - Tosses: Clean handoffs directly to the domain desks (e.g., "Turning to our Affective Science desk...", "Over to Music Cognition...").
   - Outro: A thoughtful 3-sentence synthesis tying together the common threads of today's three papers.

2. CORRESPONDENT 1, 2, and 3:
   - Must strictly maintain their assigned rhetorical persona throughout their ~380-word segment:
     * Story 1 ({domain_pool[0]}): {assigned_personas[0]["description"]}
     * Story 2 ({domain_pool[1]}): {assigned_personas[1]["description"]}
     * Story 3 ({domain_pool[2]}): {assigned_personas[2]["description"]}

FORMATTING RULES:
- Only dialogue formatted with Speaker prefixes:
  Anchor: ...
  Correspondent 1: ...
  Anchor: ...
  Correspondent 2: ...
  Anchor: ...
  Correspondent 3: ...
  Anchor: ...
- NO asterisks, NO markdown bold/italics, NO bracketed directions (e.g., [laughs] or [pause]).

PAPERS FOR TODAY'S BROADCAST:
{papers_text}
"""

    for model_name in CANDIDATE_MODELS:
        try:
            res = client.models.generate_content(model=model_name, contents=prompt)
            if res and res.text:
                return res.text
        except Exception:
            continue
    raise RuntimeError("Failed to generate broadcast script.")

async def generate_broadcast_audio(script_text, output_mp3):
    lines = script_text.strip().splitlines()
    temp_files = []
    
    corrs = list(CORRESPONDENT_ROSTER)
    import random
    random.shuffle(corrs)
    
    voice_map = {
        "Anchor": VOICE_ANCHOR,
        "Correspondent 1": corrs[0],
        "Correspondent 2": corrs[1],
        "Correspondent 3": corrs[2],
    }

    for i, line in enumerate(lines):
        line = line.strip()
        if not line or ":" not in line:
            continue
        speaker, text = line.split(":", 1)
        speaker = speaker.strip()
        clean_text = sanitize_tts_text(text)

        meta = voice_map.get(speaker, VOICE_ANCHOR)
        fname = f"temp_daily_{i}.mp3"
        comm = edge_tts.Communicate(clean_text, meta["id"], rate=meta["rate"], pitch=meta["pitch"])
        await comm.save(fname)
        temp_files.append(fname)

    with open(output_mp3, "wb") as out:
        for f in temp_files:
            if os.path.exists(f):
                with open(f, "rb") as inf:
                    out.write(inf.read())
                os.remove(f)

async def main():
    print(f"=== Starting Morning Research Desk [{get_date_stamp()}] ===")
    history = load_history()
    papers = curate_new_papers(history)
    
    if len(papers) < 3:
        print("Not enough fresh papers found. Curation threshold not met.")
        return

    daily_papers = papers[:3]
    print("Selected 3 papers for today's broadcast.")
    
    # 1. Script Generation with Randomized Personas
    print("Generating radio broadcast script via Gemini...")
    script_text = generate_broadcast_script(daily_papers)
    
    # 2. File paths & Metadata
    date_str = get_date_stamp()
    ep_filename = f"daily_digest_{date_str}.mp3"
    art_filename = f"daily_digest_{date_str}.png"
    ep_path = os.path.join(EPISODES_DIR, ep_filename)
    art_path = os.path.join(EPISODES_DIR, art_filename)
    
    # 3. Audio Synthesis
    print("Synthesizing audio (Anchor @ +16%, Correspondents @ +3%)...")
    await generate_broadcast_audio(script_text, ep_path)
    
    # 4. Artwork
    lead_paper = daily_papers[0]
    generate_episode_art(daily_papers, art_path)
    
    # 5. Build Rich Show Notes
    show_notes = build_show_notes(daily_papers)
    
    # 6. RSS Entry with all required keys
    lead_title = lead_paper.get("title", "Daily Research Briefing")[:55]
    rel_audio_path = f"episodes/{ep_filename}"
    rel_art_path = f"episodes/{art_filename}"

    new_entry = {
        "title": f"Morning Research Briefing: {lead_title}...",
        "description": show_notes,
        "guid": f"daily_digest_{date_str}",
        "audio_path": rel_audio_path,
        "art_path": rel_art_path,
    }
    
    append_to_podcast_rss([new_entry])
    
    # 7. Update History
    for p in daily_papers:
        history.add(p["id"])
    save_history(history)
    print(f"=== Morning Digest Complete: {ep_filename} ===")

if __name__ == "__main__":
    asyncio.run(main())
