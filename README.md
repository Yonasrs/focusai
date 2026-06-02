import os
import base64
import json
import re
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from openai import OpenAI
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

app = FastAPI(title="Autonomous AI Focus Group")
templates = Jinja2Templates(directory="templates")

_api_key = os.getenv("OPENAI_API_KEY")
if not _api_key:
    raise RuntimeError("OPENAI_API_KEY environment variable is not set.")

client = OpenAI(api_key=_api_key)

PERSONAS = [
    {
        "id": "skeptic",
        "name": "Jordan",
        "label": "The Skeptic",
        "age": "34",
        "emoji": "🤨",
        "color": "#E85D4A",
        "description": "Suspicious and trust-sensitive. Questions everything.",
        "prompt": """You are Jordan, a 34-year-old skeptical consumer. You are naturally suspicious of advertising, question brand motives, and are very sensitive to trust signals. You dislike hype, vague claims, and anything that feels manipulative. You value transparency and authenticity above all.

Analyze this advertisement from Jordan's perspective. Respond ONLY with valid JSON matching this exact structure:
{
  "first_reaction": "A short 1-2 sentence gut reaction",
  "attention_score": <1-10>,
  "trust_score": <1-10>,
  "interest_score": <1-10>,
  "would_stop_scrolling": <true or false>,
  "main_objection": "The single biggest concern",
  "quote": "One realistic thing Jordan would actually say out loud"
}"""
    },
    {
        "id": "emotional",
        "name": "Maya",
        "label": "The Emotional Buyer",
        "age": "28",
        "emoji": "💫",
        "color": "#7C5CBF",
        "description": "Emotionally driven. Buys on feeling, not logic.",
        "prompt": """You are Maya, a 28-year-old emotionally-driven consumer. You make purchasing decisions based on how something makes you feel. You respond to storytelling, aspirational imagery, relatability, and emotional resonance. You care about how a product fits your identity and lifestyle.

Analyze this advertisement from Maya's perspective. Respond ONLY with valid JSON matching this exact structure:
{
  "first_reaction": "A short 1-2 sentence gut reaction",
  "attention_score": <1-10>,
  "trust_score": <1-10>,
  "interest_score": <1-10>,
  "would_stop_scrolling": <true or false>,
  "main_objection": "The single biggest concern",
  "quote": "One realistic thing Maya would actually say out loud"
}"""
    },
    {
        "id": "rational",
        "name": "David",
        "label": "The Rational Buyer",
        "age": "41",
        "emoji": "📊",
        "color": "#2B7A78",
        "description": "Logic and value oriented. Needs facts and proof.",
        "prompt": """You are David, a 41-year-old rational, analytical consumer. You need facts, specifics, and clear value propositions before making decisions. You compare options, read reviews, and are skeptical of vague promises. ROI and concrete benefits drive your choices.

Analyze this advertisement from David's perspective. Respond ONLY with valid JSON matching this exact structure:
{
  "first_reaction": "A short 1-2 sentence gut reaction",
  "attention_score": <1-10>,
  "trust_score": <1-10>,
  "interest_score": <1-10>,
  "would_stop_scrolling": <true or false>,
  "main_objection": "The single biggest concern",
  "quote": "One realistic thing David would actually say out loud"
}"""
    },
    {
        "id": "trendy",
        "name": "Zoe",
        "label": "The Trend Chaser",
        "age": "22",
        "emoji": "✨",
        "color": "#F4A261",
        "description": "Social-media savvy. Responds to hooks and virality.",
        "prompt": """You are Zoe, a 22-year-old trend-oriented consumer. You live on TikTok and Instagram. You notice instantly whether something feels culturally current or dated. You care about aesthetics, shareability, and whether something aligns with what's trending. A boring or "boomer" ad gets scrolled past immediately.

Analyze this advertisement from Zoe's perspective. Respond ONLY with valid JSON matching this exact structure:
{
  "first_reaction": "A short 1-2 sentence gut reaction",
  "attention_score": <1-10>,
  "trust_score": <1-10>,
  "interest_score": <1-10>,
  "would_stop_scrolling": <true or false>,
  "main_objection": "The single biggest concern",
  "quote": "One realistic thing Zoe would actually say out loud"
}"""
    },
    {
        "id": "conservative",
        "name": "Robert",
        "label": "The Value-Conscious",
        "age": "52",
        "emoji": "🎯",
        "color": "#457B9D",
        "description": "Practical and risk-averse. Needs to justify the spend.",
        "prompt": """You are Robert, a 52-year-old practical, value-conscious consumer. You are careful with money and suspicious of trendy or flashy advertising. You look for reliability, longevity, and whether something genuinely solves a real problem. You distrust hype and want straightforward, honest communication.

Analyze this advertisement from Robert's perspective. Respond ONLY with valid JSON matching this exact structure:
{
  "first_reaction": "A short 1-2 sentence gut reaction",
  "attention_score": <1-10>,
  "trust_score": <1-10>,
  "interest_score": <1-10>,
  "would_stop_scrolling": <true or false>,
  "main_objection": "The single biggest concern",
  "quote": "One realistic thing Robert would actually say out loud"
}"""
    }
]

