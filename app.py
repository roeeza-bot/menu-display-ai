import os
import re
import json
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename

try:
    import fitz
except Exception:
    fitz = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY) if OpenAI and OPENAI_API_KEY else None


MEAT_STATIONS = ["grill", "chef special", "sandwich", "soup", "sushi"]
DAIRY_STATIONS = ["fish special", "pizza", "bakery", "veg", "vegan", "vegetarian"]

ALLERGEN_PATTERNS = {
    r"\bgluten\b": "גלוטן",
    r"\bwheat\b": "חיטה",
    r"\begg\b|\beggs\b": "ביצים",
    r"\bmilk\b|\bdairy\b": "חלב",
    r"\bsoy\b|\bsoya\b": "סויה",
    r"\bsesame\b": "שומשום",
    r"\bmustard\b": "חרדל",
    r"\blupin\b": "לופין",
    r"\bfish\b": "דגים",
    r"\bnut\b|\bnuts\b": "אגוזים",
    r"\bpeanut\b|\bpeanuts\b": "בוטנים",
    r"\bcelery\b": "סלרי",
    r"\bsulfites\b|\bsulphites\b": "סולפיטים",
}


def clean_text(text):
    if not text:
        return ""
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.replace("and and", "and")
    text = text.replace("beaf", "beef")
    text = text.replace("tomatoes salad", "tomato salad")
    return text.strip()


def split_category(raw):
    raw = clean_text(raw)
    match = re.search(r"^(.*?)\s*\((.*?)\)", raw)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return raw.strip(), ""


def map_kosher(category, raw_kosher=""):
    c = (category or "").lower()
    raw = (raw_kosher or "").lower()

    if "salad bar" in c:
        return ""

    for station in MEAT_STATIONS:
        if station in c:
            return "בשרי"

    for station in DAIRY_STATIONS:
        if station in c:
            return "חלבי"

    if raw == "meat":
        return "בשרי"
    if raw == "dairy":
        return "חלבי"

    return ""


def extract_allergens(text):
    text_l = (text or "").lower()
    found = []

    for pattern, hebrew in ALLERGEN_PATTERNS.items():
        if re.search(pattern, text_l) and hebrew not in found:
            found.append(hebrew)

    order = ["גלוטן", "חיטה", "ביצים", "חלב", "דגים", "סויה", "שומשום", "חרדל", "לופין", "אגוזים", "בוטנים", "סלרי", "סולפיטים"]
    found.sort(key=lambda x: order.index(x) if x in order else 999)

    return ", ".join(found)


def extract_text_from_pdf(path):
    if fitz is None:
        return ""

    doc = fitz.open(path)
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text


def is_category_line(line):
    l = line.lower()
    return "(" in line and ")" in line and ("meat" in l or "dairy" in l)


