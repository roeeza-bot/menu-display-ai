import os
import json
import re
from flask import Flask, render_template, request, jsonify
from openai import OpenAI

app = Flask(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
You extract structured food data from raw text.

Rules:
- Do NOT invent anything
- Extract only what exists
- Clean ingredients (remove allergen parentheses)
- Extract allergens separately
- Return Hebrew + English when possible
- If missing, leave empty

Return JSON only:

{
  "dish_name_en": "",
  "dish_name_he": "",
  "description_en": "",
  "description_he": "",
  "ingredients_en": "",
  "ingredients_he": "",
  "allergens_en": "",
  "allergens_he": "",
  "category": ""
}
"""

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/extract", methods=["POST"])
def extract():
    try:
        data = request.get_json()
        raw_text = data.get("text", "")

        response = client.responses.create(
            model="gpt-4.1-mini",
            instructions=SYSTEM_PROMPT,
            input=raw_text,
            temperature=0
        )

        # 👇 זה התיקון הכי חשוב
        result_text = response.output[0].content[0].text

        # הופך ל-JSON אמיתי
        result_json = json.loads(result_text)

        return jsonify(result_json)

    except Exception as e:
        return jsonify({"error": str(e)})
    data = request.get_json()
    raw_text = data.get("text", "")

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=SYSTEM_PROMPT,
        input=raw_text,
        temperature=0
    )

    text = response.output_text.strip()

    text = re.sub(r"```json", "", text)
    text = re.sub(r"```", "", text)

    try:
        result = json.loads(text)
    except:
        return jsonify({"error": "Bad JSON", "raw": text}), 500

    return jsonify(result)

if __name__ == "__main__":
    app.run()
