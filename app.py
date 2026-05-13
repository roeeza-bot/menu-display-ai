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

MEAT_STATIONS = [
    "grill",
    "chef special",
    "sandwich",
    "soup",
    "sushi",
    "meat station",
    "chicken station"
]

DAIRY_STATIONS = [
    "fish special",
    "pizza",
    "bakery",
    "veg",
    "vegan",
    "vegetarian",
    "fish station",
    "pizza station"
]

ALLERGEN_PATTERNS = {
    r"\bgluten\b": ("Gluten", "גלוטן"),
    r"\bwheat\b": ("Wheat", "חיטה"),
    r"\begg\b|\beggs\b": ("Eggs", "ביצים"),
    r"\bmilk\b|\bdairy\b": ("Milk", "חלב"),
    r"\bsoy\b|\bsoya\b|\bsoybeans\b": ("Soy", "סויה"),
    r"\bsesame\b": ("Sesame", "שומשום"),
    r"\bmustard\b": ("Mustard", "חרדל"),
    r"\blupin\b": ("Lupin", "לופין"),
    r"\bfish\b": ("Fish", "דגים"),
    r"\bnut\b|\bnuts\b|\btree nuts\b|\bcashew\b|\balmond\b|\bpistachio\b": ("Nuts", "אגוזים"),
    r"\bpeanut\b|\bpeanuts\b": ("Peanuts", "בוטנים"),
    r"\bcelery\b": ("Celery", "סלרי"),
    r"\bsulfites\b|\bsulphites\b": ("Sulfites", "סולפיטים"),
}

CULINARY_HE_REPLACEMENTS = {
    "lemon grass": "למון גראס",
    "lemongrass": "למון גראס",
    "stracciatella": "סטרצ׳יאטלה",
    "yuzu": "יוזו",
    "miso": "מיסו",
    "panko": "פנקו",
    "aioli": "איולי",
    "brioche": "בריוש",
    "kimchi": "קימצ׳י",
    "shatta": "שאטה",
}


def clean_text(text):
    if not text:
        return ""

    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


def clean_price(value):
    if not value:
        return "55"

    cleaned = re.sub(r"[^\d.]", "", value)
    cleaned = cleaned.replace(".00", "")

    return cleaned or "55"


def extract_text_from_pdf(path):
    if fitz is None:
        return ""

    doc = fitz.open(path)
    pages = []

    for page in doc:
        txt = page.get_text()
        if txt.strip():
            pages.append(txt)

    doc.close()

    return "\n\n__PAGE_BREAK__\n\n".join(pages)


def extract_allergens(text):
    text_l = (text or "").lower()

    found_en = []
    found_he = []

    for pattern, (en, he) in ALLERGEN_PATTERNS.items():
        if re.search(pattern, text_l):
            if en not in found_en:
                found_en.append(en)
            if he not in found_he:
                found_he.append(he)

    return {
        "allergens_en": ", ".join(found_en),
        "allergens_he": ", ".join(found_he),
        "allergens": ", ".join(found_he)
    }


def normalize_category(category):
    c = (category or "").strip().lower()

    if "sushi" in c:
        return "Sushi Station"

    if "grill" in c or "meat station" in c:
        return "Grill"

    if "chef" in c or "chicken station" in c:
        return "Chef Special"

    if "sandwich" in c:
        return "Sandwich"

    if "soup" in c:
        return "Soup"

    if "fish" in c:
        return "Fish Special"

    if "pizza" in c:
        return "Pizza"

    if "bakery" in c:
        return "Bakery"

    if "veg" in c or "vegan" in c or "vegetarian" in c:
        return "Veg/Vegan"

    if "salad" in c:
        return "Salad Bar"

    return "Grill"


def map_kosher(category):
    c = (category or "").lower()

    if "salad" in c:
        return "פרווה"

    for item in MEAT_STATIONS:
        if item in c:
            return "בשרי"

    for item in DAIRY_STATIONS:
        if item in c:
            return "חלבי"

    return "בשרי"


def post_process_hebrew(text):
    if not text:
        return ""

    result = text

    for eng, heb in CULINARY_HE_REPLACEMENTS.items():
        result = re.sub(eng, heb, result, flags=re.IGNORECASE)

    return result.strip()


def ai_translate(dish):
    fallback = {
        "name_he": dish.get("name_en", ""),
        "description_he": dish.get("description_en", ""),
        "ingredients_he": dish.get("ingredients_en", "")
    }

    if client is None:
        return fallback

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": """
You are a professional culinary translator for Apple Caffè Macs.

Return JSON only.

Rules:
- Translate to professional culinary Hebrew
- Keep sushi terminology accurate
- Do not invent ingredients
- Do not change dish meaning
- Keep translations short and elegant

Return:
{
"name_he":"...",
"description_he":"...",
"ingredients_he":"..."
}
"""
                },
                {
                    "role": "user",
                    "content": json.dumps(dish, ensure_ascii=False)
                }
            ]
        )

        raw = response.choices[0].message.content
        raw = raw.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(raw)

        return {
            "name_he": post_process_hebrew(parsed.get("name_he", fallback["name_he"])),
            "description_he": post_process_hebrew(parsed.get("description_he", fallback["description_he"])),
            "ingredients_he": post_process_hebrew(parsed.get("ingredients_he", fallback["ingredients_he"]))
        }

    except Exception:
        return fallback


def parse_pdf_pages(text):
    pages = [p.strip() for p in text.split("__PAGE_BREAK__") if p.strip()]

    dishes = []

    for page in pages:

        lines = [l.strip() for l in page.split("\n") if l.strip()]

        if len(lines) < 3:
            continue

        station = lines[0]
        category = normalize_category(station)

        current_name = None
        current_price = "55"
        current_description = []
        current_ingredients = []

        for line in lines[1:]:

            if re.search(r"₪\s*\d+", line):
                current_price = clean_price(line)
                continue

            if line.lower().startswith("ingredients"):
                ing = line.split(":", 1)[-1].strip() if ":" in line else ""
                current_ingredients.append(ing)
                continue

            if len(line) < 60 and not current_name:
                current_name = line
                continue

            if current_name and not current_description:
                current_description.append(line)
                continue

            current_ingredients.append(line)

        if current_name:
            ingredients_text = clean_text(" ".join(current_ingredients))

            dish = {
                "category": category,
                "kosher": map_kosher(category),
                "name_en": clean_text(current_name),
                "description_en": clean_text(" ".join(current_description)),
                "ingredients_en": ingredients_text,
                "price": current_price
            }

            allergens = extract_allergens(ingredients_text)

            dish.update(allergens)

            dishes.append(dish)

    return dishes


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/extract-full-day", methods=["POST"])
def extract_full_day():

    if "file" not in request.files:
        return jsonify({
            "success": False,
            "error": "No file uploaded"
        }), 400

    file = request.files["file"]

    filename = secure_filename(file.filename)

    path = os.path.join(UPLOAD_FOLDER, filename)

    file.save(path)

    if filename.lower().endswith(".pdf"):
        raw_text = extract_text_from_pdf(path)
    else:
        raw_text = file.read().decode("utf-8", errors="ignore")

    dishes = parse_pdf_pages(raw_text)

    return jsonify({
        "success": True,
        "count": len(dishes),
        "dishes": dishes
    })


@app.route("/enhance", methods=["POST"])
def enhance():

    data = request.json or {}

    translated = ai_translate(data)

    return jsonify({
        "success": True,
        "dish": translated
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
