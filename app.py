import os
import json
import re
from flask import Flask, render_template, request, jsonify
from openai import OpenAI

app = Flask(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
You extract structured food data from raw menu text.

Rules:
- Do NOT invent anything
- Extract only what exists
- Clean ingredients by removing allergen parentheses
- Extract allergens separately
- Return Hebrew + English when possible
- If missing, leave empty
- Use professional Israeli culinary Hebrew, not literal translation

Important culinary translation rules:
- Spring Chicken = פרגית
- Chicken Breast = חזה עוף
- Sea Bass = לברק
- Puree = פירה
- Aioli = איולי
- Remoulade = רמולד
- Vinaigrette = ויניגרט
- Sandwich = סנדוויץ׳
- Meat = בשרי
- Dairy = חלבי
- Vegan = טבעוני
- Vegetarian = צמחוני

Return JSON only. No markdown.

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

EXPECTED_KEYS = [
    "dish_name_en",
    "dish_name_he",
    "description_en",
    "description_he",
    "ingredients_en",
    "ingredients_he",
    "allergens_en",
    "allergens_he",
    "category"
]

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/extract", methods=["POST"])
def extract():
    try:
        data = request.get_json()
        raw_text = data.get("text", "")

        if not raw_text.strip():
            return jsonify({"error": "No text provided"}), 400

        response = client.responses.create(
            model="gpt-4.1-mini",
            instructions=SYSTEM_PROMPT,
            input=raw_text,
            temperature=0
        )

        text = response.output_text.strip()

        text = re.sub(r"```json", "", text)
        text = re.sub(r"```", "", text)
        text = text.strip()

        result = json.loads(text)

        for key in EXPECTED_KEYS:
            if key not in result:
                result[key] = ""

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run()
