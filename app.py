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
    r"\bgluten\b": ("Gluten", "גלוטן"),
    r"\bwheat\b": ("Wheat", "חיטה"),
    r"\begg\b|\beggs\b": ("Eggs", "ביצים"),
    r"\bmilk\b|\bdairy\b": ("Milk", "חלב"),
    r"\bsoy\b|\bsoya\b": ("Soy", "סויה"),
    r"\bsesame\b": ("Sesame", "שומשום"),
    r"\bmustard\b": ("Mustard", "חרדל"),
    r"\blupin\b": ("Lupin", "לופין"),
    r"\bfish\b": ("Fish", "דגים"),
    r"\bnut\b|\bnuts\b": ("Nuts", "אגוזים"),
    r"\bpeanut\b|\bpeanuts\b": ("Peanuts", "בוטנים"),
    r"\bcelery\b": ("Celery", "סלרי"),
    r"\bsulfites\b|\bsulphites\b": ("Sulfites", "סולפיטים"),
}

CULINARY_HE_REPLACEMENTS = {
    "lemon grass": "למון גראס",
    "lemongrass": "למון גראס",
    "lemon-grass": "למון גראס",
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
    text = text.replace("and and", "and")
    text = text.replace("beaf", "beef")
    text = text.replace("tomatoes salad", "tomato salad")
    return text.strip()


def clean_ingredients_for_display(ingredients):
    if not ingredients:
        return ""
    ingredients = re.sub(r"\([^)]*\)", "", ingredients)
    ingredients = re.sub(r"\s+,", ",", ingredients)
    ingredients = re.sub(r",\s*,", ",", ingredients)
    ingredients = re.sub(r"\s{2,}", " ", ingredients)
    return clean_text(ingredients).strip(" ,.")


def post_process_hebrew(text):
    if not text:
        return ""

    result = text

    for eng, heb in CULINARY_HE_REPLACEMENTS.items():
        result = re.sub(eng, heb, result, flags=re.IGNORECASE)

    result = result.replace("שatta", "שאטה")
    result = result.replace("למון גראס,", "למון גראס,")
    result = result.replace("חמוץ מתוק", "חמוץ-מתוק")

    return result.strip()


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
    found_en = []
    found_he = []

    order_he = [
        "גלוטן", "חיטה", "ביצים", "חלב", "דגים", "סויה",
        "שומשום", "חרדל", "לופין", "אגוזים", "בוטנים",
        "סלרי", "סולפיטים"
    ]

    for pattern, (en, he) in ALLERGEN_PATTERNS.items():
        if re.search(pattern, text_l):
            if en not in found_en:
                found_en.append(en)
            if he not in found_he:
                found_he.append(he)

    combined = list(zip(found_en, found_he))
    combined.sort(key=lambda pair: order_he.index(pair[1]) if pair[1] in order_he else 999)

    return {
        "allergens_en": ", ".join([x[0] for x in combined]),
        "allergens_he": ", ".join([x[1] for x in combined]),
        "allergens": ", ".join([x[1] for x in combined])
    }


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


def is_price_line(line):
    return bool(re.search(r"₪\s*\d+", line) or re.fullmatch(r"\d+(\.\d+)?", line))


def clean_price(line):
    price = re.sub(r"[^\d.]", "", line or "")
    return price.replace(".00", "").strip() or "55"


def is_bad_generic_description(description, name, category):
    if not description:
        return True

    d = description.lower().strip()
    n = (name or "").lower().strip()
    c = (category or "").lower().strip()

    bad_phrases = [
        "pizza of the day",
        "soup of the day",
        "dish of the day",
        "special of the day"
    ]

    if d in bad_phrases:
        return True

    if any(phrase in d for phrase in bad_phrases):
        cleaned = d
        for phrase in bad_phrases:
            cleaned = cleaned.replace(phrase, "")
        cleaned = cleaned.replace(n, "").replace("pizza", "").replace("soup", "").strip()
        if len(cleaned) < 8:
            return True

    if n and d == n:
        return True

    if c and d == c:
        return True

    return False


def parse_text(text):
    text = clean_text(text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    dishes = []
    current = None
    ingredient_mode = False
    description_mode = False

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
            description_mode = False
            continue

        if current is None:
            continue

        if is_price_line(line):
            current["price"] = clean_price(line)
            ingredient_mode = False
            description_mode = True
            continue

        if line.lower().startswith("ingredients"):
            ing = line.split(":", 1)[-1].strip() if ":" in line else ""
            current["ingredients"] = ing
            ingredient_mode = True
            description_mode = False
            continue

        if ingredient_mode:
            current["ingredients"] += " " + line
            continue

        if not current["name"]:
            current["name"] = line
            continue

        if line == current["name"]:
            description_mode = False
            continue

        if description_mode:
            current["description"] += (" " if current["description"] else "") + line
            continue

        if not current["description"]:
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

    needs_description = not dish.get("description_en", "").strip()

    prompt = {
        "station": dish.get("category", ""),
        "kosher": dish.get("kosher", ""),
        "name_en": dish.get("name_en", ""),
        "description_en": dish.get("description_en", ""),
        "ingredients_en": dish.get("ingredients_en", ""),
        "needs_description_from_ingredients": needs_description
    }

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": """
You are a professional culinary Hebrew translator for Apple Herzliya Caffè Macs.
Return JSON only.

Rules:
- Translate only the Hebrew fields.
- Do not decide kosher.
- Do not decide station/category.
- Do not decide allergens.
- Do not invent ingredients.
- Do not add marketing language.
- Do not add adjectives like delicious, delightful, rich, indulgent, exciting, amazing, unless they appear in the source.
- Dish name should be a professional Hebrew menu name, accurate to the English.
- If description_en exists, description_he must be an accurate translation of it.
- Do not rewrite description_en creatively.
- If description_en is empty or generic, create one neutral short description using only name_en and ingredients_en.
- Keep the tone neutral, professional and culinary.
- Ingredients should be translated to Hebrew, comma separated.
- Translate/normalize culinary terms consistently:
  lemongrass / lemon grass = למון גראס
  stracciatella = סטרצ׳יאטלה
  yuzu = יוזו
  miso = מיסו
  panko = פנקו
  aioli = איולי
  brioche = בריוש
  kimchi = קימצ׳י
  shatta = שאטה
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
            "name_he": post_process_hebrew(data.get("name_he") or fallback["name_he"]),
            "description_he": post_process_hebrew(data.get("description_he") or fallback["description_he"]),
            "ingredients_he": post_process_hebrew(data.get("ingredients_he") or fallback["ingredients_he"])
        }

    except Exception:
        return fallback


def normalize_dish(raw):
    category, raw_kosher = split_category(raw.get("category_raw", ""))
    kosher = map_kosher(category, raw_kosher)

    raw_ingredients = clean_text(raw.get("ingredients", ""))
    name_en = clean_text(raw.get("name", ""))
    description_en = clean_text(raw.get("description", ""))

    if is_bad_generic_description(description_en, name_en, category):
        description_en = ""

    dish = {
        "category": category,
        "kosher": kosher,
        "name_en": name_en,
        "description_en": description_en,
        "ingredients_en": clean_ingredients_for_display(raw_ingredients),
        "price": raw.get("price", "55")
    }

    allergens = extract_allergens(raw_ingredients)
    dish.update(allergens)

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
        "ingredients_en": clean_ingredients_for_display(data.get("ingredients_en", "")),
        "price": data.get("price", "55")
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
        "ingredients_en": clean_ingredients_for_display(data.get("ingredients_en", "")),
        "allergens": data.get("allergens", ""),
        "allergens_en": data.get("allergens_en", ""),
        "allergens_he": data.get("allergens_he", ""),
        "price": data.get("price", "55")
    }

    return jsonify({
        "success": True,
        "display": display
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
