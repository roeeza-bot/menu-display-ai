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
    "grill", "chef special", "sandwich", "soup",
    "sushi", "sushi station", "meat station", "chicken station"
]

DAIRY_STATIONS = [
    "fish special", "pizza", "bakery", "veg", "vegan",
    "vegetarian", "fish station", "pizza station"
]

SIDE_DISH_NAMES = {
    "rice", "french fries", "fries", "puree", "polenta",
    "roasted vegetables", "healthy carb side dish", "coconut rice",
    "saffron rice", "oshpelo", "rizo", "sushi rice", "small salad",
    "bread", "tofu", "roasted tofu", "hard boiled egg", "tuna",
    "small chicken breast", "chicken breast", "antipasti",
    "freekeh & vegetables"
}

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
    r"\bwine\b|\bred wine\b|\bwhite wine\b|\bmirin\b|\balcohol\b": ("Alcohol", "אלכוהול"),
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
    "mushroom": "פטריות",
    "mushrooms": "פטריות",
    "radish": "צנון",
    "radishes": "צנון",
}


def clean_text(text):
    if not text:
        return ""
    text = text.replace("\r", "\n")
    text = text.replace("", "")
    text = text.replace("￾", "")
    text = text.replace("and and", "and")
    text = text.replace("beaf", "beef")
    text = text.replace("tomatoes salad", "tomato salad")
    text = text.replace("Ram#", "Ramen")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def clean_price(value):
    if not value:
        return "55"
    cleaned = re.sub(r"[^\d.]", "", value)
    cleaned = cleaned.replace(".00", "")
    return cleaned or "55"


def clean_ingredients_for_display(ingredients):
    if not ingredients:
        return ""
    ingredients = re.sub(r"\([^)]*\)", "", ingredients)
    ingredients = re.sub(r"\bIngredients:\s*", "", ingredients, flags=re.IGNORECASE)
    ingredients = re.sub(r"\bContains:\s*", "", ingredients, flags=re.IGNORECASE)
    ingredients = re.sub(r"\s+\.", ".", ingredients)
    ingredients = re.sub(r"\s+,", ",", ingredients)
    ingredients = re.sub(r",\s*,", ",", ingredients)
    ingredients = re.sub(r"\s{2,}", " ", ingredients)
    ingredients = ingredients.replace(" .", ".").replace("..", ".")
    return clean_text(ingredients).strip(" ,.")


def clean_sushi_ingredients(text):
    if not text:
        return ""
    text = clean_text(text)
    text = re.sub(r"\s+\.", ".", text)
    text = re.sub(r"\s+\,", ",", text)
    text = re.sub(r"\.\s*$", "", text)
    text = text.replace(" .", ".").replace("..", ".")
    return text.strip()


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


def extract_raw_text_from_request():
    if "file" in request.files:
        file = request.files["file"]
        filename = secure_filename(file.filename)
        path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(path)

        if filename.lower().endswith(".pdf"):
            return extract_text_from_pdf(path)

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    data = request.json or {}
    return data.get("text", "")


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
        result = re.sub(rf"\b{re.escape(eng)}\b", heb, result, flags=re.IGNORECASE)

    result = result.replace("רדיקי", "צנון")
    result = result.replace(" .", ".").replace("..", ".")

    return result.strip()


def ai_translate(dish):
    fallback = {
        "name_he": dish.get("name_en", ""),
        "description_he": dish.get("description_en", ""),
        "ingredients_he": dish.get("ingredients_en", "")
    }

    if client is None:
        return fallback

    for attempt in range(2):
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
- Translate to professional culinary Hebrew.
- Keep sushi terminology accurate.
- Do not invent ingredients.
- Do not change dish meaning.
- Keep translations short and elegant.
- Translate ingredients only from the ingredients field.
- Translate description only from the description field.
- Do not move description into ingredients.
- Translate mushroom and mushrooms as פטריות.
- Translate radish and radishes as צנון, never רדיקי.
- For sushi:
  Fish Sushi = סושי דגים
  Vegetarian Sushi = סושי צמחוני
  Fish Combination = קומבינציית סושי דגים
  Vegan Combination = קומבינציית סושי טבעונית
  I/O = רול אינסייד-אאוט
  Maki = מאקי
  Sashimi = סשימי
  Nigiri = ניגירי

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
            continue

    return fallback


def is_price_line(line):
    return bool(re.search(r"₪\s*\d+", line or ""))


