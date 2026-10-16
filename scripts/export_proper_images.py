"""Export high-resolution chest X-ray images and an interactive HTML viewer."""

from pathlib import Path
import base64
import io
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image

OUT_DIR = Path("proper_images")
OUT_DIR.mkdir(exist_ok=True)

hospitals = {
    "Hospital A": Path("data/hospital_a/shard.npz"),
    "Hospital B": Path("data/hospital_b/shard.npz"),
    "Hospital C": Path("data/hospital_c/shard.npz"),
    "Server Test Set": Path("data/server/test.npz"),
}

records = []

# Collect and export high-res samples
for name, path in hospitals.items():
    if not path.exists():
        continue
    data = np.load(path)
    images = data["images"]
    labels = data["labels"]

    # Pick samples: 2 normal (0) and 2 pneumonia (1)
    normal_idx = np.where(labels == 0)[0][:3]
    pneumonia_idx = np.where(labels == 1)[0][:3]

    for category, indices in [("Normal", normal_idx), ("Pneumonia", pneumonia_idx)]:
        for i, idx in enumerate(indices):
            raw_img = images[idx]
            # Resize from 64x64 to crisp 512x512 with bicubic interpolation
            pil_img = Image.fromarray(raw_img).resize((512, 512), Image.Resampling.BICUBIC)

            clean_name = f"{name.lower().replace(' ', '_')}_{category.lower()}_{i+1}.png"
            file_path = OUT_DIR / clean_name
            pil_img.save(file_path)

            # Also buffer base64 for html
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")

            records.append({
                "hospital": name,
                "label_name": category,
                "label_id": int(labels[idx]),
                "sample_index": int(idx),
                "file_name": clean_name,
                "b64": b64_str
            })

# Generate a high-resolution 4x4 comparison chart
fig, axes = plt.subplots(4, 4, figsize=(14, 14), dpi=200)
fig.patch.set_facecolor("#0f172a")

for ax, rec in zip(axes.flat, records[:16]):
    img_path = OUT_DIR / rec["file_name"]
    img = Image.open(img_path)
    ax.imshow(img, cmap="bone")
    ax.axis("off")
    color = "#ef4444" if rec["label_name"] == "Pneumonia" else "#22c55e"
    ax.set_title(
        f"{rec['hospital']}\n{rec['label_name']} (idx: {rec['sample_index']})",
        color=color,
        fontsize=11,
        fontweight="bold",
        pad=8
    )

plt.suptitle("FedMed — PneumoniaMNIST Chest X-Ray Clinical View", color="#f8fafc", fontsize=18, fontweight="bold", y=0.98)
plt.tight_layout(rect=[0, 0.02, 1, 0.95])
chart_path = OUT_DIR / "xray_grid_comparison.png"
plt.savefig(chart_path, facecolor=fig.get_facecolor(), bbox_inches="tight")
plt.close()

