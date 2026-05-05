import os
import json
from flask import Flask, render_template, request, jsonify
from openai import OpenAI

app = Flask(__name__)

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

SYSTEM_PROMPT = """
You are a strict translation and formatting assistant for food display pages.

Your job is ONLY to translate the dish information provided by the user.
Do not improve, rewrite, shorten, expand, market, or beautify any text.
Do not add ingredients, allergens, cooking methods, flavors, serving suggestions, or assumptions.
Do not invent missing information.
If a field is empty, return it empty.
Preserve the price exactly as entered.
Preserve the category exactly as selected.
Return valid JSON only.

Output JSON keys:
dish_name_he
dish_name_en
description_he
description_en
ingredients_he
ingredients_en
allergens_he
allergens_en
price
category
"""

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/translate", methods=["POST"])
def translate():
    data = request.get_json(force=True)

    required_keys = [
        "dish_name", "description", "ingredients", "allergens",
        "price", "category", "source_language"
    ]

    payload = {key: data.get(key, "") for key in required_keys}

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return jsonify({
            "error": "OPENAI_API_KEY is missing. Add it in Render Environment Variables."
        }), 500

    client = OpenAI(api_key=api_key)

    user_prompt = f"""
Translate the following fields only.
Keep the original meaning exactly.
Create Hebrew and English versions.
Do not add anything.

Input JSON:
{json.dumps(payload, ensure_ascii=False)}
"""

    response = client.responses.create(
        model=MODEL,
        instructions=SYSTEM_PROMPT,
        input=user_prompt,
        temperature=0
    )

    text = response.output_text.strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return jsonify({
            "error": "AI returned invalid JSON",
            "raw": text
        }), 500

    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))