def looks_like_title(line):
    if not line:
        return False

    l = line.strip().lower()

    if l.startswith("ingredients"):
        return False
    if l.startswith("contains"):
        return False
    if is_price_line(line):
        return False
    if len(line) > 70:
        return False
    if "," in line:
        return False

    return True


def find_price_index(lines, start, max_lookahead=3):
    end = min(len(lines), start + max_lookahead + 1)

    for i in range(start, end):
        if is_price_line(lines[i]):
            return i

    return None


def find_dish_starts(lines):
    starts = []

    for i, line in enumerate(lines):
        if not looks_like_title(line):
            continue

        price_index = find_price_index(lines, i + 1, 3)

        if price_index is not None:
            starts.append((i, price_index))

    cleaned = []
    used_prices = set()

    for start, price in starts:
        if price in used_prices:
            continue
        cleaned.append((start, price))
        used_prices.add(price)

    return cleaned


def is_sushi_station(station):
    return "sushi" in (station or "").lower()


def is_salad_bar_station(station):
    return "salad" in (station or "").lower()


def is_sushi_dish_name(line):
    l = (line or "").strip().lower()
    return l in {
        "fish sushi",
        "vegetarian sushi",
        "fish combination",
        "vegan combination"
    }


def is_sushi_section_name(line):
    l = (line or "").strip().lower()
    return l in {
        "i/o",
        "io",
        "maki",
        "sashimi",
        "nigiri",
        "futomaki",
        "hosomaki",
        "fried hosomaki",
        "sushi rice"
    }


def find_sushi_starts(lines):
    starts = []

    for i, line in enumerate(lines):
        if not is_sushi_dish_name(line):
            continue

        price_index = find_price_index(lines, i + 1, 3)

        if price_index is not None:
            starts.append((i, price_index))

    return starts


def parse_sushi_segment(station, name, price, segment_lines):
    description_lines = []
    ingredient_lines = []
    i = 0

    while i < len(segment_lines):
        line = clean_text(segment_lines[i])
        next_line = clean_text(segment_lines[i + 1]) if i + 1 < len(segment_lines) else ""

        if not line:
            i += 1
            continue

        if is_sushi_section_name(line) and next_line.lower().startswith("ingredients"):
            section_name = line
            ing = next_line.split(":", 1)[-1].strip() if ":" in next_line else ""
            parts = [ing] if ing else []
            i += 2

            while i < len(segment_lines):
                current = clean_text(segment_lines[i])
                following = clean_text(segment_lines[i + 1]) if i + 1 < len(segment_lines) else ""

                if is_sushi_section_name(current) and following.lower().startswith("ingredients"):
                    break
                if is_sushi_dish_name(current):
                    break

                parts.append(current)
                i += 1

            section_text = clean_sushi_ingredients(clean_text(" ".join(parts)))
            ingredient_lines.append(f"{section_name}: {section_text}")
            continue

        if line.lower().startswith("ingredients"):
            ing = line.split(":", 1)[-1].strip() if ":" in line else ""
            ingredient_lines.append(clean_sushi_ingredients(ing))
            i += 1
            continue

        if not ingredient_lines:
            description_lines.append(line)

        i += 1

    category = normalize_category(station)
    raw_ingredients = clean_sushi_ingredients("\n".join(ingredient_lines))

    dish = {
        "category": category,
        "kosher": map_kosher(category),
        "name_en": clean_text(name),
        "description_en": clean_text(" ".join(description_lines)),
        "ingredients_en": clean_ingredients_for_display(raw_ingredients),
        "price": clean_price(price)
    }

    allergens = extract_allergens(raw_ingredients)
    dish.update(allergens)

    dish["name_he"] = dish["name_en"]
    dish["description_he"] = dish["description_en"]
    dish["ingredients_he"] = dish["ingredients_en"]

    return dish


def parse_sushi_page(station, body_lines):
    starts = find_sushi_starts(body_lines)

    if not starts:
        return []

    dishes = []

    for idx, (start_index, price_index) in enumerate(starts):
        next_start = starts[idx + 1][0] if idx + 1 < len(starts) else len(body_lines)
        name = clean_text(" ".join(body_lines[start_index:price_index]))
        price = body_lines[price_index]
        segment = body_lines[price_index + 1:next_start]
        dishes.append(parse_sushi_segment(station, name, price, segment))

    return dishes