# Generate a sleek HTML viewer
cards_html = ""
for r in records:
    is_pneumonia = r["label_name"] == "Pneumonia"
    badge_bg = "rgba(239, 68, 68, 0.15)" if is_pneumonia else "rgba(34, 197, 94, 0.15)"
    badge_color = "#f87171" if is_pneumonia else "#4ade80"
    badge_border = "rgba(239, 68, 68, 0.3)" if is_pneumonia else "rgba(34, 197, 94, 0.3)"

    cards_html += f"""
    <div class="card" data-diagnosis="{r['label_name'].lower()}" data-hospital="{r['hospital']}">
      <div class="img-wrapper">
        <img src="data:image/png;base64,{r['b64']}" alt="{r['label_name']} X-Ray" />
      </div>
      <div class="card-info">
        <div class="card-header">
          <span class="hospital-tag">{r['hospital']}</span>
          <span class="badge" style="background:{badge_bg}; color:{badge_color}; border:1px solid {badge_border};">
            {r['label_name']}
          </span>
        </div>
        <div class="meta">Sample #{r['sample_index']} &bull; 512 &times; 512 HD</div>
      </div>
    </div>
    """

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>FedMed Medical Image Viewer</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Plus Jakarta Sans', sans-serif;
      background: #090d16;
      color: #f1f5f9;
      min-height: 100vh;
      padding: 32px 24px;
    }}
    .header {{
      max-width: 1200px;
      margin: 0 auto 32px;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      padding-bottom: 24px;
    }}
    h1 {{
      font-size: 26px;
      font-weight: 700;
      background: linear-gradient(135deg, #38bdf8, #818cf8);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .subtitle {{
      color: #94a3b8;
      font-size: 14px;
      margin-top: 4px;
    }}
    .filter-bar {{
      display: flex;
      gap: 8px;
    }}
    .btn {{
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.12);
      color: #cbd5e1;
      padding: 8px 16px;
      border-radius: 8px;
      cursor: pointer;
      font-weight: 500;
      font-size: 13px;
      transition: all 0.2s ease;
    }}
    .btn:hover, .btn.active {{
      background: #38bdf8;
      color: #090d16;
      border-color: #38bdf8;
      font-weight: 600;
    }}
    .grid {{
      max-width: 1200px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 20px;
    }}
    .card {{
      background: #111827;
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid rgba(255,255,255,0.06);
      transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
    }}
    .card:hover {{
      transform: translateY(-4px);
      border-color: rgba(56, 189, 248, 0.4);
      box-shadow: 0 12px 30px rgba(0,0,0,0.4);
    }}
    .img-wrapper {{
      width: 100%;
      aspect-ratio: 1;
      background: #000;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .img-wrapper img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      filter: contrast(1.15) brightness(1.05);
    }}
    .card-info {{
      padding: 14px 16px;
    }}
    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;
    }}
    .hospital-tag {{
      font-size: 13px;
      font-weight: 600;
      color: #e2e8f0;
    }}
    .badge {{
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      padding: 3px 8px;
      border-radius: 6px;
    }}
    .meta {{
      font-size: 12px;
      color: #64748b;
    }}
    .summary-box {{
      max-width: 1200px;
      margin: 0 auto 24px;
      background: rgba(56, 189, 248, 0.04);
      border: 1px solid rgba(56, 189, 248, 0.15);
      border-radius: 10px;
      padding: 14px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <h1>FedMed Chest X-Ray Intelligence Viewer</h1>
      <div class="subtitle">Inspecting PneumoniaMNIST partitioned dataset shards across 3 hospital federations</div>
    </div>
    <div class="filter-bar">
      <button class="btn active" onclick="filterImages('all', this)">All Images</button>
      <button class="btn" onclick="filterImages('normal', this)">Normal Only</button>
      <button class="btn" onclick="filterImages('pneumonia', this)">Pneumonia Only</button>
    </div>
  </div>

  <div class="summary-box">
    <span><strong>Dataset:</strong> PneumoniaMNIST &bull; <strong>Modality:</strong> Pediatric Chest Radiographs &bull; <strong>Labels:</strong> 0 = Normal, 1 = Pneumonia</span>
    <span style="color:#38bdf8;">High-Definition Bi-Cubic Upscaled</span>
  </div>

  <div class="grid" id="imageGrid">
    {cards_html}
  </div>

  <script>
    function filterImages(type, btn) {{
      document.querySelectorAll('.filter-bar .btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const cards = document.querySelectorAll('.card');
      cards.forEach(card => {{
        if (type === 'all' || card.getAttribute('data-diagnosis') === type) {{
          card.style.display = 'block';
        }} else {{
          card.style.display = 'none';
        }}
      }});
    }}
  </script>
</body>
</html>
"""

html_path = Path("medical_images_viewer.html")
html_path.write_text(html_content, encoding="utf-8")
print(f"Exported {len(records)} HD images to {OUT_DIR}/")
print(f"Saved comparison grid to {chart_path}")
print(f"Created HTML viewer at {html_path.resolve()}")