MODERATOR_PROMPT = """You are a senior advertising strategist and focus group moderator. You have just received structured feedback from five consumer personas who reviewed an advertisement.

Here is the persona feedback:
{persona_feedback}

Ad copy provided: {ad_copy}
Target audience: {target_audience}

Your job is to synthesize this feedback into an actionable executive report. Respond ONLY with valid JSON matching this exact structure:
{{
  "executive_summary": "2-3 sentence overview of how the ad performed",
  "final_score": <overall score 1-10, weighted average>,
  "main_agreements": ["point 1", "point 2"],
  "main_disagreements": ["point 1", "point 2"],
  "strongest_positive": "The single strongest thing working in this ad",
  "strongest_negative": "The single biggest risk or weakness",
  "likely_strengths": ["strength 1", "strength 2", "strength 3"],
  "likely_weaknesses": ["weakness 1", "weakness 2", "weakness 3"],
  "attention_risks": "Key attention risks identified",
  "trust_risks": "Key trust risks identified",
  "recommended_improvements": ["improvement 1", "improvement 2", "improvement 3"],
  "suggested_angle": "A concrete alternative ad angle or headline idea that would test better"
}}"""


def encode_image(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


async def analyze_persona(persona: dict, image_b64: str, image_type: str, ad_copy: str, target_audience: str) -> dict:
    user_content = []

    user_content.append({
        "type": "image_url",
        "image_url": {
            "url": f"data:{image_type};base64,{image_b64}",
            "detail": "high"
        }
    })

    context_parts = [persona["prompt"]]
    if ad_copy:
        context_parts.append(f"\nAd copy: {ad_copy}")
    if target_audience:
        context_parts.append(f"\nTarget audience: {target_audience}")

    user_content.append({
        "type": "text",
        "text": "\n".join(context_parts)
    })

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": user_content}],
        max_tokens=500,
        temperature=0.8
    )

    raw = response.choices[0].message.content.strip()
    # Strip markdown code blocks if present
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    result = json.loads(raw)
    result["persona"] = persona
    return result


async def generate_moderator_report(persona_results: list, ad_copy: str, target_audience: str) -> dict:
    feedback_text = json.dumps([
        {
            "persona": r["persona"]["label"],
            "name": r["persona"]["name"],
            "first_reaction": r.get("first_reaction"),
            "attention_score": r.get("attention_score"),
            "trust_score": r.get("trust_score"),
            "interest_score": r.get("interest_score"),
            "would_stop_scrolling": r.get("would_stop_scrolling"),
            "main_objection": r.get("main_objection"),
            "quote": r.get("quote")
        }
        for r in persona_results
    ], indent=2)

    prompt = MODERATOR_PROMPT.format(
        persona_feedback=feedback_text,
        ad_copy=ad_copy or "Not provided",
        target_audience=target_audience or "Not specified"
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000,
        temperature=0.5
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/analyze")
async def analyze(
    image: UploadFile = File(...),
    ad_copy: Optional[str] = Form(default=""),
    target_audience: Optional[str] = Form(default="")
):
    image_bytes = await image.read()
    image_b64 = encode_image(image_bytes)
    content_type = image.content_type or "image/jpeg"

    persona_results = []
    for persona in PERSONAS:
        try:
            result = await analyze_persona(persona, image_b64, content_type, ad_copy, target_audience)
            persona_results.append(result)
        except Exception as e:
            persona_results.append({
                "persona": persona,
                "error": str(e),
                "first_reaction": "Analysis failed",
                "attention_score": 5,
                "trust_score": 5,
                "interest_score": 5,
                "would_stop_scrolling": False,
                "main_objection": "Could not analyze",
                "quote": "..."
            })

    try:
        moderator = await generate_moderator_report(persona_results, ad_copy, target_audience)
    except Exception as e:
        moderator = {"error": str(e), "executive_summary": "Moderator analysis failed."}

    return JSONResponse({
        "personas": persona_results,
        "moderator": moderator
    })


@app.get("/report", response_class=HTMLResponse)
async def report(request: Request):
    return templates.TemplateResponse("report.html", {"request": request})