def parse_text(text):
    text = clean_text(text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    dishes = []
    current = None
    ingredient_mode = False

    for line in lines:
        if is_category_line(line):
            if current and current.get("name"):
                dishes.append(current)

            current = {
                "category_raw": line,
                "name": "",
                "description": "",
                "ingredients": "",
                "price": "55"
            }
            ingredient_mode = False
            continue

        if current is None:
            continue

        if re.fullmatch(r"\d+(\.\d+)?", line):
            current["price"] = line
            ingredient_mode = False
            continue

        if line.lower().startswith("ingredients"):
            current["ingredients"] = line.split(":", 1)[-1].strip() if ":" in line else ""
            ingredient_mode = True
            continue

        if ingredient_mode:
            current["ingredients"] += (", " if current["ingredients"] else "") + line
            continue

        if not current["name"]:
            current["name"] = line
        elif not current["description"] and line != current["name"]:
            current["description"] = line

    if current and current.get("name"):
        dishes.append(current)

    return dishes


def enhance_with_ai(dish):
    fallback = {
        "name_he": dish.get("name_en", ""),
        "description_he": dish.get("description_en", ""),
        "ingredients_he": dish.get("ingredients_en", "")
    }

    if client is None:
        return fallback

    prompt = {
        "station": dish.get("category", ""),
        "kosher": dish.get("kosher", ""),
        "name_en": dish.get("name_en", ""),
        "description_en": dish.get("description_en", ""),
        "ingredients_en": dish.get("ingredients_en", "")
    }

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": """
You are a culinary Hebrew menu display editor for Apple Herzliya Caffè Macs.
Return JSON only.

Rules:
- Translate and improve only the Hebrew culinary text.
- Do not decide kosher.
- Do not decide station/category.
- Do not decide allergens.
- Do not invent ingredients.
- Keep Hebrew professional, clear, concise, suitable for a food display.
- Dish name should sound like a real menu item, not literal translation.
- Description should be one short elegant sentence.
- Ingredients should be translated to Hebrew, comma separated.
- Keep culinary terms when appropriate: טחינה, אריסה, מטבוחה, פתיתים, קובה, סינייה, בריסקט.
- If a vegan dish is kosher dairy because of the station, do not mention parve.
Return exactly:
{
  "name_he": "...",
  "description_he": "...",
  "ingredients_he": "..."
}
"""
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False)
                }
            ]
        )

        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)

        return {
            "name_he": data.get("name_he") or fallback["name_he"],
            "description_he": data.get("description_he") or fallback["description_he"],
            "ingredients_he": data.get("ingredients_he") or fallback["ingredients_he"]
        }

    except Exception:
        return fallback


def normalize_dish(raw):
    category, raw_kosher = split_category(raw.get("category_raw", ""))
    kosher = map_kosher(category, raw_kosher)

    dish = {
        "category": category,
        "kosher": kosher,
        "name_en": clean_text(raw.get("name", "")),
        "description_en": clean_text(raw.get("description", "")),
        "ingredients_en": clean_text(raw.get("ingredients", "")),
        "price": raw.get("price", "55")
    }

    dish["allergens"] = extract_allergens(
        f"{dish['ingredients_en']} {dish['description_en']}"
    )

    ai = enhance_with_ai(dish)

    dish["name_he"] = ai["name_he"]
    dish["description_he"] = ai["description_he"]
    dish["ingredients_he"] = ai["ingredients_he"]

    return dish


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/extract", methods=["POST"])
def extract():
    raw_text = ""

    if "file" in request.files:
        file = request.files["file"]
        filename = secure_filename(file.filename)
        path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(path)

        if filename.lower().endswith(".pdf"):
            raw_text = extract_text_from_pdf(path)
        else:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                raw_text = f.read()
    else:
        data = request.json or {}
        raw_text = data.get("text", "")

    raw_dishes = parse_text(raw_text)
    dishes = [normalize_dish(d) for d in raw_dishes]

    return jsonify({
        "success": True,
        "count": len(dishes),
        "dishes": dishes
    })


@app.route("/enhance", methods=["POST"])
def enhance():
    data = request.json or {}

    fixed = {
        "category": data.get("category", ""),
        "kosher": data.get("kosher", ""),
        "name_en": data.get("name_en", ""),
        "description_en": data.get("description_en", ""),
        "ingredients_en": data.get("ingredients_en", ""),
        "price": data.get("price", "55"),
        "allergens": data.get("allergens", "")
    }

    ai = enhance_with_ai(fixed)

    fixed["name_he"] = ai["name_he"]
    fixed["description_he"] = ai["description_he"]
    fixed["ingredients_he"] = ai["ingredients_he"]

    return jsonify({
        "success": True,
        "dish": fixed
    })


@app.route("/create-display", methods=["POST"])
def create_display():
    data = request.json or {}

    display = {
        "kosher": data.get("kosher", ""),
        "category": data.get("category", ""),
        "name_he": data.get("name_he", ""),
        "name_en": data.get("name_en", ""),
        "description_he": data.get("description_he", ""),
        "description_en": data.get("description_en", ""),
        "ingredients_he": data.get("ingredients_he", ""),
        "ingredients_en": data.get("ingredients_en", ""),
        "allergens": data.get("allergens", ""),
        "price": data.get("price", "55")
    }

    return jsonify({
        "success": True,
        "display": display
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
