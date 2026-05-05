# Menu Display AI

A simple web app for creating food display pages.

## What it does

- Receives dish information manually
- Translates only
- Does not improve, rewrite, add, or invent content
- Keeps the price exactly as entered
- Creates a printable display page
- Supports category marks:
  - Meat: red triangle
  - Dairy: blue triangle
  - Vegan: green triangle

## Files

- `app.py` - Flask backend and OpenAI translation route
- `templates/index.html` - Web interface and display page
- `requirements.txt` - Python dependencies
- `render.yaml` - Render deployment configuration

## Render setup

Add this environment variable in Render:

`OPENAI_API_KEY`

Optional:

`OPENAI_MODEL=gpt-4.1-mini`

## Local run

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="your-key"
python app.py
```