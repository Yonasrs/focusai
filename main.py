import os
import base64
import json
import re
from fastapi import FastAPI, File, UploadFile, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from openai import OpenAI
from dotenv import load_dotenv
from typing import Optional

from personas import PERSONAS, build_persona_prompt, DEBATE_PROMPT, MODERATOR_PROMPT_V2

load_dotenv()

app = FastAPI(title="Autonomous AI Focus Group v2")
templates = Jinja2Templates(directory="templates")


def get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured. Add it in Render → Environment Variables."
        )
    return OpenAI(api_key=api_key)


def clean_json(raw: str) -> str:
    """Strip markdown fences and extract the first JSON object/array."""
    raw = raw.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return raw.strip()


def encode_image(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


async def analyze_persona(
    client: OpenAI,
    persona: dict,
    image_b64: str,
    image_type: str,
    ad_copy: str,
    target_audience: str
) -> dict:
    prompt = build_persona_prompt(persona, ad_copy, target_audience)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image_type};base64,{image_b64}",
                        "detail": "high"
                    }
                },
                {"type": "text", "text": prompt}
            ]
        }],
        max_tokens=600,
        temperature=0.9   # higher temp = more personality differentiation
    )

    raw = clean_json(response.choices[0].message.content)
    result = json.loads(raw)
    result["persona"] = persona
    return result


async def generate_debate(
    client: OpenAI,
    persona_results: list
) -> dict:
    """Generate an inter-persona debate based on their individual reactions."""
    feedback_text = json.dumps([
        {
            "name": r["persona"]["name"],
            "archetype": r["persona"]["label"],
            "attention_score": r.get("attention_score"),
            "trust_score": r.get("trust_score"),
            "interest_score": r.get("interest_score"),
            "would_stop_scrolling": r.get("would_stop_scrolling"),
            "visual_evidence_found": r.get("visual_evidence_found", "not evaluated"),
            "main_objection": r.get("main_objection"),
            "first_reaction": r.get("first_reaction"),
            "quote": r.get("quote")
        }
        for r in persona_results
    ], indent=2)

    prompt = DEBATE_PROMPT.format(persona_feedback=feedback_text)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
        temperature=0.85
    )

    raw = clean_json(response.choices[0].message.content)
    return json.loads(raw)


async def generate_moderator_report(
    client: OpenAI,
    persona_results: list,
    debate: dict,
    ad_copy: str,
    target_audience: str
) -> dict:
    feedback_text = json.dumps([
        {
            "name": r["persona"]["name"],
            "archetype": r["persona"]["label"],
            "attention_score": r.get("attention_score"),
            "trust_score": r.get("trust_score"),
            "interest_score": r.get("interest_score"),
            "would_stop_scrolling": r.get("would_stop_scrolling"),
            "visual_evidence_found": r.get("visual_evidence_found", "not evaluated"),
            "main_objection": r.get("main_objection"),
            "first_reaction": r.get("first_reaction"),
            "quote": r.get("quote")
        }
        for r in persona_results
    ], indent=2)

    debate_text = json.dumps(debate, indent=2)

    prompt = MODERATOR_PROMPT_V2.format(
        persona_feedback=feedback_text,
        debate_transcript=debate_text,
        ad_copy=ad_copy or "Not provided",
        target_audience=target_audience or "Not specified"
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1200,
        temperature=0.4   # low temp = consistent, decisive moderator
    )

    raw = clean_json(response.choices[0].message.content)
    return json.loads(raw)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/analyze")
async def analyze(
    image: UploadFile = File(...),
    ad_copy: Optional[str] = Form(default=""),
    target_audience: Optional[str] = Form(default="")
):
    client = get_client()
    image_bytes = await image.read()
    image_b64 = encode_image(image_bytes)
    content_type = image.content_type or "image/jpeg"

    # Step 1 — run all 5 personas
    persona_results = []
    for persona in PERSONAS:
        try:
            result = await analyze_persona(
                client, persona, image_b64, content_type, ad_copy, target_audience
            )
            persona_results.append(result)
        except HTTPException:
            raise
        except Exception as e:
            persona_results.append({
                "persona": persona,
                "error": str(e),
                "first_reaction": "Analysis failed for this persona.",
                "attention_score": 5,
                "trust_score": 5,
                "interest_score": 5,
                "would_stop_scrolling": False,
                "main_objection": "Could not analyze.",
                "quote": "..."
            })

    # Step 2 — generate debate
    try:
        debate = await generate_debate(client, persona_results)
    except Exception as e:
        debate = {
            "exchanges": [{"speaker": "System", "line": f"Debate generation failed: {str(e)}"}],
            "debate_summary": "Debate unavailable."
        }

    # Step 3 — moderator synthesizes everything
    try:
        moderator = await generate_moderator_report(
            client, persona_results, debate, ad_copy, target_audience
        )
    except HTTPException:
        raise
    except Exception as e:
        moderator = {
            "error": str(e),
            "executive_summary": "Moderator analysis failed.",
            "decision_recommendation": "REVISE"
        }

    return JSONResponse({
        "personas": persona_results,
        "debate": debate,
        "moderator": moderator
    })


@app.get("/report", response_class=HTMLResponse)
async def report(request: Request):
    return templates.TemplateResponse(request, "report.html")
