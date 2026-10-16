import { useMemo, useRef, useState } from "react";
import { predict } from "../api";

const LABEL_COLORS = {
  normal: "var(--series-1)",
  pneumonia: "var(--series-2)",
};

export default function ImageGalleryPanel({
  images,
  onAddImage,
  onRemoveUpload,
  onSelectImage,
  modelRound,
}) {
  const [filter, setFilter] = useState("all");
  const [selectedImage, setSelectedImage] = useState(null);
  const [classifyingId, setClassifyingId] = useState(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const fileInputRef = useRef(null);

  const handleUpload = async (file) => {
    if (!file) return;
    setUploadBusy(true);

    const reader = new FileReader();
    reader.onload = async (e) => {
      const dataUrl = e.target.result;
      const newImage = {
        id: `upload-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`,
        url: dataUrl,
        name: file.name,
        source: "User Upload",
        label: "pending",
        isDataset: false,
        uploadedAt: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        fileObject: file,
      };

      // Add to gallery right away so the user sees it immediately
      onAddImage(newImage);

      // Attempt immediate classification if API is running
      try {
        setClassifyingId(newImage.id);
        const result = await predict(file);
        newImage.prediction = result;
        newImage.label = result.label;
        onAddImage(newImage); // update with result
      } catch (err) {
        console.warn("Auto-classification failed (API offline or busy):", err);
      } finally {
        setClassifyingId(null);
        setUploadBusy(false);
      }
    };
    reader.readAsDataURL(file);
  };

  const handleClassifySample = async (item) => {
    if (item.prediction) {
      setSelectedImage(item);
      return;
    }

    try {
      setClassifyingId(item.id);
      // Fetch the sample image blob to pass to the API
      const res = await fetch(item.url);
      const blob = await res.blob();
      const file = new File([blob], item.name, { type: "image/png" });
      const result = await predict(file);

      const updated = { ...item, prediction: result };
      onAddImage(updated);
      setSelectedImage(updated);
      if (onSelectImage) onSelectImage(file, result);
    } catch (err) {
      alert(`Prediction error: ${err.message}`);
    } finally {
      setClassifyingId(null);
    }
  };

  const filteredImages = useMemo(() => {
    return images.filter((img) => {
      if (filter === "all") return true;
      if (filter === "uploads") return !img.isDataset;
      if (filter === "normal") return img.label?.toLowerCase() === "normal";
      if (filter === "pneumonia") return img.label?.toLowerCase() === "pneumonia";
      if (filter === "hospital-a") return img.source === "Hospital A";
      if (filter === "hospital-b") return img.source === "Hospital B";
      if (filter === "hospital-c") return img.source === "Hospital C";
      if (filter === "test") return img.source === "Global Test Set";
      return true;
    });
  }, [images, filter]);

  const userUploadsCount = images.filter((i) => !i.isDataset).length;

  return (
    <div className="card" style={{ marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 style={{ margin: 0 }}>PneumoniaMNIST Medical Image Intelligence</h2>
          <p className="subtitle" style={{ marginTop: 4, marginBottom: 12 }}>
            Real chest X-ray scans partitioned across hospital silos. Upload your own scan to inspect and classify it live.
          </p>
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <input
            type="file"
            ref={fileInputRef}
            accept="image/*"
            style={{ display: "none" }}
            onChange={(e) => {
              if (e.target.files?.[0]) handleUpload(e.target.files[0]);
              e.target.value = "";
            }}
          />
          <button
            className="action-btn"
            style={{
              background: "var(--series-1)",
              color: "#fff",
              border: "none",
              borderRadius: "var(--radius)",
              padding: "8px 16px",
              fontWeight: 600,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadBusy}
          >
            <span>+</span> {uploadBusy ? "Processing..." : "Upload New X-Ray"}
          </button>
        </div>
      </div>

      {/* Filter Tabs */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "14px 0 18px", borderBottom: "1px solid var(--border)", paddingBottom: 12 }}>
        {[
          { key: "all", label: `All Images (${images.length})` },
          { key: "uploads", label: `My Uploads (${userUploadsCount})` },
          { key: "normal", label: "Normal" },
          { key: "pneumonia", label: "Pneumonia" },
          { key: "hospital-a", label: "Hospital A" },
          { key: "hospital-b", label: "Hospital B" },
          { key: "hospital-c", label: "Hospital C" },
          { key: "test", label: "Global Test" },
        ].map((tab) => (
          <button
            key={tab.key}
            style={{
              padding: "5px 12px",
              borderRadius: 6,
              fontSize: 12,
              fontWeight: filter === tab.key ? 600 : 400,
              background: filter === tab.key ? "var(--text-primary)" : "transparent",
              color: filter === tab.key ? "var(--page-plane)" : "var(--text-secondary)",
              border: "1px solid var(--border)",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
            onClick={() => setFilter(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Gallery Grid */}
      {filteredImages.length === 0 ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
          No images found for filter "{filter}".
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
            gap: 14,
          }}
        >
          {filteredImages.map((img) => {
            const isUserUpload = !img.isDataset;
            const isPneumonia = img.label?.toLowerCase() === "pneumonia";
            const isNormal = img.label?.toLowerCase() === "normal";
            const badgeBg = isPneumonia
              ? "rgba(235, 104, 52, 0.15)"
              : isNormal
              ? "rgba(42, 120, 214, 0.15)"
              : "rgba(128, 128, 128, 0.15)";
            const badgeColor = isPneumonia
              ? "var(--series-2)"
              : isNormal
              ? "var(--series-1)"
              : "var(--text-muted)";

            return (
              <div
                key={img.id}
                style={{
                  background: "var(--surface-1)",
                  border: isUserUpload ? "2px solid var(--series-1)" : "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                  overflow: "hidden",
                  display: "flex",
                  flexDirection: "column",
                  position: "relative",
                  transition: "transform 0.15s ease, box-shadow 0.15s ease",
                  cursor: "pointer",
                }}
                onClick={() => setSelectedImage(img)}
              >
                {/* Uploaded Badge */}
                {isUserUpload && (
                  <div
                    style={{
                      position: "absolute",
                      top: 6,
                      left: 6,
                      background: "var(--series-1)",
                      color: "#fff",
                      fontSize: 10,
                      fontWeight: 700,
                      padding: "2px 6px",
                      borderRadius: 4,
                      zIndex: 2,
                    }}
                  >
                    NEW UPLOAD
                  </div>
                )}

                {/* Remove button for custom uploads */}
                {isUserUpload && onRemoveUpload && (
                  <button
                    style={{
                      position: "absolute",
                      top: 6,
                      right: 6,
                      background: "rgba(0,0,0,0.6)",
                      color: "#fff",
                      border: "none",
                      borderRadius: "50%",
                      width: 22,
                      height: 22,
                      cursor: "pointer",
                      fontSize: 11,
                      zIndex: 3,
                    }}
                    title="Remove upload"
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemoveUpload(img.id);
                    }}
                  >
                    &times;
                  </button>
                )}

                <div
                  style={{
                    width: "100%",
                    aspectRatio: "1",
                    background: "#000",
                    position: "relative",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <img
                    src={img.url}
                    alt={img.name}
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "contain",
                      imageRendering: "auto",
                    }}
                  />
                  {classifyingId === img.id && (
                    <div
                      style={{
                        position: "absolute",
                        inset: 0,
                        background: "rgba(0,0,0,0.7)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#fff",
                        fontSize: 12,
                        fontWeight: 600,
                      }}
                    >
                      Classifying...
                    </div>
                  )}
                </div>

                <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span
                      style={{
                        fontSize: 11,
                        color: "var(--text-secondary)",
                        fontWeight: 600,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        maxWidth: 90,
                      }}
                      title={img.source}
                    >
                      {img.source}
                    </span>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: "uppercase",
                        padding: "2px 6px",
                        borderRadius: 4,
                        background: badgeBg,
                        color: badgeColor,
                      }}
                    >
                      {img.label}
                    </span>
                  </div>

                  <div
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: "var(--text-primary)",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                    title={img.name}
                  >
                    {img.name}
                  </div>

                  {img.prediction ? (
                    <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 2 }}>
                      Confidence: {(img.prediction.confidence * 100).toFixed(1)}%
                    </div>
                  ) : (
                    <button
                      style={{
                        marginTop: 4,
                        padding: "3px 8px",
                        fontSize: 10,
                        borderRadius: 4,
                        border: "1px solid var(--border)",
                        background: "transparent",
                        color: "var(--text-secondary)",
                        cursor: "pointer",
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleClassifySample(img);
                      }}
                    >
                      Classify with Model
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Lightbox Modal for detail inspection */}
      {selectedImage && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0, 0, 0, 0.75)",
            backdropFilter: "blur(4px)",
            zIndex: 9999,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 20,
          }}
          onClick={() => setSelectedImage(null)}
        >
          <div
            style={{
              background: "var(--surface-1)",
              borderRadius: "var(--radius)",
              border: "1px solid var(--border)",
              maxWidth: 580,
              width: "100%",
              overflow: "hidden",
              boxShadow: "0 20px 40px rgba(0,0,0,0.5)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                padding: "16px 20px",
                borderBottom: "1px solid var(--border)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: 16 }}>{selectedImage.name}</h3>
                <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                  Source: {selectedImage.source} {selectedImage.uploadedAt ? `• Uploaded at ${selectedImage.uploadedAt}` : ""}
                </span>
              </div>
              <button
                onClick={() => setSelectedImage(null)}
                style={{
                  background: "transparent",
                  border: "none",
                  fontSize: 22,
                  cursor: "pointer",
                  color: "var(--text-secondary)",
                }}
              >
                &times;
              </button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: 20, background: "#05070c" }}>
              <img
                src={selectedImage.url}
                alt={selectedImage.name}
                style={{
                  maxWidth: "100%",
                  maxHeight: 320,
                  objectFit: "contain",
                  borderRadius: 6,
                  border: "1px solid rgba(255,255,255,0.1)",
                }}
              />
            </div>

            <div style={{ padding: "16px 20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <span style={{ fontSize: 14, fontWeight: 600 }}>Diagnosis Status:</span>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    padding: "4px 10px",
                    borderRadius: 6,
                    background:
                      selectedImage.label === "pneumonia"
                        ? "rgba(235, 104, 52, 0.2)"
                        : "rgba(42, 120, 214, 0.2)",
                    color:
                      selectedImage.label === "pneumonia"
                        ? "var(--series-2)"
                        : "var(--series-1)",
                  }}
                >
                  {selectedImage.label}
                </span>
              </div>

              {selectedImage.prediction ? (
                <div>
                  <div style={{ fontSize: 13, marginBottom: 8, color: "var(--text-secondary)" }}>
                    Federated Model Confidence:{" "}
                    <strong>{(selectedImage.prediction.confidence * 100).toFixed(1)}%</strong>
                    {selectedImage.prediction.model_round && ` (Round ${selectedImage.prediction.model_round})`}
                  </div>
                  {Object.entries(selectedImage.prediction.probabilities || {}).map(([lbl, p]) => (
                    <div key={lbl} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, marginBottom: 6 }}>
                      <span style={{ width: 70, textTransform: "capitalize" }}>{lbl}</span>
                      <div style={{ flex: 1, height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
                        <div
                          style={{
                            width: `${p * 100}%`,
                            height: "100%",
                            background: LABEL_COLORS[lbl] || "var(--series-1)",
                          }}
                        />
                      </div>
                      <span style={{ width: 45, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                        {(p * 100).toFixed(1)}%
                      </span>
                    </div>
                  ))}
                  {selectedImage.prediction.request_hash && (
                    <p style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--text-muted)", marginTop: 10 }}>
                      SHA-256: {selectedImage.prediction.request_hash.slice(0, 32)}...
                    </p>
                  )}
                </div>
              ) : (
                <button
                  style={{
                    width: "100%",
                    padding: "10px",
                    background: "var(--series-1)",
                    color: "#fff",
                    border: "none",
                    borderRadius: "var(--radius)",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                  onClick={() => handleClassifySample(selectedImage)}
                  disabled={classifyingId === selectedImage.id}
                >
                  {classifyingId === selectedImage.id ? "Classifying..." : "Run Federated Model Classification"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
