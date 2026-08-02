import os
import json
from urllib.parse import urljoin
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from groq import Groq
from playwright.sync_api import sync_playwright

load_dotenv()

app = FastAPI(title="Email Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"          # text-only tasks (replacement for deprecated llama-3.3-70b-versatile)


class CommandRequest(BaseModel):
    command: str


class ReviseRequest(BaseModel):
    profile: dict
    current_email: dict
    edit_instruction: str


def parse_intent(command: str) -> dict:
    prompt = f"""Extract structured details from this user command about generating a marketing email.

Command: "{command}"

Extract:
- url: the website URL mentioned
- email_type: one of welcome, discount, newsletter, product_announcement, re_engagement, or 'unspecified' if unclear
- topic_focus: a specific theme/product line/category the user wants the email to focus on (e.g. "ready to wear essentials"), or null if not mentioned
- image_count: how many images the user wants included (a number), or null if not mentioned
- length_preference: one of "short", "medium", "long", or null if not mentioned

Respond with ONLY valid JSON in this exact format, nothing else:
{{"url": "<url or null>", "email_type": "<type>", "topic_focus": "<topic or null>", "image_count": <number or null>, "length_preference": "<short/medium/long or null>"}}
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Could not understand the command. Please try rephrasing.")

    return parsed


def scrape_website(url: str) -> dict:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Give JS-rendered content (SPAs, lazy-loaded sections) a moment to populate
            page.wait_for_timeout(2500)

            title = page.title()

            meta_description = page.evaluate("""
                () => {
                    const tag = document.querySelector('meta[name="description"]');
                    return tag ? tag.getAttribute('content') : '';
                }
            """)

            og_image = page.evaluate("""
                () => {
                    const tag = document.querySelector('meta[property="og:image"]');
                    return tag ? tag.getAttribute('content') : null;
                }
            """)

            candidate_images = page.evaluate("""
                () => Array.from(document.querySelectorAll('img'))
                    .filter(img => img.naturalWidth > 300 && img.naturalHeight > 300)
                    .map(img => img.src)
                    .filter(Boolean)
                    .slice(0, 8)
            """)

            headings = page.evaluate("""
                () => Array.from(document.querySelectorAll('h1, h2, h3'))
                    .map(el => el.innerText.trim())
                    .filter(Boolean)
            """)

            body_text = page.evaluate("() => document.body.innerText")

            design_data = page.evaluate("""
                () => {
                    function rgbToHex(rgb) {
                        if (!rgb) return null;
                        const m = rgb.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                        if (!m) return null;
                        return '#' + m.slice(1, 4).map(x => parseInt(x).toString(16).padStart(2, '0')).join('');
                    }

                    const bodyStyle = getComputedStyle(document.body);
                    const backgroundColor = rgbToHex(bodyStyle.backgroundColor) || '#ffffff';
                    const textColor = rgbToHex(bodyStyle.color) || '#1a1a1a';

                    // Look at buttons/CTAs for the most commonly used accent color
                    const candidates = Array.from(document.querySelectorAll(
                        'button, a.btn, a.button, [class*="btn"], [class*="button"], [role="button"], input[type="submit"]'
                    ));
                    const colorCounts = {};
                    candidates.forEach(el => {
                        const bg = rgbToHex(getComputedStyle(el).backgroundColor);
                        if (bg && bg !== backgroundColor && bg !== '#000000') {
                            colorCounts[bg] = (colorCounts[bg] || 0) + 1;
                        }
                    });

                    let accentColor = null;
                    let maxCount = 0;
                    for (const [color, count] of Object.entries(colorCounts)) {
                        if (count > maxCount) {
                            maxCount = count;
                            accentColor = color;
                        }
                    }

                    // Fallback: use link color if no button accent found
                    if (!accentColor) {
                        const links = Array.from(document.querySelectorAll('a'));
                        for (const a of links) {
                            const c = rgbToHex(getComputedStyle(a).color);
                            if (c && c !== textColor) {
                                accentColor = c;
                                break;
                            }
                        }
                    }

                    return {
                        backgroundColor,
                        textColor,
                        accentColor: accentColor || '#2563eb',
                        sectionCount: document.querySelectorAll('section, article, [class*="section"]').length,
                        imageCount: document.querySelectorAll('img').length
                    };
                }
            """)

            browser.close()

            cleaned_body = " ".join(body_text.split())[:3000]

            scraped_text = f"""
Title: {title}
Meta Description: {meta_description}
Headings: {', '.join(headings[:15])}
Body Content: {cleaned_body}
"""

            raw_images = []
            if og_image:
                raw_images.append(og_image)
            for img in candidate_images:
                if img not in raw_images:
                    raw_images.append(img)

            image_urls = [urljoin(url, img) for img in raw_images]

            if design_data["imageCount"] > 6:
                layout_feel = "image-heavy and dense"
            elif design_data["sectionCount"] <= 2:
                layout_feel = "minimal and spacious"
            else:
                layout_feel = "balanced, moderately structured"

            design = {
                "background_color": design_data["backgroundColor"],
                "text_color": design_data["textColor"],
                "accent_color": design_data["accentColor"],
                "layout_feel": layout_feel,
            }

            return {"text": scraped_text, "image_urls": image_urls, "design": design}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to scrape the website: {str(e)}")


def build_business_profile(scraped_text: str, image_urls: list) -> dict:
    prompt = f"""Based on the following scraped website content, extract a business profile.

Scraped Content:
{scraped_text}

Respond with ONLY valid JSON in this exact format, nothing else:
{{
  "business_name": "<name of the business>",
  "industry": "<industry/category>",
  "tone": "<brief description of the brand's tone/voice>",
  "key_products_or_services": ["<item1>", "..."],
  "notable_offers_or_usps": ["<offer 1>", "..."]
}}
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to build a business profile from the scraped content.")

    parsed["image_urls"] = image_urls
    return parsed


def generate_email(profile: dict, email_type: str, topic_focus: str, image_count: int,
                    length_preference: str = None, design: dict = None, extra_guidance: str = "") -> dict:
    images = profile.get("image_urls", [])
    logo_tag = f'<img src="{images[0]}" alt="{profile["business_name"]}" style="max-width:200px; margin-bottom:16px;" />' if images else ""

    extra_images = images[1:1 + image_count] if len(images) > 1 else []
    marker_list = ", ".join([f"[[IMAGE_BREAK_{i}]]" for i in range(len(extra_images))]) if extra_images else "(no image markers needed)"

    topic_instruction = f"Focus specifically on this theme/product line: {topic_focus}." if topic_focus else ""

    length_map = {
        "short": "60-90 words",
        "medium": "120-180 words",
        "long": "250-350 words",
    }
    word_count_instruction = length_map.get(length_preference, "120-180 words")

    design = design or {
        "background_color": "#ffffff",
        "text_color": "#1a1a1a",
        "accent_color": "#2563eb",
        "layout_feel": "clean and simple"
    }

    design_instruction = f"""
Style every element with inline CSS matching this design:
- Background color: {design['background_color']}
- Text color: {design['text_color']}
- Accent/button color: {design['accent_color']}
- Overall feel: {design['layout_feel']}
Wrap the whole body in a container div with the background color, padding, and text color set inline. Style any call-to-action like a button using the accent color.
"""

    prompt = f"""You are writing a marketing email on behalf of this business, based on their profile below.

Business Profile:
{json.dumps({k: v for k, v in profile.items() if k != "image_urls"}, indent=2)}

Email type to write: {email_type}
{topic_instruction}

Guidelines based on email type:
- welcome: warm introduction to a new subscriber, highlight what makes the brand special
- discount: promote a specific offer or discount, create urgency, include a clear call to action
- newsletter: recap-style update on products/offers, friendly and informative tone
- product_announcement: spotlight a specific product/service, build excitement
- re_engagement: win back an inactive subscriber, remind them what they're missing
- unspecified: default to a general promotional email showcasing the brand

Write in the tone described in the business profile. Keep the body around {word_count_instruction}, written like a real marketing email a subscriber would receive.
Write the body as HTML paragraphs (use <p> tags), not plain text.
Do not invent specific numbers, prices, percentages, timeframes, or guarantees that are not explicitly stated in the business profile above. If the profile only says something general (e.g. "fast delivery" with no timeframe), describe it in general terms (e.g. "quick, reliable delivery") — do not add a specific number of days/hours/percent that isn't in the profile.
{extra_guidance}
{design_instruction}
Insert these exact markers at natural points in the email where images would fit well, in order: {marker_list}

Respond with ONLY valid JSON in this exact format, nothing else:
{{"subject": "<compelling subject line>", "body": "<HTML with inline styles and image markers inserted>"}}
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to generate the email. Please try again.")

    body = parsed["body"]
    for i, img_url in enumerate(extra_images):
        tag = f'<img src="{img_url}" alt="Featured item" style="max-width:100%; border-radius:8px; margin:16px 0;" />'
        marker = f"[[IMAGE_BREAK_{i}]]"
        if marker in body:
            body = body.replace(marker, tag)
        else:
            body += tag

    parsed["body"] = logo_tag + body
    return parsed


def revise_email(profile: dict, current_email: dict, edit_instruction: str) -> dict:
    prompt = f"""You previously wrote this marketing email for a business. The user wants a specific change made.

Business Profile (the only verified facts about this business):
{json.dumps({k: v for k, v in profile.items() if k != "image_urls"}, indent=2)}

Current Email:
Subject: {current_email['subject']}
Body: {current_email['body']}

Requested change: {edit_instruction}

Apply the requested change while keeping everything else consistent with the business profile above. Do not invent offers, prices, or products not listed in the profile. Preserve any existing <img> tags and inline styles in the body exactly as they are unless the change specifically asks to remove/move images or restyle it.

Respond with ONLY valid JSON in this exact format, nothing else:
{{"subject": "<updated subject>", "body": "<updated HTML body>"}}
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to apply the revision. Please try again.")

    return parsed


def critic_check(email: dict, profile: dict) -> dict:
    prompt = f"""You are a fact-checker reviewing a marketing email for fabricated claims.

Business Profile (the only verified facts about this business):
{json.dumps({k: v for k, v in profile.items() if k != "image_urls"}, indent=2)}

Generated Email:
Subject: {email['subject']}
Body: {email['body']}

Check if the email makes any claims NOT supported by the business profile — specifically:
- Mentions of discounts, prices, or offers not listed in "notable_offers_or_usps"
- Mentions of products/services not listed in "key_products_or_services"
- Any other invented specifics (dates, percentages, guarantees) not grounded in the profile

Respond with ONLY valid JSON in this exact format, nothing else:
{{"passed": true/false, "issues": ["<issue 1>", "..."]}}
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"passed": True, "issues": []}

    return parsed


@app.post("/generate")
def generate(request: CommandRequest):
    intent = parse_intent(request.command)

    if not intent.get("url"):
        raise HTTPException(status_code=400, detail="No website URL found in your command. Please include one.")

    scraped = scrape_website(intent["url"])
    profile = build_business_profile(scraped["text"], scraped["image_urls"])
    design = scraped["design"]

    if intent["email_type"] == "discount" and not profile.get("notable_offers_or_usps"):
        raise HTTPException(
            status_code=400,
            detail=f"No discount or offer was found on {intent['url']}. Try a different email type like 'welcome' or 'newsletter'."
        )

    image_count = intent.get("image_count") or 1
    topic_focus = intent.get("topic_focus")
    length_preference = intent.get("length_preference")

    max_attempts = 3
    extra_guidance = ""
    email = None
    review = None

    for attempt in range(max_attempts):
        email = generate_email(profile, intent["email_type"], topic_focus, image_count,
                                length_preference, design, extra_guidance)
        review = critic_check(email, profile)
        if review["passed"]:
            break
        issues_text = "; ".join(review["issues"])
        extra_guidance = (
            f"IMPORTANT: A previous draft was rejected for containing these unverified claims: {issues_text}. "
            f"Do not repeat these — only state facts that appear in the business profile above."
        )

    if not review["passed"]:
        issues_text = "; ".join(review["issues"])
        raise HTTPException(
            status_code=400,
            detail=f"Generated email contained unverified claims: {issues_text}. Try a different email type or website."
        )

    return {"subject": email["subject"], "body": email["body"], "profile": profile}


@app.post("/revise")
def revise(request: ReviseRequest):
    updated_email = revise_email(request.profile, request.current_email, request.edit_instruction)

    review = critic_check(updated_email, request.profile)
    if not review["passed"]:
        issues_text = "; ".join(review["issues"])
        raise HTTPException(
            status_code=400,
            detail=f"Revision introduced unverified claims: {issues_text}. Try rephrasing your edit request."
        )

    return updated_email