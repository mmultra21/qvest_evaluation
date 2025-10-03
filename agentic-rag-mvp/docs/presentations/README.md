Readership Campaign presentation generator

Files:
- generate_readership_deck.py — script that creates a PowerPoint deck using python-pptx
- readership_campaign_deck.pptx — generated deck (after running the script)
- readership_slides.json — optional slide outlines used as reference

How to generate the deck

1. Ensure you have python3 available.
2. Install the dependency:

```bash
python3 -m pip install --upgrade python-pptx
```

3. Run the generator:

```bash
python3 agentic-rag-mvp/docs/presentations/generate_readership_deck.py
```

The script will create `agentic-rag-mvp/docs/presentations/readership_campaign_deck.pptx`.

Notes
- The slide content is intentionally high-level; edit `generate_readership_deck.py` to customize bullets, speaker notes, or add branding.
- I can generate a second version with school branding (colors/logo) if you provide assets.