def parse_dish_segment(station, name, price, segment_lines):
    description_lines = []
    ingredient_lines = []
    repeated_name_seen = False
    ingredient_mode = False

    for line in segment_lines:
        clean_line = clean_text(line)

        if not clean_line:
            continue

        if clean_line == name:
            repeated_name_seen = True
            continue

        if clean_line.lower().startswith("ingredients"):
            ing = clean_line.split(":", 1)[-1].strip() if ":" in clean_line else ""
            ingredient_lines.append(ing)
            ingredient_mode = True
            continue

        if ingredient_mode:
            ingredient_lines.append(clean_line)
            continue

        if repeated_name_seen:
            continue

        description_lines.append(clean_line)

    description = clean_text(" ".join(description_lines))
    raw_ingredients = clean_text(" ".join(ingredient_lines))
    category = normalize_category(station)

    dish = {
        "category": category,
        "kosher": map_kosher(category),
        "name_en": clean_text(name),
        "description_en": description,
        "ingredients_en": clean_ingredients_for_display(raw_ingredients),
        "price": clean_price(price)
    }

    allergens = extract_allergens(raw_ingredients)
    dish.update(allergens)

    dish["name_he"] = dish["name_en"]
    dish["description_he"] = dish["description_en"]
    dish["ingredients_he"] = dish["ingredients_en"]

    return dish


def append_side_to_previous(previous_dish, side_name, side_segment_lines):
    if not previous_dish:
        return

    side_ingredients = []
    ingredient_mode = False

    for line in side_segment_lines:
        clean_line = clean_text(line)

        if not clean_line:
            continue
        if clean_line == side_name:
            continue
        if is_price_line(clean_line):
            continue

        if clean_line.lower().startswith("ingredients"):
            ing = clean_line.split(":", 1)[-1].strip() if ":" in clean_line else ""
            side_ingredients.append(ing)
            ingredient_mode = True
            continue

        if ingredient_mode:
            side_ingredients.append(clean_line)

    side_text = clean_ingredients_for_display(clean_text(" ".join(side_ingredients)))

    if side_text:
        if previous_dish.get("ingredients_en"):
            previous_dish["ingredients_en"] += f", {side_text}"
        else:
            previous_dish["ingredients_en"] = side_text

        allergens = extract_allergens(previous_dish["ingredients_en"])
        previous_dish.update(allergens)
        previous_dish["ingredients_he"] = previous_dish["ingredients_en"]


def should_skip_as_display_dish(name, price):
    normalized_name = (name or "").lower().strip()
    normalized_price = clean_price(price)

    if normalized_name in SIDE_DISH_NAMES:
        return True

    if normalized_price == "7":
        return True

    return False


def parse_regular_page(station, body):
    starts = find_dish_starts(body)

    if not starts:
        return []

    dishes = []

    for idx, (start_index, price_index) in enumerate(starts):
        next_start = starts[idx + 1][0] if idx + 1 < len(starts) else len(body)

        name = clean_text(" ".join(body[start_index:price_index]))
        price = body[price_index]
        segment = body[price_index + 1:next_start]

        if should_skip_as_display_dish(name, price):
            if dishes:
                append_side_to_previous(dishes[-1], name, segment)
            continue

        dish = parse_dish_segment(station, name, price, segment)
        dishes.append(dish)

    return dishes


def parse_page(page_text):
    page_text = clean_text(page_text)
    lines = [line.strip() for line in page_text.split("\n") if line.strip()]

    if len(lines) < 3:
        return []

    station = lines[0]

    if is_salad_bar_station(station):
        return []

    body = lines[1:]

    if is_sushi_station(station):
        return parse_sushi_page(station, body)

    return parse_regular_page(station, body)


def parse_full_day_text(text):
    if "__PAGE_BREAK__" in text:
        pages = [p.strip() for p in text.split("__PAGE_BREAK__") if p.strip()]
    else:
        pages = [text]

    dishes = []

    for page in pages:
        dishes.extend(parse_page(page))

    return dishes


def add_ai_to_dishes(dishes):
    enriched = []

    for dish in dishes:
        item = dict(dish)
        ai = ai_translate(item)

        item["name_he"] = ai["name_he"]
        item["description_he"] = ai["description_he"]
        item["ingredients_he"] = ai["ingredients_he"]

        enriched.append(item)

    return enriched


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/extract-full-day", methods=["POST"])
def extract_full_day():
    raw_text = extract_raw_text_from_request()
    dishes = parse_full_day_text(raw_text)

    return jsonify({
        "success": True,
        "count": len(dishes),
        "dishes": dishes
    })


@app.route("/extract", methods=["POST"])
def extract():
    raw_text = extract_raw_text_from_request()
    dishes = parse_full_day_text(raw_text)
    dishes = add_ai_to_dishes(dishes)

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
