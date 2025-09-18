import gradio as gr, requests, os

API = os.getenv("API_BASE", "http://127.0.0.1:8000")

def load_banner():
    try:
        c = requests.get(f"{API}/campaign/current", timeout=10).json()
        top = ", ".join(c.get("seed_list", [])) or "surprise picks"
        return f"**{c.get('title','Weekly Campaign')}**  \n{c.get('prize_rules','')}  \n_Featured IDs:_ {top}"
    except Exception:
        return "**Reading Week**  \nRead 1 book to enter the prize drawing!"

def get_top5(grade, interests, bucket):
    """
    Returns: (cards_json, error_markdown_update)
    If an error occurs or Pydantic 422 is returned, we surface a red box with details.
    """
    try:
        # 1) Recommend
        rec_resp = requests.post(
            f"{API}/recommend",
            json={"grade": int(grade), "interests": interests or [], "progress_bucket": bucket, "top_k": 10},
            timeout=20,
        )
        rec_resp.raise_for_status()
        cands = rec_resp.json().get("candidates", [])

        # 2) Justify (Hermes-3)
        jus_resp = requests.post(
            f"{API}/justify",
            json={
                "candidates": cands,
                "student": {"grade": int(grade), "interests": interests or [], "progress_bucket": bucket},
                "notes": None,
            },
            timeout=120,
        )

        # If Hermes-3 drifted, API returns a 422 with detail—show it
        if jus_resp.status_code != 200:
            try:
                detail = jus_resp.json().get("detail", "Validation failed.")
            except Exception:
                detail = f"Validation failed with status {jus_resp.status_code}."
            msg = f"❌ Recommendation explanation failed:\n\n```\n{detail}\n```"
            return [], gr.update(value=msg, visible=True)

        data = jus_resp.json()
        items = data.get("items", [])
        title_by_id = {c["catalog_id"]: c["payload"]["title"] for c in cands}
        cards = [
            {
                "title": title_by_id.get(it["catalog_id"], it["catalog_id"]),
                "pitch": it.get("pitch", ""),
                "why": it.get("why", ""),
                "shelf": it.get("shelf", ""),
            }
            for it in items
        ]
        # Success → hide error box
        return cards, gr.update(value="", visible=False)

    except Exception as e:
        msg = f"❌ Error talking to API:\n\n```\n{e}\n```"
        return [], gr.update(value=msg, visible=True)

def refresh_report():
    # Placeholder until metrics tables are wired; keeps UI flowing
    return {
        "checkout_rate_per_student": "0.48 (last 7d)",
        "acceptance_rate": "63%",
        "selection_to_checkout": "41%",
        "repeat_30d": "22%",
        "repeat_60d": "37%",
        "campaign_lift": "+18%",
    }

with gr.Blocks(title="Reading Assistant", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 📚 Reading Assistant (MVP with Hermes-3)")
    with gr.Tab("Student Assistant"):
        banner = gr.Markdown("Loading weekly campaign…")
        with gr.Row():
            grade = gr.Dropdown(["3","4","5","6"], value="5", label="Grade")
            interests = gr.CheckboxGroup(
                ["sports","animals","fantasy","mystery","graphic novels","short reads","technology","nature"],
                label="Pick a couple interests"
            )
            bucket = gr.Dropdown(["starter","building","streak"], value="starter", label="Reading progress")
    btn = gr.Button("Get my Top 5")
    out = gr.JSON(label="Your picks")
    error_box = gr.Markdown(visible=False)  # <-- NEW: error surface

    demo.load(load_banner, outputs=[banner])
    btn.click(get_top5, [grade, interests, bucket], [out, error_box])

    with gr.Tab("Librarian Console"):
        gr.Markdown("### Weekly KPIs")
        rpt_btn = gr.Button("Refresh Report")
        kpis = gr.JSON()
        rpt_btn.click(refresh_report, outputs=[kpis])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
